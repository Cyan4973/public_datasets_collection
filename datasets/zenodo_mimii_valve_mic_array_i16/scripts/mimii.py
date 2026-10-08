#!/usr/bin/env python3
"""MIMII valve recordings (6 dB SNR product), 8-channel microphone array, PCM16.

Source: Purohit et al. (Hitachi, Ltd.), "MIMII Dataset: Sound Dataset for
Malfunctioning Industrial Machine Investigation and Inspection", Zenodo
record 3384388, version "public 1.0", CC BY-SA 4.0. The valve recordings
with factory noise mixed in at 6 dB SNR are the 4,170 deflate-compressed
10-second WAV members of one 6.9 GB ZIP64 archive, 6_dB_valve.zip. This
recipe collects a pinned, evenly spaced subset of whole clips (30 normal
and 10 abnormal per product model id_00/02/04/06) by HTTP range requests,
without fetching the archive whole.

Subcommands (all network I/O is done by curl in the shell scripts; this
module only parses local files):

  discover        derive members.tsv from a fetched archive tail (documents
                  how the pins were made; see discover.sh)
  check-record    validate the Zenodo record JSON (license, file identity)
  check-metadata  validate the archive tail (EOCD, ZIP64 EOCD, central
                  directory sha256) and re-derive the member selection,
                  which must equal members.tsv
  plan-members    list member byte spans still missing
  check-members   validate fetched .part spans and promote the good ones
  check-downloads require every pinned member to be present and valid
  build           decode every member and emit one int16 sample each
  verify          independent re-decode (zipfile + wave) and full checks
  selftest        synthetic-input test of both decoders and the ZIP parsers
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import io
import json
import os
import re
import struct
import sys
import wave
import zipfile
import zlib
from pathlib import Path

DATASET_ID = "zenodo_mimii_valve_mic_array_i16"
SERIES_ID = "mimii_valve_6db_array_pcm_i16"
RECIPE_DIR = Path(__file__).resolve().parents[1]
MEMBERS_TSV = RECIPE_DIR / "members.tsv"

RECORD = {
    "id": 3384388,
    "doi": "10.5281/zenodo.3384388",
    "version": "public 1.0",
    "license": "cc-by-sa-4.0",
    "key": "6_dB_valve.zip",
    "size": 6915951837,
    "checksum": "md5:fe5fb7c337cd701b1d31dc641e621892",
}
LICENSE_SENTENCE = "Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)"
ARCHIVE = {
    "entries": 4183,
    "cd_offset": 6915459463,
    "cd_size": 492276,
    # sha256 of bytes [cd_offset, size): central directory, ZIP64 EOCD record,
    # ZIP64 EOCD locator and EOCD (492,374 bytes).
    "tail_sha256": "209786dc47b446d51160124a79a9e23a8600142e93fb79512ab08730cb9cd0ae",
}
TAIL_BYTES = RECORD["size"] - ARCHIVE["cd_offset"]

# Selection rule (see README): within each (product model, condition) group,
# ordered by member name, take PICKS[condition] evenly spaced members at
# ranks floor((2k+1) N / (2K)), k = 0..K-1.
MODELS = ("id_00", "id_02", "id_04", "id_06")
CONDITIONS = ("abnormal", "normal")
PICKS = {"abnormal": 10, "normal": 30}
GROUP_SIZES = {
    ("id_00", "abnormal"): 119, ("id_00", "normal"): 991,
    ("id_02", "abnormal"): 120, ("id_02", "normal"): 708,
    ("id_04", "abnormal"): 120, ("id_04", "normal"): 1000,
    ("id_06", "abnormal"): 120, ("id_06", "normal"): 992,
}
WAV_MEMBERS = 4170
MEMBER_RE = re.compile(r"^valve/(id_\d\d)/(normal|abnormal)/(\d{8})\.wav$")

# WAV layout: WAVE_FORMAT_EXTENSIBLE, 8 channels, 16 kHz, 16-bit PCM,
# 160,000 frames (10 s) -> 2,560,000 data bytes in a 2,560,080-byte file.
WAVE_FORMAT_EXTENSIBLE = 0xFFFE
CHANNELS = 8
SAMPLE_RATE = 16000
BITS = 16
FRAMES = 160000
DATA_BYTES = FRAMES * CHANNELS * BITS // 8
WAV_BYTES = 2560080
EXPECTED_FMT = (WAVE_FORMAT_EXTENSIBLE, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * CHANNELS * 2, CHANNELS * 2, BITS, 22, BITS)
KSDATAFORMAT_SUBTYPE_PCM = bytes.fromhex("0100000000001000800000aa00389b71")

MIN_DISTINCT_CODES = 64
MAX_EXCLUDED_FRACTION = 0.01
FULL_SCALE = (-32768, 32767)

MEMBER_COLUMNS = [
    "sample_id", "model_id", "condition", "member", "cd_index", "group_size", "group_rank",
    "local_header_offset", "span_bytes", "compressed_size", "uncompressed_size", "crc32",
]


class RecipeError(Exception):
    pass


def fail(message: str) -> None:
    raise RecipeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# pinned table


def read_members(path: Path = MEMBERS_TSV) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames != MEMBER_COLUMNS:
            fail(f"{path.name}: unexpected columns {reader.fieldnames}")
        rows = list(reader)
    for row in rows:
        for key in ("cd_index", "group_size", "group_rank", "local_header_offset", "span_bytes",
                    "compressed_size", "uncompressed_size", "crc32"):
            row[key] = int(row[key])
    return rows


def write_members(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MEMBER_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in MEMBER_COLUMNS})


def normalize(rows: list[dict]) -> list[tuple]:
    return [tuple(str(row[key]) for key in MEMBER_COLUMNS) for row in rows]


def member_relpath(row: dict) -> str:
    return f"members/{row['sample_id']}.zipentry"


def sample_relpath(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['sample_id']}.bin"


# --------------------------------------------------------------------------
# ZIP structures


def parse_eocd(tail: bytes, archive_size: int) -> dict:
    """Parse the end of central directory (with ZIP64 when flagged) from the
    last bytes of an archive. Returns entries, cd_offset, cd_size, zip64."""
    base = archive_size - len(tail)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or pos + 22 > len(tail):
        fail("EOCD signature not found in archive tail")
    _, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = struct.unpack("<IHHHHIIH", tail[pos:pos + 22])
    if pos + 22 + comment_len != len(tail):
        fail("EOCD comment length does not reach the end of the archive")
    if disk != 0 or cd_disk != 0 or n_disk != n_total:
        fail("multi-disk archives are not supported")
    zip64 = False
    cd_end = base + pos
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF or n_total == 0xFFFF:
        loc = pos - 20
        if loc < 0 or tail[loc:loc + 4] != b"PK\x06\x07":
            fail("ZIP64 EOCD locator missing")
        _, loc_disk, eocd64_offset, total_disks = struct.unpack("<IIQI", tail[loc:loc + 20])
        if loc_disk != 0 or total_disks != 1:
            fail("multi-disk ZIP64 archives are not supported")
        rel = eocd64_offset - base
        if rel < 0 or rel + 56 > loc:
            fail("ZIP64 EOCD record outside the fetched tail")
        rec = struct.unpack("<IQHHIIQQQQ", tail[rel:rel + 56])
        if rec[0] != 0x06064B50:
            fail("ZIP64 EOCD record signature mismatch")
        if rec[1] + 12 != loc - rel:
            fail("ZIP64 EOCD record size does not abut the locator")
        if rec[4] != 0 or rec[5] != 0 or rec[6] != rec[7]:
            fail("ZIP64 multi-disk fields")
        n_total, cd_size, cd_offset = rec[7], rec[8], rec[9]
        zip64 = True
        cd_end = eocd64_offset
    if cd_offset + cd_size != cd_end:
        fail(f"central directory [{cd_offset}, +{cd_size}) does not end at the EOCD ({cd_end})")
    return {"entries": n_total, "cd_offset": cd_offset, "cd_size": cd_size, "zip64": zip64}


def parse_zip64_extra(extra: bytes, usize: int, csize: int, offset: int | None) -> tuple[int, int, int | None]:
    """Walk an extra field; widen whichever of usize/csize/offset carry the
    0xFFFFFFFF sentinel from the ZIP64 (0x0001) block, in spec order. Pass
    offset=None for local headers, which have no offset field."""
    pos = 0
    while pos + 4 <= len(extra):
        header_id, size = struct.unpack("<HH", extra[pos:pos + 4])
        body = extra[pos + 4:pos + 4 + size]
        if len(body) != size:
            fail("truncated extra field")
        if header_id == 0x0001:
            k = 0
            if usize == 0xFFFFFFFF:
                if k + 8 > len(body):
                    fail("ZIP64 extra field too short (usize)")
                (usize,) = struct.unpack("<Q", body[k:k + 8])
                k += 8
            if csize == 0xFFFFFFFF:
                if k + 8 > len(body):
                    fail("ZIP64 extra field too short (csize)")
                (csize,) = struct.unpack("<Q", body[k:k + 8])
                k += 8
            if offset is not None and offset == 0xFFFFFFFF:
                if k + 8 > len(body):
                    fail("ZIP64 extra field too short (offset)")
                (offset,) = struct.unpack("<Q", body[k:k + 8])
                k += 8
        pos += 4 + size
    if pos != len(extra):
        fail("malformed extra field")
    if 0xFFFFFFFF in (usize, csize) or offset == 0xFFFFFFFF:
        fail("ZIP64 sentinel without matching ZIP64 extra field")
    return usize, csize, offset


def parse_central_directory(data: bytes, expected_entries: int, cd_offset: int) -> list[dict]:
    """Parse every central-directory entry; attach each entry's span
    [own local header offset, next entry's offset or cd_offset)."""
    entries = []
    pos = 0
    while pos < len(data):
        if pos + 46 > len(data):
            fail("truncated central directory entry")
        (sig, _made_by, _needed, flags, method, mtime, mdate, crc, csize, usize, name_len, extra_len,
         comment_len, disk, _internal, _external, offset) = struct.unpack("<IHHHHHHIIIHHHHHII", data[pos:pos + 46])
        if sig != 0x02014B50:
            fail(f"central directory signature mismatch at entry {len(entries)}")
        name_raw = data[pos + 46:pos + 46 + name_len]
        extra = data[pos + 46 + name_len:pos + 46 + name_len + extra_len]
        if len(name_raw) != name_len or len(extra) != extra_len:
            fail("truncated central directory name/extra")
        usize, csize, offset = parse_zip64_extra(extra, usize, csize, offset)
        if disk not in (0, 0xFFFF):
            fail("multi-disk member")
        entries.append({
            "cd_index": len(entries),
            "name": name_raw.decode("utf-8" if flags & 0x0800 else "cp437"),
            "flags": flags,
            "method": method,
            "mtime": mtime,
            "mdate": mdate,
            "crc32": crc,
            "compressed_size": csize,
            "uncompressed_size": usize,
            "local_header_offset": offset,
        })
        pos += 46 + name_len + extra_len + comment_len
    if len(entries) != expected_entries:
        fail(f"central directory has {len(entries)} entries, expected {expected_entries}")
    for index, entry in enumerate(entries):
        end = entries[index + 1]["local_header_offset"] if index + 1 < len(entries) else cd_offset
        if end <= entry["local_header_offset"]:
            fail("central-directory offsets are not strictly increasing")
        entry["span_bytes"] = end - entry["local_header_offset"]
    return entries


def load_tail(path: Path) -> list[dict]:
    """Archive tail [cd_offset, size): checksum, EOCD fields, central directory."""
    tail = path.read_bytes()
    if len(tail) != TAIL_BYTES:
        fail(f"{path.name}: {len(tail)} bytes, expected {TAIL_BYTES}")
    if sha256_bytes(tail) != ARCHIVE["tail_sha256"]:
        fail(f"{path.name}: sha256 mismatch (archive changed upstream or transfer corrupted)")
    return parse_tail_bytes(tail)


def parse_tail_bytes(tail: bytes) -> list[dict]:
    eocd = parse_eocd(tail, RECORD["size"])
    got = (eocd["entries"], eocd["cd_offset"], eocd["cd_size"], eocd["zip64"])
    want = (ARCHIVE["entries"], ARCHIVE["cd_offset"], ARCHIVE["cd_size"], True)
    if got != want:
        fail(f"EOCD (entries, cd_offset, cd_size, zip64) {got} != pinned {want}")
    base = RECORD["size"] - len(tail)
    cd = tail[eocd["cd_offset"] - base:eocd["cd_offset"] - base + eocd["cd_size"]]
    return parse_central_directory(cd, eocd["entries"], eocd["cd_offset"])


def parse_local_header(span: bytes, cd: dict) -> int:
    """Validate the local file header of one fetched member span against its
    central-directory entry, using the local header's own name and extra
    lengths (local and central extras differ in this archive). Returns the
    offset of the compressed data."""
    if len(span) < 30:
        fail("member span shorter than a local header")
    (sig, _needed, flags, method, _mtime, _mdate, crc, csize, usize, name_len, extra_len) = struct.unpack("<IHHHHHIIIHH", span[:30])
    if sig != 0x04034B50:
        fail("local header signature mismatch")
    name_raw = span[30:30 + name_len]
    name = name_raw.decode("utf-8" if flags & 0x0800 else "cp437")
    if name != cd["name"]:
        fail(f"local header name {name!r} != central directory name {cd['name']!r}")
    if flags != cd["flags"] or method != cd["method"]:
        fail("local header flags/method disagree with the central directory")
    if flags & 0x0001:
        fail("encrypted member")
    if flags & 0x0008:
        fail("member uses a data descriptor; spans would not be exact")
    extra = span[30 + name_len:30 + name_len + extra_len]
    if len(extra) != extra_len:
        fail("truncated local extra field")
    usize, csize, _ = parse_zip64_extra(extra, usize, csize, None)
    if (crc, csize, usize) != (cd["crc32"], cd["compressed_size"], cd["uncompressed_size"]):
        fail("local header crc/sizes disagree with the central directory")
    data_offset = 30 + name_len + extra_len
    if data_offset + csize != len(span):
        fail(f"span length {len(span)} != local header {data_offset} + compressed {csize}")
    return data_offset


def inflate(data: bytes, uncompressed_size: int) -> bytes:
    """Raw deflate (ZIP method 8): the stream must end exactly at the end of
    the compressed span and produce exactly the declared size."""
    decoder = zlib.decompressobj(-15)
    out = decoder.decompress(data, uncompressed_size + 1)
    if len(out) > uncompressed_size or decoder.unconsumed_tail:
        fail("deflate stream produces more than the declared uncompressed size")
    out += decoder.flush()
    if not decoder.eof:
        fail("deflate stream truncated (no final block)")
    if decoder.unused_data:
        fail("trailing bytes after the deflate stream")
    if len(out) != uncompressed_size:
        fail(f"deflate produced {len(out)} bytes, expected {uncompressed_size}")
    return out


def parse_wav(wav: bytes) -> tuple[bytes, list[str], int]:
    """Walk the RIFF chunk list; require the exact WAVE_FORMAT_EXTENSIBLE
    PCM format and a data chunk of exactly DATA_BYTES. Returns (data chunk,
    chunk ids, channel mask)."""
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        fail("not a RIFF/WAVE file")
    (riff_size,) = struct.unpack("<I", wav[4:8])
    if riff_size + 8 != len(wav):
        fail(f"RIFF size {riff_size} + 8 != file size {len(wav)}")
    pos = 12
    fmt = None
    guid = None
    mask = None
    data = None
    fact_frames = None
    chunk_ids = []
    while pos < len(wav):
        if pos + 8 > len(wav):
            fail("truncated RIFF chunk header")
        cid = wav[pos:pos + 4]
        (size,) = struct.unpack("<I", wav[pos + 4:pos + 8])
        body = wav[pos + 8:pos + 8 + size]
        if len(body) != size:
            fail(f"truncated RIFF chunk {cid!r}")
        chunk_ids.append(cid.decode("latin-1"))
        if cid == b"fmt ":
            if fmt is not None:
                fail("duplicate fmt chunk")
            if size != 40:
                fail(f"fmt chunk is {size} bytes; WAVE_FORMAT_EXTENSIBLE needs 40")
            (tag, channels, rate, byte_rate, block_align, bits, cb_size, valid_bits, mask) = struct.unpack("<HHIIHHHHI", body[:24])
            fmt = (tag, channels, rate, byte_rate, block_align, bits, cb_size, valid_bits)
            guid = body[24:40]
        elif cid == b"fact":
            if size < 4:
                fail("short fact chunk")
            (fact_frames,) = struct.unpack("<I", body[:4])
        elif cid == b"data":
            if data is not None:
                fail("duplicate data chunk")
            data = body
        pos += 8 + size + (size & 1)
    if pos != len(wav):
        fail("RIFF chunks overrun the file")
    if fmt is None or data is None:
        fail("missing fmt or data chunk")
    if fmt != EXPECTED_FMT:
        fail(f"fmt {fmt} != expected {EXPECTED_FMT} (EXTENSIBLE, 8 ch, 16 kHz, 16-bit, 16 valid bits)")
    if guid != KSDATAFORMAT_SUBTYPE_PCM:
        fail(f"fmt subformat GUID {guid.hex()} is not KSDATAFORMAT_SUBTYPE_PCM")
    if len(data) != DATA_BYTES:
        fail(f"data chunk is {len(data)} bytes, expected {DATA_BYTES}")
    if fact_frames is not None and fact_frames != FRAMES:
        fail(f"fact chunk declares {fact_frames} frames, expected {FRAMES}")
    return data, chunk_ids, mask


def decode_member_span(span: bytes, cd: dict) -> tuple[bytes, list[str], int]:
    """Build path: local header -> raw deflate -> CRC32 -> RIFF walk -> PCM."""
    if cd["method"] != 8:
        fail(f"member {cd['name']} uses method {cd['method']}, expected 8 (deflate)")
    if cd["uncompressed_size"] != WAV_BYTES:
        fail(f"member {cd['name']} is {cd['uncompressed_size']} bytes, expected {WAV_BYTES}")
    offset = parse_local_header(span, cd)
    wav = inflate(span[offset:], cd["uncompressed_size"])
    if zlib.crc32(wav) & 0xFFFFFFFF != cd["crc32"]:
        fail(f"CRC32 mismatch for {cd['name']}")
    return parse_wav(wav)


def decode_member_independent(span: bytes, cd: dict) -> bytes:
    """Verify path: wrap the fetched local entry in a one-entry central
    directory carrying the real central-directory CRC and sizes, let the
    stdlib zipfile module (its own local-header handling, inflate and CRC
    check) extract it, then read the frames with the stdlib wave module
    (WAVE_FORMAT_EXTENSIBLE support needs Python 3.12+)."""
    (_sig, needed, flags, method, mtime, mdate, _crc, _csize, _usize, name_len, _extra_len) = struct.unpack("<IHHHHHIIIHH", span[:30])
    name = span[30:30 + name_len]
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, needed, needed, flags, method, mtime, mdate, cd["crc32"],
                          cd["compressed_size"], cd["uncompressed_size"], name_len, 0, 0, 0, 0, 0, 0) + name
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(span), 0)
    with zipfile.ZipFile(io.BytesIO(span + central + eocd)) as archive:
        info = archive.getinfo(name.decode("utf-8" if flags & 0x0800 else "cp437"))
        if info.compress_type != zipfile.ZIP_DEFLATED:
            fail("zipfile reports a non-deflate member")
        wav = archive.read(info)
    with wave.open(io.BytesIO(wav)) as reader:
        params = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes(), reader.getcomptype())
        if params != (CHANNELS, 2, SAMPLE_RATE, FRAMES, "NONE"):
            fail(f"wave module reports {params}")
        frames = reader.readframes(FRAMES)
    if len(frames) != DATA_BYTES:
        fail("wave module returned a short frame buffer")
    return frames


