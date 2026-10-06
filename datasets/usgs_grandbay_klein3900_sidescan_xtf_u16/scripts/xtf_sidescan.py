#!/usr/bin/env python3
"""Helpers for the USGS 2015-315-FA Grand Bay Klein side-scan XTF recipe.

Pure standard library. Subcommands:

  check-metadata  validate the FGDC metadata text (pinned SHA-256 + license phrases)
  check-cd        validate the archive tail: total size, ZIP64 EOCD, central
                  directory SHA-256, and every pinned member's CD entry
  check-range     validate one HTTP range response (206 + exact Content-Range)
  extract         validate a member's local header and inflate it with CRC32 check
  check-xtf       size + CRC32 + XTF file-header semantics of an extracted member
  list-band       discovery step 1: band candidates from the central directory
  discover        discovery step 2: apply the header filter to member prefixes
  build           emit ping-major port|starboard uint16 samples and the index
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import re
import struct
import sys
import zlib
from array import array
from pathlib import Path

DATASET_ID = "usgs_grandbay_klein3900_sidescan_xtf_u16"
SERIES_ID = "klein_sidescan_port_stbd_backscatter_u16"
ARCHIVE_BYTES = 9_843_630_446
CD_OFFSET = 9_843_618_372
CD_SIZE = 11_976
CD_ENTRIES = 145
CD_SHA256 = "1c82077476a90a00184a574b4ef7199dffd522394073e352dae21b7091974247"

XTF_FILE_HEADER_BYTES = 1024
XTF_MAGIC = 0xFACE
PING_HEADER_BYTES = 256
CHAN_HEADER_BYTES = 64
SONAR_HEADER_TYPE = 0
KLEIN_AUX_HEADER_TYPE = 108
KLEIN_AUX_RECORD_BYTES = 832

# Canonical (majority) acquisition configuration enforced on every ping.
CANON_CHANNELS = 2
CANON_SAMPLES = 4096
CANON_FREQ_FIELD = 100
CANON_SLANT_RANGE_M = 100.0
SONAR_RECORD_BYTES = PING_HEADER_BYTES + CANON_CHANNELS * (CHAN_HEADER_BYTES + 2 * CANON_SAMPLES)
PING_PAIR_BYTES = SONAR_RECORD_BYTES + KLEIN_AUX_RECORD_BYTES  # 17,600

# Discovery band (pings per recording file).
BAND_MIN_PINGS = 1000
BAND_MAX_PINGS_EXCLUSIVE = 2700

SOURCE_COLUMNS = [
    "member",
    "local_header_offset",
    "range_end",
    "compressed_bytes",
    "uncompressed_bytes",
    "crc32",
    "ping_count",
    "survey_date",
]

METADATA_PHRASES = [
    "Subbottom and Sidescan Sonar Data Acquired in 2015 From Grand Bay, Mississippi and Alabama",
    "doi:10.5066/P9374DKQ",
    "Access_Constraints: None. These data are held in the public domain.",
    "Public domain data from the U.S. Government are freely redistributable",
    "Klein 3900 dual frequency (455 and 900 kHz) towfish and Klein SonarPro version 12.1",
    "143 sidescan XTF data files",
    "https://coastal.er.usgs.gov/data-release/doi-P9374DKQ/data/2015-315-FA_xtf.zip",
]


def fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    raise SystemExit(f"FATAL: {message}")


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != SOURCE_COLUMNS:
        fail(f"unexpected sources header in {path}")
    rows = []
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != len(SOURCE_COLUMNS):
            fail(f"{path}:{number}: expected {len(SOURCE_COLUMNS)} columns")
        row = dict(zip(SOURCE_COLUMNS, parts))
        for key in ("local_header_offset", "range_end", "compressed_bytes", "uncompressed_bytes", "ping_count"):
            row[key] = int(row[key])
        if not re.fullmatch(r"15CCT03_SSS_(15[34]_)?\d{12}\.xtf", row["member"]):
            fail(f"{path}:{number}: unexpected member name {row['member']!r}")
        if (row["uncompressed_bytes"] - XTF_FILE_HEADER_BYTES) != row["ping_count"] * PING_PAIR_BYTES:
            fail(f"{path}:{number}: ping_count does not match uncompressed size")
        rows.append(row)
    names = [row["member"] for row in rows]
    if len(set(names)) != len(names):
        fail("duplicate members in sources table")
    return rows


# ---------------------------------------------------------------- HTTP / ZIP


def final_response(headers_text: str) -> tuple[int, str]:
    blocks = [b for b in re.split(r"\r?\n\r?\n", headers_text) if b.strip().startswith("HTTP/")]
    if not blocks:
        fail("no HTTP response headers recorded")
    final = blocks[-1]
    match = re.match(r"HTTP/\S+\s+(\d+)", final.strip())
    return (int(match.group(1)) if match else 0), final


def content_range(block: str) -> tuple[int, int, int]:
    match = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", block, re.IGNORECASE | re.MULTILINE)
    if not match:
        fail("response lacks a Content-Range header")
    return tuple(int(x) for x in match.groups())  # type: ignore[return-value]


def cmd_check_range(args: argparse.Namespace) -> None:
    status, block = final_response(Path(args.headers).read_text(encoding="iso-8859-1"))
    if status != 206:
        fail(f"server did not answer the range request with 206 (status={status})")
    start, end, total = content_range(block)
    if (start, end, total) != (args.start, args.end, ARCHIVE_BYTES):
        fail(f"unexpected Content-Range {start}-{end}/{total}; wanted {args.start}-{args.end}/{ARCHIVE_BYTES}")
    if args.chunk_bytes > end - start + 1:
        fail("received more bytes than requested")
    print(f"range_ok start={start} end={end} received={args.chunk_bytes}")


def parse_central_directory(cd: bytes) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    p = 0
    while p < len(cd):
        if cd[p : p + 4] != b"PK\x01\x02":
            fail(f"bad central-directory signature at +{p}")
        (flags, method, _time, _date, crc, csz, usz, nlen, elen, clen, _disk, _iattr, _eattr, lho) = struct.unpack_from(
            "<4x2H2H3I3H2HII", cd, p + 4
        )
        name = cd[p + 46 : p + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
        extra = cd[p + 46 + nlen : p + 46 + nlen + elen]
        q = 0
        while q + 4 <= len(extra):
            hid, hlen = struct.unpack_from("<HH", extra, q)
            if hid == 1:
                body = extra[q + 4 : q + 4 + hlen]
                k = 0
                if usz == 0xFFFFFFFF:
                    usz = struct.unpack_from("<Q", body, k)[0]
                    k += 8
                if csz == 0xFFFFFFFF:
                    csz = struct.unpack_from("<Q", body, k)[0]
                    k += 8
                if lho == 0xFFFFFFFF:
                    lho = struct.unpack_from("<Q", body, k)[0]
                    k += 8
            q += 4 + hlen
        entries[name] = {"flags": flags, "method": method, "crc32": f"{crc:08x}", "csz": csz, "usz": usz, "lho": lho}
        p += 46 + nlen + elen + clen
    return entries


def load_cd_from_tail(tail: bytes, tail_start: int) -> dict[str, dict]:
    cd_rel = CD_OFFSET - tail_start
    if cd_rel < 0 or cd_rel + CD_SIZE > len(tail):
        fail("archive tail does not cover the central directory")
    cd = tail[cd_rel : cd_rel + CD_SIZE]
    digest = hashlib.sha256(cd).hexdigest()
    if digest != CD_SHA256:
        fail(f"central directory SHA-256 changed: {digest}")
    loc = tail.rfind(b"PK\x06\x07")
    if loc < 0:
        fail("ZIP64 end-of-central-directory locator missing")
    _sig, _disk, z64_offset, _ndisks = struct.unpack_from("<IIQI", tail, loc)
    rec = z64_offset - tail_start
    fields = struct.unpack_from("<IQHHIIQQQQ", tail, rec)
    if fields[0] != 0x06064B50 or fields[7] != CD_ENTRIES or fields[8] != CD_SIZE or fields[9] != CD_OFFSET:
        fail(f"ZIP64 EOCD mismatch: {fields}")
    entries = parse_central_directory(cd)
    if len(entries) != CD_ENTRIES:
        fail(f"expected {CD_ENTRIES} central-directory entries, found {len(entries)}")
    return entries


def cmd_check_cd(args: argparse.Namespace) -> None:
    status, block = final_response(Path(args.headers).read_text(encoding="iso-8859-1"))
    if status != 206:
        fail(f"tail request status {status}")
    start, end, total = content_range(block)
    if total != ARCHIVE_BYTES or end != ARCHIVE_BYTES - 1:
        fail(f"archive size changed: Content-Range {start}-{end}/{total}")
    tail = Path(args.tail).read_bytes()
    if len(tail) != end - start + 1:
        fail("tail payload length does not match Content-Range")
    entries = load_cd_from_tail(tail, start)
    offsets = sorted(e["lho"] for e in entries.values())
    next_offset = {o: (offsets[i + 1] if i + 1 < len(offsets) else CD_OFFSET) for i, o in enumerate(offsets)}
    xtf_members = sorted(n for n in entries if n.lower().endswith(".xtf"))
    if len(xtf_members) != 143:
        fail(f"expected 143 .xtf members, found {len(xtf_members)}")
    for row in read_sources(Path(args.sources)):
        entry = entries.get(row["member"])
        if entry is None:
            fail(f"member {row['member']} missing from central directory")
        if entry["method"] != 8 or entry["flags"] & 0x0009:
            fail(f"{row['member']}: unexpected method/flags {entry['method']}/{entry['flags']}")
        expected = (row["local_header_offset"], row["compressed_bytes"], row["uncompressed_bytes"], row["crc32"])
        actual = (entry["lho"], entry["csz"], entry["usz"], entry["crc32"])
        if expected != actual:
            fail(f"{row['member']}: CD entry {actual} != pinned {expected}")
        if next_offset[entry["lho"]] - 1 != row["range_end"]:
            fail(f"{row['member']}: pinned range end disagrees with the next member offset")
    print(f"central_directory_ok entries={len(entries)} xtf_members={len(xtf_members)} sha256={CD_SHA256}")


def cmd_check_metadata(args: argparse.Namespace) -> None:
    raw = Path(args.path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args.sha256:
        fail(f"FGDC metadata SHA-256 changed: {digest}")
    text = raw.decode("utf-8", errors="replace")
    flat = re.sub(r"\s+", " ", text)
    missing = [phrase for phrase in METADATA_PHRASES if phrase not in flat]
    if missing:
        fail(f"FGDC metadata lacks expected phrases: {missing}")
    print(f"metadata_ok bytes={len(raw)} sha256={digest} license=public-domain")


def cmd_extract(args: argparse.Namespace) -> None:
    payload = Path(args.range_file).read_bytes()
    want = args.range_end - args.lho + 1
    if len(payload) != want:
        fail(f"range payload is {len(payload)} bytes, expected {want}")
    if payload[:4] != b"PK\x03\x04":
        fail("range does not start with a ZIP local file header")
    (_ver, flags, method, _t, _d, crc, csz, usz, nlen, elen) = struct.unpack_from("<5H3I2H", payload, 4)
    name = payload[30 : 30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    extra = payload[30 + nlen : 30 + nlen + elen]
    q = 0
    while q + 4 <= len(extra):
        hid, hlen = struct.unpack_from("<HH", extra, q)
        if hid == 1:
            body = extra[q + 4 : q + 4 + hlen]
            k = 0
            if usz == 0xFFFFFFFF:
                usz = struct.unpack_from("<Q", body, k)[0]
                k += 8
            if csz == 0xFFFFFFFF:
                csz = struct.unpack_from("<Q", body, k)[0]
        q += 4 + hlen
    data_offset = 30 + nlen + elen
    expected_crc = int(args.crc32, 16)
    if name != args.member or method != 8 or flags & 0x0009:
        fail(f"local header mismatch: name={name!r} method={method} flags={flags}")
    if (crc, csz, usz) != (expected_crc, args.csz, args.usz):
        fail(f"local header sizes/CRC mismatch: crc={crc:08x} csz={csz} usz={usz}")
    if data_offset + csz != len(payload):
        fail("compressed data does not end exactly at the next member's local header")
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    actual_crc = 0
    written = 0
    view = memoryview(payload)[data_offset:]
    with open(args.out, "wb") as out:
        for offset in range(0, len(view), 4 << 20):
            block = inflater.decompress(view[offset : offset + (4 << 20)])
            out.write(block)
            actual_crc = zlib.crc32(block, actual_crc)
            written += len(block)
        block = inflater.flush()
        out.write(block)
        actual_crc = zlib.crc32(block, actual_crc)
        written += len(block)
    if not inflater.eof or inflater.unused_data:
        fail("DEFLATE stream did not end at the member boundary")
    if written != args.usz or (actual_crc & 0xFFFFFFFF) != expected_crc:
        fail(f"inflated member mismatch: bytes={written} crc32={actual_crc & 0xFFFFFFFF:08x}")
    print(f"extract_ok member={name} bytes={written} crc32={actual_crc & 0xFFFFFFFF:08x}")


# ---------------------------------------------------------------- XTF parsing


def parse_file_header(buf) -> dict:
    if len(buf) < XTF_FILE_HEADER_BYTES:
        fail("file shorter than the XTF file header")
    header = {
        "file_format": buf[0],
        "recording_program": bytes(buf[2:10]).split(b"\0")[0].decode("latin-1"),
        "recording_version": bytes(buf[10:18]).split(b"\0")[0].decode("latin-1"),
        "sonar_name": bytes(buf[18:34]).split(b"\0")[0].decode("latin-1"),
        "note": bytes(buf[36:100]).split(b"\0")[0].decode("latin-1"),
    }
    nav_units, n_sonar, n_bathy = struct.unpack_from("<3H", buf, 164)
    header.update({"nav_units": nav_units, "sonar_channels": n_sonar, "bathymetry_channels": n_bathy})
    chans = []
    for index in range(max(n_sonar, 0)):
        o = 256 + 128 * index
        ctype, sub, corr, unipolar, bps = struct.unpack_from("<BBHHH", buf, o)
        volt_scale, freq = struct.unpack_from("<ff", buf, o + 28)
        chans.append(
            {"type": ctype, "sub_channel": sub, "correction_flags": corr, "unipolar": unipolar, "bytes_per_sample": bps, "volt_scale": volt_scale, "frequency_khz": freq}
        )
    header["chaninfo"] = chans
    return header


def check_file_header(header: dict, label: str) -> None:
    problems = []
    if header["file_format"] != 0x7B:
        problems.append(f"FileFormat {header['file_format']}")
    if header["sonar_channels"] != CANON_CHANNELS or header["bathymetry_channels"] != 0:
        problems.append(f"channels {header['sonar_channels']}/{header['bathymetry_channels']}")
    types = [c["type"] for c in header["chaninfo"]]
    if types != [1, 2]:
        problems.append(f"TypeOfChannel {types}")
    if any(c["bytes_per_sample"] != 2 for c in header["chaninfo"]):
        problems.append("BytesPerSample != 2")
    if header["sonar_name"] != "Klein 3000" or header["recording_program"] != "KleinXlt":
        problems.append(f"sonar/program {header['sonar_name']!r}/{header['recording_program']!r}")
    if problems:
        fail(f"{label}: XTF file header not in the canonical configuration: {problems}")


def cmd_check_xtf(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if not path.is_file() or path.stat().st_size != args.usz:
        fail(f"{path}: missing or wrong size")
    crc = 0
    with path.open("rb") as handle:
        head = handle.read(XTF_FILE_HEADER_BYTES)
        crc = zlib.crc32(head, crc)
        first = handle.read(16)
        crc = zlib.crc32(first, crc)
        while block := handle.read(8 << 20):
            crc = zlib.crc32(block, crc)
    if f"{crc & 0xFFFFFFFF:08x}" != args.crc32:
        fail(f"{path}: CRC32 {crc & 0xFFFFFFFF:08x} != {args.crc32}")
    check_file_header(parse_file_header(head), path.name)
    if struct.unpack_from("<H", first, 0)[0] != XTF_MAGIC:
        fail(f"{path.name}: first packet lacks 0xFACE")
    print(f"xtf_ok member={path.name} bytes={args.usz} crc32={args.crc32}")


def walk_xtf(buf, size: int, label: str):
    """Yield (offset, header_type, chans_to_follow, record_bytes) for every packet."""
    p = XTF_FILE_HEADER_BYTES
    while p < size:
        if p + 14 > size:
            fail(f"{label}: truncated packet header at {p}")
        magic, htype, _sub, nchans, _r1, _r2, nbytes = struct.unpack_from("<HBBHHHI", buf, p)
        if magic != XTF_MAGIC:
            fail(f"{label}: missing 0xFACE at offset {p}")
        if nbytes < 14 or p + nbytes > size:
            fail(f"{label}: bad NumBytesThisRecord {nbytes} at offset {p}")
        yield p, htype, nchans, nbytes
        p += nbytes


def ping_time(buf, p: int) -> str:
    year, month, day, hour, minute, second, hsec = struct.unpack_from("<H6B", buf, p + 14)
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{hsec:02d}"


def u16_stats(raw: bytes | bytearray) -> dict:
    values = array("H")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = set(values)
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "distinct": len(distinct),
        "zeros": values.count(0),
        "_set": distinct,
    }


def build_one(path: Path, row: dict, out_path: Path) -> dict:
    label = row["member"]
    size = path.stat().st_size
    if size != row["uncompressed_bytes"]:
        fail(f"{label}: size {size} != pinned {row['uncompressed_bytes']}")
    type_counts: dict[str, int] = {}
    pings = 0
    first_ping = last_ping = None
    first_time = last_time = None
    ping_number_steps_not_one = 0
    seconds_per_ping: set[float] = set()
    port = bytearray()
    stbd = bytearray()
    digest = hashlib.sha256()
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as buf:
        header = parse_file_header(buf)
        check_file_header(header, label)
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        with tmp.open("wb") as out:
            for p, htype, nchans, nbytes in walk_xtf(buf, size, label):
                type_counts[str(htype)] = type_counts.get(str(htype), 0) + 1
                if htype != SONAR_HEADER_TYPE:
                    if htype == KLEIN_AUX_HEADER_TYPE and nbytes != KLEIN_AUX_RECORD_BYTES:
                        fail(f"{label}: Klein type-108 record of {nbytes} bytes at {p}")
                    continue
                if nchans != CANON_CHANNELS:
                    fail(f"{label}: ping at {p} has {nchans} channels")
                q = p + PING_HEADER_BYTES
                slices = []
                for expect_channel in range(CANON_CHANNELS):
                    channel, _ds, slant, _ground, _delay, _dur, spp = struct.unpack_from("<HHfffff", buf, q)
                    freq = struct.unpack_from("<H", buf, q + 26)[0]
                    nsamp = struct.unpack_from("<I", buf, q + 42)[0]
                    if channel != expect_channel:
                        fail(f"{label}: ping at {p} channel order {channel} != {expect_channel}")
                    if nsamp != CANON_SAMPLES or freq != CANON_FREQ_FIELD or slant != CANON_SLANT_RANGE_M:
                        fail(f"{label}: ping at {p} channel {channel} config ns={nsamp} freq={freq} slant={slant}")
                    seconds_per_ping.add(round(spp, 6))
                    start = q + CHAN_HEADER_BYTES
                    slices.append((start, start + 2 * nsamp))
                    q = start + 2 * nsamp
                used = q - p
                padded = (used + 63) // 64 * 64
                if nbytes != padded:
                    fail(f"{label}: ping at {p} NumBytesThisRecord {nbytes} != {padded}")
                port_bytes = buf[slices[0][0] : slices[0][1]]
                stbd_bytes = buf[slices[1][0] : slices[1][1]]
                out.write(port_bytes)
                out.write(stbd_bytes)
                digest.update(port_bytes)
                digest.update(stbd_bytes)
                port += port_bytes
                stbd += stbd_bytes
                number = struct.unpack_from("<I", buf, p + 28)[0]
                if last_ping is not None and number != last_ping + 1:
                    ping_number_steps_not_one += 1
                if first_ping is None:
                    first_ping = number
                    first_time = ping_time(buf, p)
                last_ping = number
                last_time = ping_time(buf, p)
                pings += 1
    if pings != row["ping_count"]:
        fail(f"{label}: parsed {pings} sonar pings, pinned {row['ping_count']}")
    port_stats = u16_stats(port)
    stbd_stats = u16_stats(stbd)
    for name, stats in (("port", port_stats), ("starboard", stbd_stats)):
        if stats["max"] == 0 or stats["distinct"] < 64 or stats["zeros"] * 2 > stats["count"]:
            fail(f"{label}: degenerate {name} channel {stats}")
    tmp.replace(out_path)
    value_count = pings * CANON_CHANNELS * CANON_SAMPLES
    combined_distinct = len(port_stats.pop("_set") | stbd_stats.pop("_set"))
    return {
        "member": label,
        "pings": pings,
        "value_count": value_count,
        "sha256": digest.hexdigest(),
        "type_counts": type_counts,
        "first_ping_number": first_ping,
        "last_ping_number": last_ping,
        "ping_number_steps_not_one": ping_number_steps_not_one,
        "first_ping_time": first_time,
        "last_ping_time": last_time,
        "seconds_per_ping": sorted(seconds_per_ping),
        "port": port_stats,
        "starboard": stbd_stats,
        "minimum": min(port_stats["min"], stbd_stats["min"]),
        "maximum": max(port_stats["max"], stbd_stats["max"]),
        "distinct_values": combined_distinct,
        "zero_fraction": round((port_stats["zeros"] + stbd_stats["zeros"]) / value_count, 6),
        "file_header": header,
    }


def resolve_data_dir(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def cmd_build(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).resolve()
    data_root = resolve_data_dir(repo_root, args.data_dir)
    rows = read_sources(Path(args.sources))
    download_dir = data_root / "downloads" / DATASET_ID / "xtf"
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for directory in (sample_dir, index_dir, filtered_dir):
        directory.mkdir(parents=True, exist_ok=True)
    expected_names = set()
    index_rows = []
    stats_rows = []
    for row in rows:
        source = download_dir / row["member"]
        if not source.is_file():
            fail(f"missing local member {source}; run download.sh first")
        stem = row["member"][: -len(".xtf")]
        out_name = f"{stem}_ping_port_stbd_u16le.bin"
        expected_names.add(out_name)
        out_path = sample_dir / out_name
        info = build_one(source, row, out_path)
        size = out_path.stat().st_size
        if size != info["value_count"] * 2:
            fail(f"{out_name}: size {size} != value_count*2")
        stats_rows.append(info)
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": out_path.relative_to(data_root).as_posix(),
                "numeric_kind": "uint",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": size,
                "value_count": info["value_count"],
                "role": "primary",
                "natural_record_kind": "complete_klein_sonarpro_xtf_recording_file",
                "sample_format": "raw little-endian uint16 side-scan backscatter, ping-major [ping][port, starboard][stored sample index: port far-to-nadir, starboard nadir-to-far]",
                "sample_rank": 3,
                "sample_shape": [info["pings"], CANON_CHANNELS, CANON_SAMPLES],
                "sample_axes": ["ping", "channel_port_then_starboard", "stored_sample_index_port_far_to_nadir_stbd_nadir_to_far"],
                "source_member": row["member"],
                "source_member_crc32": row["crc32"],
                "survey_date": row["survey_date"],
                "ping_count": info["pings"],
                "first_ping_number": info["first_ping_number"],
                "last_ping_number": info["last_ping_number"],
                "first_ping_time": info["first_ping_time"],
                "last_ping_time": info["last_ping_time"],
                "slant_range_m": CANON_SLANT_RANGE_M,
                "chan_frequency_field": CANON_FREQ_FIELD,
                "samples_per_channel": CANON_SAMPLES,
                "minimum": info["minimum"],
                "maximum": info["maximum"],
                "distinct_values": info["distinct_values"],
                "zero_fraction": info["zero_fraction"],
                "sha256": info["sha256"],
            }
        )
        print(
            f"sample {out_name} pings={info['pings']} values={info['value_count']} "
            f"min={info['minimum']} max={info['maximum']} distinct={info['distinct_values']} "
            f"zero_frac={info['zero_fraction']} types={info['type_counts']}",
            flush=True,
        )
    for stale in sample_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()
            print(f"removed stale sample {stale.name}")
    index_path = index_dir / "samples.jsonl"
    tmp = index_path.with_suffix(".jsonl.part")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows), encoding="utf-8")
    tmp.replace(index_path)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "pings": sum(r["ping_count"] for r in index_rows),
        "values": sum(r["value_count"] for r in index_rows),
        "bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "files": stats_rows,
    }
    (filtered_dir / "build_stats.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build_summary samples={summary['samples']} pings={summary['pings']} values={summary['values']} bytes={summary['bytes']}")


# ---------------------------------------------------------------- discovery


def cmd_list_band(args: argparse.Namespace) -> None:
    status, block = final_response(Path(args.headers).read_text(encoding="iso-8859-1"))
    start, _end, total = content_range(block)
    if status != 206 or total != ARCHIVE_BYTES:
        fail("unexpected tail response")
    entries = load_cd_from_tail(Path(args.tail).read_bytes(), start)
    offsets = sorted(e["lho"] for e in entries.values())
    next_offset = {o: (offsets[i + 1] if i + 1 < len(offsets) else CD_OFFSET) for i, o in enumerate(offsets)}
    for name, entry in sorted(entries.items(), key=lambda kv: kv[1]["lho"]):
        if not name.lower().endswith(".xtf"):
            continue
        body = entry["usz"] - XTF_FILE_HEADER_BYTES
        if body % PING_PAIR_BYTES:
            print(f"# skip {name}: size not a whole number of ping pairs", file=sys.stderr)
            continue
        pings = body // PING_PAIR_BYTES
        if not BAND_MIN_PINGS <= pings < BAND_MAX_PINGS_EXCLUSIVE:
            continue
        print("\t".join(str(x) for x in (name, entry["lho"], next_offset[entry["lho"]] - 1, entry["csz"], entry["usz"], entry["crc32"], pings)))


def cmd_discover(args: argparse.Namespace) -> None:
    out_lines = ["\t".join(SOURCE_COLUMNS)]
    for line in Path(args.band).read_text(encoding="utf-8").splitlines():
        name, lho, end, csz, usz, crc, pings = line.split("\t")
        raw = (Path(args.prefix_dir) / name).read_bytes()
        nlen, elen = struct.unpack_from("<HH", raw, 26)
        buf = zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw[30 + nlen + elen :])
        header = parse_file_header(buf)
        check_file_header(header, name)
        configs = set()
        usable = XTF_FILE_HEADER_BYTES + (len(buf) - XTF_FILE_HEADER_BYTES) // PING_PAIR_BYTES * PING_PAIR_BYTES
        for p, htype, nchans, nbytes in walk_xtf(buf, usable, name):
            if htype != SONAR_HEADER_TYPE:
                continue
            q = p + PING_HEADER_BYTES
            for _ in range(nchans):
                slant = struct.unpack_from("<f", buf, q + 4)[0]
                freq = struct.unpack_from("<H", buf, q + 26)[0]
                nsamp = struct.unpack_from("<I", buf, q + 42)[0]
                configs.add((nchans, nsamp, freq, slant))
                q += CHAN_HEADER_BYTES + 2 * nsamp
        canon = {(CANON_CHANNELS, CANON_SAMPLES, CANON_FREQ_FIELD, CANON_SLANT_RANGE_M)}
        if configs != canon:
            print(f"# exclude {name}: prefix ping configs {sorted(configs)}", file=sys.stderr)
            continue
        date = "20" + name.rsplit("_", 1)[1][:6]
        out_lines.append("\t".join([name, lho, end, csz, usz, crc, pings, date]))
    Path(args.out).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"discover wrote {len(out_lines) - 1} members to {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-metadata")
    p.add_argument("path")
    p.add_argument("sha256")
    p.set_defaults(func=cmd_check_metadata)
    p = sub.add_parser("check-cd")
    p.add_argument("tail")
    p.add_argument("headers")
    p.add_argument("sources")
    p.set_defaults(func=cmd_check_cd)
    p = sub.add_parser("check-range")
    p.add_argument("headers")
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p.add_argument("chunk_bytes", type=int)
    p.set_defaults(func=cmd_check_range)
    p = sub.add_parser("extract")
    p.add_argument("range_file")
    p.add_argument("out")
    p.add_argument("member")
    p.add_argument("lho", type=int)
    p.add_argument("range_end", type=int)
    p.add_argument("csz", type=int)
    p.add_argument("usz", type=int)
    p.add_argument("crc32")
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("check-xtf")
    p.add_argument("path")
    p.add_argument("usz", type=int)
    p.add_argument("crc32")
    p.set_defaults(func=cmd_check_xtf)
    p = sub.add_parser("list-band")
    p.add_argument("tail")
    p.add_argument("headers")
    p.set_defaults(func=cmd_list_band)
    p = sub.add_parser("discover")
    p.add_argument("band")
    p.add_argument("prefix_dir")
    p.add_argument("out")
    p.set_defaults(func=cmd_discover)
    p = sub.add_parser("build")
    p.add_argument("--repo-root", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--sources", required=True)
    p.set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