# --------------------------------------------------------------------------
# selection


def select_members(entries: list[dict]) -> tuple[list[dict], dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    other = 0
    for entry in entries:
        match = MEMBER_RE.match(entry["name"])
        if not match:
            if not entry["name"].endswith("/") or entry["uncompressed_size"] != 0:
                fail(f"unexpected non-WAV member {entry['name']!r}")
            other += 1
            continue
        model, condition, _number = match.groups()
        if entry["method"] != 8 or entry["uncompressed_size"] != WAV_BYTES:
            fail(f"{entry['name']}: method {entry['method']}, size {entry['uncompressed_size']} (expected deflate, {WAV_BYTES})")
        groups.setdefault((model, condition), []).append(entry)
    sizes = {key: len(value) for key, value in groups.items()}
    if sizes != GROUP_SIZES:
        fail(f"group sizes {sorted(sizes.items())} != pinned {sorted(GROUP_SIZES.items())}")
    if sum(sizes.values()) != WAV_MEMBERS:
        fail("WAV member count changed")
    selected = []
    for model in MODELS:
        for condition in CONDITIONS:
            members = sorted(groups[(model, condition)], key=lambda e: e["name"])
            n = len(members)
            k_total = PICKS[condition]
            for k in range(k_total):
                rank = (2 * k + 1) * n // (2 * k_total)
                entry = members[rank]
                number = MEMBER_RE.match(entry["name"]).group(3)
                selected.append({
                    "sample_id": f"{model}_{condition}_{number}",
                    "model_id": model,
                    "condition": condition,
                    "member": entry["name"],
                    "cd_index": entry["cd_index"],
                    "group_size": n,
                    "group_rank": rank,
                    "local_header_offset": entry["local_header_offset"],
                    "span_bytes": entry["span_bytes"],
                    "compressed_size": entry["compressed_size"],
                    "uncompressed_size": entry["uncompressed_size"],
                    "crc32": entry["crc32"],
                })
    selected.sort(key=lambda row: row["cd_index"])
    if len({row["sample_id"] for row in selected}) != len(selected):
        fail("duplicate sample ids in selection")
    stats = {"wav_members": sum(sizes.values()), "directory_entries": other,
             "group_sizes": {f"{m}/{c}": n for (m, c), n in sorted(sizes.items())}, "selected": len(selected)}
    return selected, stats


def member_cd(row: dict, entries: list[dict]) -> dict:
    cd = entries[row["cd_index"]]
    pinned = (row["member"], row["local_header_offset"], row["span_bytes"], row["compressed_size"],
              row["uncompressed_size"], row["crc32"])
    actual = (cd["name"], cd["local_header_offset"], cd["span_bytes"], cd["compressed_size"],
              cd["uncompressed_size"], cd["crc32"])
    if pinned != actual:
        fail(f"members.tsv row {row['sample_id']} disagrees with the central directory: {pinned} != {actual}")
    return cd


def checked_selection(download_dir: Path) -> tuple[list[dict], list[dict], dict]:
    entries = load_tail(download_dir / "archive_tail.bin")
    selected, stats = select_members(entries)
    pinned = read_members()
    if normalize(selected) != normalize(pinned):
        fail("re-derived member selection differs from the pinned members.tsv")
    return entries, pinned, stats


# --------------------------------------------------------------------------
# download-side checks


def check_record(path: Path) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    meta = record.get("metadata", {})
    if record.get("id") != RECORD["id"] or record.get("doi") != RECORD["doi"]:
        fail(f"record id/doi {record.get('id')}/{record.get('doi')} != pinned")
    if meta.get("version") != RECORD["version"]:
        fail(f"record version {meta.get('version')!r} != {RECORD['version']!r}")
    license_id = (meta.get("license") or {}).get("id")
    if license_id != RECORD["license"]:
        fail(f"record license {license_id!r} != {RECORD['license']!r}")
    if LICENSE_SENTENCE not in meta.get("description", ""):
        fail("record description no longer carries the CC BY-SA 4.0 statement")
    if meta.get("access_right") != "open":
        fail(f"record access_right {meta.get('access_right')!r} != 'open'")
    files = [f for f in record.get("files", []) if f.get("key") == RECORD["key"]]
    if len(files) != 1:
        fail(f"record does not list {RECORD['key']} exactly once")
    if files[0].get("size") != RECORD["size"] or files[0].get("checksum") != RECORD["checksum"]:
        fail(f"{RECORD['key']}: size/checksum {files[0].get('size')}/{files[0].get('checksum')} != pinned")
    return {"license": license_id, "version": meta.get("version"), "size": RECORD["size"]}


def parse_content_range(header_path: Path) -> tuple[int, int, int]:
    found = None
    for line in header_path.read_text(encoding="latin-1").splitlines():
        match = re.match(r"(?i)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", line.strip())
        if match:
            found = tuple(int(group) for group in match.groups())
    if found is None:
        fail(f"{header_path.name}: no Content-Range header (range request not honoured)")
    return found


def check_range_header(header_path: Path, first: int, last: int) -> None:
    got = parse_content_range(header_path)
    if got != (first, last, RECORD["size"]):
        fail(f"Content-Range {got} != requested ({first}, {last}, {RECORD['size']})")


def plan_members(download_dir: Path, plan_path: Path) -> int:
    pending = 0
    with plan_path.open("w", encoding="utf-8") as out:
        for row in read_members():
            final = download_dir / member_relpath(row)
            if final.is_file() and final.stat().st_size == row["span_bytes"]:
                continue
            start = row["local_header_offset"]
            out.write(f"{start} {start + row['span_bytes'] - 1} {member_relpath(row)}\n")
            pending += 1
    return pending


def check_members(download_dir: Path) -> dict:
    entries, pinned, _ = checked_selection(download_dir)
    promoted = rejected = 0
    for row in pinned:
        final = download_dir / member_relpath(row)
        part = final.with_name(final.name + ".part")
        header = final.with_name(final.name + ".hdr")
        if not part.exists():
            header.unlink(missing_ok=True)
            continue
        try:
            if not header.exists():
                fail(f"{header.name} missing")
            start = row["local_header_offset"]
            check_range_header(header, start, start + row["span_bytes"] - 1)
            span = part.read_bytes()
            if len(span) != row["span_bytes"]:
                fail(f"{len(span)} bytes, expected {row['span_bytes']}")
            decode_member_span(span, member_cd(row, entries))
        except (RecipeError, zlib.error) as exc:
            print(f"reject member={row['member']} reason={exc}", flush=True)
            part.unlink(missing_ok=True)
            header.unlink(missing_ok=True)
            rejected += 1
            continue
        os.replace(part, final)
        header.unlink(missing_ok=True)
        promoted += 1
    return {"promoted": promoted, "rejected": rejected}


def check_downloads(download_dir: Path) -> dict:
    entries, pinned, _ = checked_selection(download_dir)
    total = 0
    for row in pinned:
        path = download_dir / member_relpath(row)
        if not path.is_file():
            fail(f"missing member span {member_relpath(row)}")
        span = path.read_bytes()
        try:
            decode_member_span(span, member_cd(row, entries))
        except zlib.error as exc:
            fail(f"{member_relpath(row)}: deflate error {exc}")
        total += len(span)
    return {"members": len(pinned), "member_span_bytes": total}


# --------------------------------------------------------------------------
# build / verify


def pcm_stats(pcm: bytes) -> dict:
    values = array.array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    channel_ranges = []
    channel_distinct = []
    for ch in range(CHANNELS):
        column = values[ch::CHANNELS]
        channel_ranges.append([min(column), max(column)])
        channel_distinct.append(len(set(column)))
    return {
        "value_count": len(values),
        "min": min(values),
        "max": max(values),
        "distinct_codes": len(set(values)),
        "full_scale_count": values.count(FULL_SCALE[0]) + values.count(FULL_SCALE[1]),
        "channel_min_max": channel_ranges,
        "channel_distinct_codes": channel_distinct,
    }


def exclusion_reason(stats: dict, digest: str, seen: set[str]) -> str | None:
    if stats["distinct_codes"] < MIN_DISTINCT_CODES:
        return f"fewer than {MIN_DISTINCT_CODES} distinct PCM codes ({stats['distinct_codes']})"
    dead = [ch for ch, (lo, hi) in enumerate(stats["channel_min_max"]) if lo == hi]
    if dead:
        return f"constant microphone channel(s) {dead}"
    if digest in seen:
        return "PCM payload byte-identical to an earlier selected clip"
    return None


def median(values: list[int]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def index_row(row: dict, pcm_len: int, stats: dict, digest: str) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_relpath(row),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": pcm_len,
        "value_count": stats["value_count"],
        "shape": [FRAMES, CHANNELS],
        "layout": "interleaved_frames_channel_fastest",
        "sample_rate_hz": SAMPLE_RATE,
        "channels": CHANNELS,
        "frames": FRAMES,
        "machine_type": "valve",
        "snr_db": 6,
        "model_id": row["model_id"],
        "condition": row["condition"],
        "member": row["member"],
        "member_crc32": f"{row['crc32']:08x}",
        "sha256": digest,
        "min": stats["min"],
        "max": stats["max"],
        "distinct_codes": stats["distinct_codes"],
        "full_scale_count": stats["full_scale_count"],
        "channel_min_max": stats["channel_min_max"],
    }


def build(download_dir: Path, data_root: Path, index_path: Path, stats_path: Path) -> dict:
    entries, pinned, selection_stats = checked_selection(download_dir)
    samples_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*"):
        stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate = hashlib.sha256()
    seen: set[str] = set()
    rows_out = []
    excluded = []
    layouts: dict[str, int] = {}
    masks: dict[str, int] = {}
    counts: dict[str, int] = {}
    totals = {"values": 0, "bytes": 0, "full_scale": 0}
    peak_abs = []
    for row in pinned:
        span = (download_dir / member_relpath(row)).read_bytes()
        pcm, chunk_ids, mask = decode_member_span(span, member_cd(row, entries))
        layout = ",".join(chunk_ids)
        layouts[layout] = layouts.get(layout, 0) + 1
        masks[f"0x{mask:08x}"] = masks.get(f"0x{mask:08x}", 0) + 1
        digest = sha256_bytes(pcm)
        stats = pcm_stats(pcm)
        reason = exclusion_reason(stats, digest, seen)
        seen.add(digest)
        if reason:
            excluded.append({"sample_id": row["sample_id"], "reason": reason})
            continue
        (data_root / sample_relpath(row)).write_bytes(pcm)
        aggregate.update(pcm)
        totals["values"] += stats["value_count"]
        totals["bytes"] += len(pcm)
        totals["full_scale"] += stats["full_scale_count"]
        peak_abs.append(max(-stats["min"], stats["max"]))
        group = f"{row['model_id']}/{row['condition']}"
        counts[group] = counts.get(group, 0) + 1
        rows_out.append(index_row(row, len(pcm), stats, digest))
    if len(excluded) > MAX_EXCLUDED_FRACTION * len(pinned):
        fail(f"{len(excluded)} of {len(pinned)} clips excluded; more than {MAX_EXCLUDED_FRACTION:.0%}")
    with index_path.open("w", encoding="utf-8") as fh:
        for row in rows_out:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    value_counts = [row["value_count"] for row in rows_out]
    distinct = [row["distinct_codes"] for row in rows_out]
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "selection": selection_stats,
        "pinned_members": len(pinned),
        "samples": len(rows_out),
        "excluded": excluded,
        "samples_per_group": dict(sorted(counts.items())),
        "total_values": totals["values"],
        "total_bytes": totals["bytes"],
        "median_values": median(value_counts),
        "full_scale_values": totals["full_scale"],
        "peak_abs_min": min(peak_abs),
        "peak_abs_median": median(peak_abs),
        "peak_abs_max": max(peak_abs),
        "distinct_codes_min": min(distinct),
        "distinct_codes_median": median(distinct),
        "distinct_codes_max": max(distinct),
        "riff_chunk_layouts": layouts,
        "channel_masks": masks,
        "aggregate_sha256": aggregate.hexdigest(),
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: summary[key] for key in ("samples", "total_values", "total_bytes", "full_scale_values", "aggregate_sha256")} | {"excluded": len(excluded)}


def verify(download_dir: Path, data_root: Path, index_path: Path, stats_path: Path, manifest_path: Path) -> dict:
    import tomllib

    if sys.version_info < (3, 12):
        fail("verify needs Python 3.12+ (stdlib wave support for WAVE_FORMAT_EXTENSIBLE)")
    entries, pinned, _ = checked_selection(download_dir)
    per_group: dict[tuple[str, str], int] = {}
    for row in pinned:
        per_group[(row["model_id"], row["condition"])] = per_group.get((row["model_id"], row["condition"]), 0) + 1
    if per_group != {(m, c): PICKS[c] for m in MODELS for c in CONDITIONS}:
        fail(f"pinned selection is not {PICKS} per model id: {per_group}")

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    by_path = {row["sample_path"]: row for row in index_rows}
    if len(by_path) != len(index_rows):
        fail("duplicate sample paths in index")
    aggregate = hashlib.sha256()
    seen: set[str] = set()
    excluded = []
    expected_paths = []
    values_total = bytes_total = 0
    for row in pinned:
        span = (download_dir / member_relpath(row)).read_bytes()
        frames = decode_member_independent(span, member_cd(row, entries))
        digest = sha256_bytes(frames)
        pstats = pcm_stats(frames)
        reason = exclusion_reason(pstats, digest, seen)
        seen.add(digest)
        if reason:
            excluded.append({"sample_id": row["sample_id"], "reason": reason})
            continue
        rel = sample_relpath(row)
        expected_paths.append(rel)
        got = by_path.get(rel)
        if got is None:
            fail(f"index lacks {rel}")
        sample = (data_root / rel).read_bytes()
        if sample != frames:
            fail(f"{rel}: sample bytes differ from the independent zipfile+wave decode")
        expect = index_row(row, len(frames), pstats, digest)
        if got != expect:
            diff = sorted(k for k in set(got) | set(expect) if got.get(k) != expect.get(k))
            fail(f"{rel}: index fields differ: {diff}")
        if pstats["min"] == pstats["max"]:
            fail(f"{rel}: constant sample")
        aggregate.update(frames)
        values_total += pstats["value_count"]
        bytes_total += len(frames)
    if [row["sample_path"] for row in index_rows] != expected_paths:
        fail("index rows are not exactly the expected samples in canonical order")
    on_disk = sorted(str(p.relative_to(data_root)) for p in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*"))
    if on_disk != sorted(expected_paths):
        fail("sample directory contains unexpected or missing files")
    if excluded != stats.get("excluded"):
        fail(f"exclusions {excluded} disagree with build stats {stats.get('excluded')}")
    if len(excluded) > MAX_EXCLUDED_FRACTION * len(pinned):
        fail("too many exclusions")
    if aggregate.hexdigest() != stats.get("aggregate_sha256"):
        fail("aggregate sha256 disagrees with build stats")
    if values_total != stats.get("total_values") or bytes_total != stats.get("total_bytes"):
        fail("totals disagree with build stats")
    med = median([row["value_count"] for row in index_rows])
    if not (values_total >= 10_000 or bytes_total >= 100_000) or med < 1_000:
        fail("primary floors not met")
    if bytes_total > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail("manifest must declare the series exactly once")
    if series[0].get("sample_count") != len(index_rows) or series[0].get("total_size_bytes") != bytes_total:
        fail(f"manifest totals ({series[0].get('sample_count')}, {series[0].get('total_size_bytes')}) != realized ({len(index_rows)}, {bytes_total})")
    return {"samples": len(index_rows), "excluded": len(excluded), "total_values": values_total,
            "total_bytes": bytes_total, "median_values": med, "aggregate_sha256": aggregate.hexdigest()}


# --------------------------------------------------------------------------
# self-test on synthetic inputs


def synthetic_wav(seed: int, channels: int = CHANNELS, guid: bytes = KSDATAFORMAT_SUBTYPE_PCM,
                  frames: int | None = None, extra_chunk: bool = True) -> bytes:
    """An 8-channel WAVE_FORMAT_EXTENSIBLE file shaped like the MIMII clips
    (fmt 40 B, fact, data), with a deterministic pseudo-random waveform."""
    frames = FRAMES if frames is None else frames
    state = seed & 0xFFFFFFFF or 1
    values = array.array("h")
    for i in range(frames * channels):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        values.append(((state >> 8) % 4001) - 2000 + (i % channels) * 3)
    if sys.byteorder != "little":
        values.byteswap()
    data = values.tobytes()
    fmt = struct.pack("<HHIIHHHHI", WAVE_FORMAT_EXTENSIBLE, channels, SAMPLE_RATE, SAMPLE_RATE * channels * 2,
                      channels * 2, BITS, 22, BITS, 0x63F) + guid
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"fact" + struct.pack("<I", 4) + struct.pack("<I", frames)
    if extra_chunk:
        body += b"LIST" + struct.pack("<I", 5) + b"INFOx" + b"\x00"  # odd size + pad byte
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def synthetic_cd_entry(name: bytes, crc: int, csize: int, usize: int, offset: int, wide_offset: bool) -> bytes:
    """A central-directory entry like the real archive: NTFS (0x000A, 32 B)
    extra, plus a ZIP64 (0x0001) block carrying only the offset when it is
    at or above 4 GiB."""
    ntfs = struct.pack("<HH", 0x000A, 32) + bytes(32)
    extra = (struct.pack("<HHQ", 0x0001, 8, offset) + ntfs) if wide_offset else ntfs
    return struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 63, 45 if wide_offset else 20, 0, 8, 0, 0, crc, csize, usize,
                       len(name), len(extra), 0, 0, 0, 0, 0xFFFFFFFF if wide_offset else offset) + name + extra


def selftest() -> None:
    global FRAMES, DATA_BYTES, WAV_BYTES, EXPECTED_FMT
    saved = (FRAMES, DATA_BYTES, WAV_BYTES, EXPECTED_FMT)
    try:
        # small synthetic clips: 400 frames x 8 channels
        FRAMES = 400
        DATA_BYTES = FRAMES * CHANNELS * 2
        wav = synthetic_wav(7)
        WAV_BYTES = len(wav)
        _selftest_body(wav)
    finally:
        FRAMES, DATA_BYTES, WAV_BYTES, EXPECTED_FMT = saved
    print("selftest ok", flush=True)


def _expect_failure(label: str, func, *args) -> None:
    try:
        func(*args)
    except (RecipeError, zlib.error, wave.Error, zipfile.BadZipFile, EOFError):
        return
    raise AssertionError(f"selftest: {label} was not rejected")


def _selftest_body(wav: bytes) -> None:
    expected_pcm = wav[wav.index(b"data") + 8:]
    # 1. zipfile-written deflate members; the second forces a ZIP64 local
    #    extra (local extra length 20) while the central directory has none,
    #    so the local header's own lengths must be used.
    buf = io.BytesIO()
    wav2 = synthetic_wav(11)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("valve/id_00/normal/", b"")
        archive.writestr("valve/id_00/normal/00000000.wav", wav)
        with archive.open("valve/id_00/normal/00000001.wav", "w", force_zip64=True) as fh:
            fh.write(wav2)
    blob = buf.getvalue()
    eocd = parse_eocd(blob[-22:], len(blob))
    entries = parse_central_directory(blob[eocd["cd_offset"]:eocd["cd_offset"] + eocd["cd_size"]], 3, eocd["cd_offset"])
    for entry, source in ((entries[1], wav), (entries[2], wav2)):
        span = blob[entry["local_header_offset"]:entry["local_header_offset"] + entry["span_bytes"]]
        pcm, chunk_ids, mask = decode_member_span(span, entry)
        if pcm != source[source.index(b"data") + 8:] or chunk_ids != ["fmt ", "fact", "LIST", "data"] or mask != 0x63F:
            raise AssertionError("selftest: build decoder output mismatch")
        if decode_member_independent(span, entry) != pcm:
            raise AssertionError("selftest: independent decoder disagrees")
    (_, _, _, _, _, _, _, _, _, nl, el) = struct.unpack("<IHHHHHIIIHH", blob[entries[2]["local_header_offset"]:entries[2]["local_header_offset"] + 30])
    if el == 0:
        raise AssertionError("selftest: forced ZIP64 local extra not produced")
    span1 = blob[entries[1]["local_header_offset"]:entries[1]["local_header_offset"] + entries[1]["span_bytes"]]
    if decode_member_span(span1, entries[1])[0] != expected_pcm:
        raise AssertionError("selftest: pcm mismatch")

    # 2. corruption and format rejections
    off = parse_local_header(span1, entries[1])
    corrupt = bytearray(span1)
    corrupt[off + len(corrupt[off:]) // 2] ^= 0x5A
    _expect_failure("corrupted deflate data", decode_member_span, bytes(corrupt), entries[1])
    _expect_failure("wrong CRC", decode_member_span, span1, dict(entries[1], crc32=entries[1]["crc32"] ^ 1))
    _expect_failure("truncated span", decode_member_span, span1[:-10], entries[1])
    _expect_failure("wrong name", decode_member_span, span1, dict(entries[1], name="valve/id_00/normal/00000009.wav"))
    _expect_failure("non-PCM subformat", parse_wav, synthetic_wav(3, guid=bytes.fromhex("0300000000001000800000aa00389b71")))
    _expect_failure("7-channel clip", parse_wav, synthetic_wav(3, channels=7))
    _expect_failure("short data chunk", parse_wav, synthetic_wav(3, frames=FRAMES - 1))
    plain = bytearray(wav)
    struct.pack_into("<H", plain, 20, 1)  # format tag -> WAVE_FORMAT_PCM
    _expect_failure("plain PCM tag", parse_wav, bytes(plain))
    stats = pcm_stats(expected_pcm)
    if exclusion_reason(stats, "a", set()) is not None or exclusion_reason(stats, "a", {"a"}) is None:
        raise AssertionError("selftest: exclusion rule")
    dead = array.array("h", expected_pcm)
    for i in range(3, len(dead), CHANNELS):
        dead[i] = 5
    if "constant microphone channel" not in (exclusion_reason(pcm_stats(dead.tobytes()), "b", set()) or ""):
        raise AssertionError("selftest: dead channel not excluded")

    # 3. ZIP64 EOCD + central-directory ZIP64 offset extra, as in the real tail
    big = 5_000_000_000
    cd = synthetic_cd_entry(b"valve/id_00/normal/00000000.wav", 1234, 1000, WAV_BYTES, 129, False)
    cd += synthetic_cd_entry(b"valve/id_06/normal/00000001.wav", 5678, 1100, WAV_BYTES, big, True)
    cd_offset = big + 2000
    eocd64 = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, 2, 2, len(cd), cd_offset)
    locator = struct.pack("<IIQI", 0x07064B50, 0, cd_offset + len(cd), 1)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 2, 2, len(cd), 0xFFFFFFFF, 0)
    tail = cd + eocd64 + locator + end
    size = cd_offset + len(tail)
    parsed = parse_eocd(tail, size)
    if parsed != {"entries": 2, "cd_offset": cd_offset, "cd_size": len(cd), "zip64": True}:
        raise AssertionError(f"selftest: ZIP64 EOCD parse {parsed}")
    cd_entries = parse_central_directory(cd, 2, cd_offset)
    if cd_entries[1]["local_header_offset"] != big or cd_entries[1]["span_bytes"] != 2000 or cd_entries[0]["span_bytes"] != big - 129:
        raise AssertionError("selftest: ZIP64 central-directory offset/span")
    bad_end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 2, 2, len(cd), 0xFFFFFFFF, 0)
    _expect_failure("missing ZIP64 locator", parse_eocd, cd + eocd64 + bad_end, size - 20)
    _expect_failure("inconsistent EOCD", parse_eocd, cd + eocd64 + locator + end, size + 7)

    # 4. selection arithmetic on a synthetic directory listing
    fake = []
    for (model, condition), n in sorted(GROUP_SIZES.items()):
        for i in range(n):
            fake.append({"cd_index": len(fake), "name": f"valve/{model}/{condition}/{i:08d}.wav", "method": 8,
                         "uncompressed_size": WAV_BYTES, "local_header_offset": len(fake) * 10, "span_bytes": 10,
                         "compressed_size": 5, "crc32": i})
    picked, _ = select_members(fake)
    if len(picked) != sum(PICKS[c] for _m in MODELS for c in CONDITIONS):
        raise AssertionError("selftest: selection size")
    first = [r for r in picked if r["model_id"] == "id_02" and r["condition"] == "normal"]
    if [r["group_rank"] for r in first[:3]] != [11, 35, 59]:  # floor((2k+1)*708/60)
        raise AssertionError(f"selftest: selection ranks {[r['group_rank'] for r in first[:3]]}")


# --------------------------------------------------------------------------
# discover


def discover(tail_path: Path, members_out: Path) -> dict:
    tail = tail_path.read_bytes()
    print(f"tail bytes={len(tail)} sha256={sha256_bytes(tail)}")
    entries = parse_tail_bytes(tail)
    selected, stats = select_members(entries)
    write_members(members_out, selected)
    stats["member_span_bytes"] = sum(row["span_bytes"] for row in selected)
    stats["tail_sha256"] = sha256_bytes(tail)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("discover")
    p.add_argument("--tail", type=Path, required=True)
    p.add_argument("--members-out", type=Path, required=True)
    p = sub.add_parser("check-record")
    p.add_argument("--record", type=Path, required=True)
    p = sub.add_parser("check-range")
    p.add_argument("--header", type=Path, required=True)
    p.add_argument("--first", type=int, required=True)
    p.add_argument("--last", type=int, required=True)
    for name in ("check-metadata", "check-members", "check-downloads"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
    p = sub.add_parser("plan-members")
    p.add_argument("--download-dir", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--pending-out", type=Path, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    sub.add_parser("selftest")
    sub.add_parser("tail-bytes")
    args = parser.parse_args()
    try:
        if args.cmd == "discover":
            result = discover(args.tail, args.members_out)
        elif args.cmd == "check-record":
            result = check_record(args.record)
        elif args.cmd == "check-range":
            check_range_header(args.header, args.first, args.last)
            result = {"content_range": "ok"}
        elif args.cmd == "check-metadata":
            _, pinned, stats = checked_selection(args.download_dir)
            result = stats | {"pinned_span_bytes": sum(r["span_bytes"] for r in pinned)}
        elif args.cmd == "check-members":
            result = check_members(args.download_dir)
        elif args.cmd == "check-downloads":
            result = check_downloads(args.download_dir)
        elif args.cmd == "plan-members":
            pending = plan_members(args.download_dir, args.plan)
            args.pending_out.write_text(f"{pending}\n", encoding="utf-8")
            result = {"pending": pending}
        elif args.cmd == "build":
            selftest()
            result = build(args.download_dir, args.data_root, args.index, args.stats)
        elif args.cmd == "verify":
            selftest()
            result = verify(args.download_dir, args.data_root, args.index, args.stats, args.manifest)
        elif args.cmd == "selftest":
            selftest()
            result = {"selftest": "ok"}
        elif args.cmd == "tail-bytes":
            print(f"{ARCHIVE['cd_offset']} {RECORD['size'] - 1} {TAIL_BYTES}")
            return 0
        else:
            parser.error(f"unknown command {args.cmd}")
            return 2
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr, flush=True)
        return 1
    print(json.dumps({"cmd": args.cmd, **result}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
