#!/usr/bin/env python3
"""EMPIAR-10318 200 kV MicroED diffraction frames: pins, validation, build, verify.

Pure standard library. The entry's eight ZIP archives (one continuous-rotation
series each) hold DEFLATE members named D520mm_NNNN.img. Each member is an SMV
(ADSC-style) diffraction image: a 512-byte ASCII header `{ KEY=VALUE; ... }`
padded with a form feed and spaces, then 4096 x 4096 little-endian uint16
detector values (33,554,944 bytes in total).

download.sh fetches, per archive, only the central directory plus end records
(a few KB, SHA-256 pinned) and, per selected frame, only the exact byte range
of the ZIP local header and compressed member. Local headers carry no extra
field (the central directory's 32-byte NTFS timestamp extra is absent there),
so the range is local header (30 bytes) + name + compressed data.
"""
from __future__ import annotations

import argparse
import array
import collections
import csv
import hashlib
import html
import json
import re
import shutil
import statistics
import struct
import sys
import tomllib
import zlib
from pathlib import Path


DATASET_ID = "empiar_10318_microed_diffraction_frames_u16"
SERIES_ID = "microed_200kv_diffraction_frame_u16"
ENTRY_KEY = "EMPIAR-10318"
ENTRY_TITLE = "200kV MicroED structure of FUS (37-42) SYSGYS solved from merged datasets at 0.65 A"
ENTRY_DOI = "10.6019/EMPIAR-10318"
BASE_URL = "https://ftp.ebi.ac.uk/empiar/world_availability/10318/data"
LICENSE_SENTENCE = (
    "All data in EMPIAR is freely and publicly available to the global community under the CC0 license"
)

WIDTH = 4096  # SMV SIZE1, fast axis
HEIGHT = 4096  # SMV SIZE2, slow axis
HEADER_BYTES = 512
PIXELS = WIDTH * HEIGHT  # 16,777,216
PIXEL_BYTES = PIXELS * 2  # 33,554,432
MEMBER_BYTES = HEADER_BYTES + PIXEL_BYTES  # 33,554,944
FRAMES_PER_SERIES = 3

HERE = Path(__file__).resolve().parent
ARCHIVES_TSV = HERE / "archives.tsv"
FRAMES_TSV = HERE / "frames.tsv"
ARCHIVE_FIELDS = ["archive", "archive_bytes", "zip_entries", "cd_offset", "cd_tail_bytes", "zip64_end_records", "cd_tail_sha256"]
FRAME_FIELDS = [
    "archive", "member", "frame_position", "series_frames", "local_header_offset", "range_bytes",
    "compressed_bytes", "uncompressed_bytes", "crc32", "phi_deg", "smv_header_sha256",
]

SMV_KEYS = [
    "HEADER_BYTES", "DIM", "BYTE_ORDER", "TYPE", "SIZE1", "SIZE2", "PIXEL_SIZE", "BIN", "DETECTOR_SN",
    "TIME", "DISTANCE", "PHI", "OSC_START", "OSC_RANGE", "WAVELENGTH", "BEAM_CENTER_X", "BEAM_CENTER_Y",
]
SMV_FIXED = {
    "HEADER_BYTES": "512",
    "DIM": "2",
    "BYTE_ORDER": "little_endian",
    "TYPE": "unsigned_short",
    "SIZE1": "4096",
    "SIZE2": "4096",
    "PIXEL_SIZE": "0.051000",
    "BIN": "1x1",
    "DETECTOR_SN": "0",
    "TIME": "5.720000",
    "DISTANCE": "3064.000000",
    "OSC_RANGE": "1.000000",
    "WAVELENGTH": "0.025071",
}

# Degeneracy floor applied identically by build and verify.
MIN_DISTINCT = 256
MAX_ZERO_FRACTION = 0.5
MAX_MODAL_FRACTION = 0.5
MIN_ABOVE_255 = 1000  # pixels using the upper byte (Bragg peaks / direct-beam halo)
MIN_MAXIMUM = 1000

# SHA-256 over "<sample file name>\t<sample sha256>\n" lines in pin order, from
# the first build of the 2026-10-06 autocollect download; build and verify require it.
EXPECTED_OUTPUT_DIGEST = "efa1456a2c4eb3e31054d1a6c96c0fa15ca84c223288bc8c69efc4723227a73d"


class SourceError(Exception):
    pass


# ---------------------------------------------------------------- pins / docs


def load_archives() -> dict[str, dict[str, str]]:
    with ARCHIVES_TSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != ARCHIVE_FIELDS:
        raise SourceError("unexpected archives.tsv columns")
    archives = {row["archive"]: row for row in rows}
    if len(archives) != 8:
        raise SourceError(f"archives.tsv lists {len(archives)} archives, expected 8")
    for row in rows:
        if not re.fullmatch(r"2018031[67]_\d{3}[-_]\d{3}", row["archive"]):
            raise SourceError(f"unexpected archive name {row['archive']!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", row["cd_tail_sha256"]):
            raise SourceError(f"malformed cd_tail_sha256 for {row['archive']}")
        if int(row["cd_offset"]) + int(row["cd_tail_bytes"]) != int(row["archive_bytes"]):
            raise SourceError(f"cd tail does not end at EOF for {row['archive']}")
    return archives


def load_frames() -> list[dict[str, str]]:
    archives = load_archives()
    with FRAMES_TSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != FRAME_FIELDS:
        raise SourceError("unexpected frames.tsv columns")
    if len(rows) != FRAMES_PER_SERIES * len(archives):
        raise SourceError(f"frames.tsv lists {len(rows)} frames, expected {FRAMES_PER_SERIES * len(archives)}")
    per_archive: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in rows:
        if row["archive"] not in archives:
            raise SourceError(f"frame row references unknown archive {row['archive']}")
        if not re.fullmatch(r"D520mm_\d{4}\.img", row["member"]):
            raise SourceError(f"unexpected member name {row['member']!r}")
        if int(row["uncompressed_bytes"]) != MEMBER_BYTES:
            raise SourceError(f"{row['member']}: pinned uncompressed size is not {MEMBER_BYTES}")
        if int(row["range_bytes"]) != 30 + len(row["member"]) + int(row["compressed_bytes"]):
            raise SourceError(f"{row['member']}: range_bytes != 30 + name + compressed")
        if not re.fullmatch(r"[0-9a-f]{8}", row["crc32"]) or not re.fullmatch(r"[0-9a-f]{64}", row["smv_header_sha256"]):
            raise SourceError(f"{row['member']}: malformed checksum pin")
        per_archive[row["archive"]].append(row)
    # Selection rule: positions floor(n * (2k + 1) / 6), k = 0, 1, 2, among the
    # n .img members of the series in name order (the 1/6, 1/2 and 5/6 points).
    for name, items in per_archive.items():
        n = int(items[0]["series_frames"])
        wanted = [n * (2 * k + 1) // 6 for k in range(FRAMES_PER_SERIES)]
        if [int(r["frame_position"]) for r in items] != wanted or any(int(r["series_frames"]) != n for r in items):
            raise SourceError(f"{name}: pinned frames do not follow the 1/6-1/2-5/6 selection rule")
    return rows


def member_url(archive: str) -> str:
    return f"{BASE_URL}/{archive}.zip"


def member_file(row: dict[str, str]) -> str:
    return f"{row['archive']}__{row['member']}.zipmember"


def cd_file(archive: str) -> str:
    return f"{archive}.cdtail"


def output_name(row: dict[str, str]) -> str:
    stem = row["member"].removesuffix(".img")
    return f"{row['archive']}_{stem}_h{HEIGHT}_w{WIDTH}_u16.bin"


# ---------------------------------------------------------------- metadata checks


def check_entry(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data.get(ENTRY_KEY)
    if not isinstance(entry, dict):
        raise SourceError("EMPIAR API response is not the EMPIAR-10318 entry")
    if entry.get("title") != ENTRY_TITLE or entry.get("entry_doi") != ENTRY_DOI:
        raise SourceError("EMPIAR entry title or DOI changed")
    if entry.get("status") != "REL" or entry.get("experiment_type") != "MicroED":
        raise SourceError("EMPIAR entry is not a released MicroED entry")
    sets = entry.get("imagesets") or []
    if len(sets) != 1:
        raise SourceError(f"expected one imageset, found {len(sets)}")
    item = sets[0]
    expected = {
        "directory": "data",
        "category": "diffraction images",
        "data_format": "SMV",
        "header_format": "SMV",
        "num_images_or_tilt_series": 8,
        "frames_per_image": 1,
        "image_width": "4096",
        "image_height": "4096",
        "pixel_width": 51.0,
        "pixel_height": 51.0,
    }
    for key, value in expected.items():
        if item.get(key) != value:
            raise SourceError(f"imageset field {key} changed: {item.get(key)!r}")
    details = str(item.get("details") or "")
    if "200kV" not in details or "0.02507" not in details or "8 crystals" not in details:
        raise SourceError("imageset details no longer describe the 200 kV, 8-crystal collection")
    return {
        "imageset_name": item.get("name"),
        "voxel_type_label": item.get("voxel_type"),
        "release_date": entry.get("release_date"),
        "related_pdb_entries": entry.get("related_pdb_entries"),
        "cross_references": entry.get("cross_references"),
    }


def check_license(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    if LICENSE_SENTENCE not in text:
        raise SourceError("EMPIAR FAQ no longer states the CC0 licence sentence")


def check_listing(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    names = sorted(set(re.findall(r'href="([^"?/]+\.zip)"', text)))
    expected = sorted(f"{name}.zip" for name in load_archives())
    if names != expected:
        raise SourceError(f"data directory lists {names}, expected {expected}")
    return names


def check_range_headers(path: Path, start: int, end: int, total: int) -> None:
    """The final HTTP response (after any proxy CONNECT block) must be an exact 206."""
    text = path.read_text(encoding="iso-8859-1")
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    if not blocks:
        raise SourceError("no HTTP response headers recorded")
    final = blocks[-1]
    status = re.match(r"HTTP/\S+\s+(\d+)", final)
    if not status or status.group(1) != "206":
        raise SourceError(f"server did not answer 206: {final.splitlines()[0]!r}")
    match = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if not match or tuple(map(int, match.groups())) != (start, end, total):
        raise SourceError(f"unexpected Content-Range {match.groups() if match else None}, wanted {(start, end, total)}")


# ---------------------------------------------------------------- ZIP structures


def parse_central_directory(blob: bytes, archive: dict[str, str]) -> dict[str, dict[str, int]]:
    """Parse the pinned tail [cd_offset, EOF): central directory, optional ZIP64 end records, EOCD."""
    total = int(archive["archive_bytes"])
    cd_offset = int(archive["cd_offset"])
    if len(blob) != total - cd_offset:
        raise SourceError(f"{archive['archive']}: cd tail has {len(blob)} bytes, expected {total - cd_offset}")
    if hashlib.sha256(blob).hexdigest() != archive["cd_tail_sha256"]:
        raise SourceError(f"{archive['archive']}: central directory SHA-256 changed")
    eocd = len(blob) - 22
    sig, disk, cd_disk, n_this, n_total, cd_size, cd_off, comment_len = struct.unpack_from("<IHHHHIIH", blob, eocd)
    if sig != 0x06054B50 or comment_len != 0 or disk or cd_disk or n_this != n_total:
        raise SourceError(f"{archive['archive']}: malformed end of central directory record")
    if n_total != int(archive["zip_entries"]) or cd_off != cd_offset:
        raise SourceError(f"{archive['archive']}: EOCD entry count or offset changed")
    cd_end = cd_size
    if int(archive["zip64_end_records"]):
        z64 = cd_size
        if z64 + 76 != eocd:
            raise SourceError(f"{archive['archive']}: ZIP64 end records not where expected")
        fields = struct.unpack_from("<IQHHIIQQQQ", blob, z64)
        if fields[0] != 0x06064B50 or fields[1] != 44 or fields[6:] != (n_total, n_total, cd_size, cd_offset):
            raise SourceError(f"{archive['archive']}: malformed ZIP64 end of central directory record")
        loc = struct.unpack_from("<IIQI", blob, z64 + 56)
        if loc[0] != 0x07064B50 or loc[2] != cd_offset + z64 or loc[3] != 1:
            raise SourceError(f"{archive['archive']}: malformed ZIP64 end locator")
    elif cd_size != eocd:
        raise SourceError(f"{archive['archive']}: unexpected bytes between central directory and EOCD")
    members: dict[str, dict[str, int]] = {}
    pos = 0
    for _ in range(n_total):
        f = struct.unpack_from("<IHHHHHHIIIHHHHHII", blob, pos)
        if f[0] != 0x02014B50:
            raise SourceError(f"{archive['archive']}: bad central directory signature at {pos}")
        name_len, extra_len, comment = f[10], f[11], f[12]
        name = blob[pos + 46 : pos + 46 + name_len].decode("cp437")
        members[name] = {
            "flags": f[3], "method": f[4], "crc32": f[7], "compressed": f[8], "uncompressed": f[9],
            "disk": f[13], "local_header_offset": f[16],
        }
        pos += 46 + name_len + extra_len + comment
    if pos != cd_end:
        raise SourceError(f"{archive['archive']}: central directory length mismatch")
    return members


def check_cd_against_pins(archive_name: str, blob: bytes) -> int:
    archives = load_archives()
    members = parse_central_directory(blob, archives[archive_name])
    imgs = sorted(name for name in members if name.endswith(".img"))
    others = sorted(name for name in members if not name.endswith(".img"))
    if len(others) != 1 or not others[0].endswith(".cec"):
        raise SourceError(f"{archive_name}: unexpected non-image members {others}")
    numbers = [int(name[7:11]) for name in imgs]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise SourceError(f"{archive_name}: image members are not consecutively numbered")
    rows = [row for row in load_frames() if row["archive"] == archive_name]
    for row in rows:
        member = members.get(row["member"])
        if member is None:
            raise SourceError(f"{archive_name}: pinned member {row['member']} missing")
        if imgs.index(row["member"]) != int(row["frame_position"]) or len(imgs) != int(row["series_frames"]):
            raise SourceError(f"{archive_name}: {row['member']} position changed")
        expected = {
            "flags": 0, "method": 8, "crc32": int(row["crc32"], 16), "compressed": int(row["compressed_bytes"]),
            "uncompressed": int(row["uncompressed_bytes"]), "disk": 0, "local_header_offset": int(row["local_header_offset"]),
        }
        if member != expected:
            raise SourceError(f"{archive_name}: central directory entry for {row['member']} differs from pins")
    for name in imgs:
        if members[name]["uncompressed"] != MEMBER_BYTES or members[name]["method"] != 8:
            raise SourceError(f"{archive_name}: {name} is not a {MEMBER_BYTES}-byte DEFLATE member")
    return len(imgs)


def read_local_member(path: Path, row: dict[str, str]) -> tuple[bytes, int]:
    """Return (range bytes, data offset) after validating the local header against the pins."""
    payload = path.read_bytes()
    if len(payload) != int(row["range_bytes"]):
        raise SourceError(f"{path.name}: {len(payload)} bytes, expected {row['range_bytes']}")
    sig, version, flags, method, _t, _d, crc, csize, usize, name_len, extra_len = struct.unpack_from("<4s5H3I2H", payload, 0)
    if sig != b"PK\x03\x04":
        raise SourceError(f"{path.name}: no ZIP local header signature")
    name = payload[30 : 30 + name_len].decode("cp437")
    data_offset = 30 + name_len + extra_len  # the local header's own lengths
    if (
        name != row["member"]
        or flags != 0
        or method != 8
        or crc != int(row["crc32"], 16)
        or csize != int(row["compressed_bytes"])
        or usize != int(row["uncompressed_bytes"])
        or data_offset + csize != len(payload)
    ):
        raise SourceError(f"{path.name}: local header does not match the pinned member")
    return payload, data_offset


def inflate_member(payload: bytes, data_offset: int, row: dict[str, str]) -> bytes:
    """Streaming raw-DEFLATE decode to exactly MEMBER_BYTES with CRC-32 check."""
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    parts = []
    view = memoryview(payload)[data_offset:]
    step = 1 << 20
    for offset in range(0, len(view), step):
        parts.append(decoder.decompress(view[offset : offset + step]))
    parts.append(decoder.flush())
    if not decoder.eof or decoder.unused_data:
        raise SourceError(f"{row['member']}: DEFLATE stream does not end at the member boundary")
    data = b"".join(parts)
    if len(data) != MEMBER_BYTES:
        raise SourceError(f"{row['member']}: inflated to {len(data)} bytes, expected {MEMBER_BYTES}")
    if zlib.crc32(data) & 0xFFFFFFFF != int(row["crc32"], 16):
        raise SourceError(f"{row['member']}: CRC-32 mismatch")
    return data


def parse_smv_header(header: bytes, row: dict[str, str]) -> dict[str, str]:
    if len(header) != HEADER_BYTES or not header.startswith(b"{\n"):
        raise SourceError(f"{row['member']}: SMV header does not start with '{{'")
    close = header.find(b"}")
    if close < 0:
        raise SourceError(f"{row['member']}: SMV header has no closing brace")
    padding = header[close + 1 :]
    if padding.strip(b" \x0c\x00\n\r") != b"":
        raise SourceError(f"{row['member']}: non-padding bytes after the SMV header")
    fields: dict[str, str] = {}
    for statement in header[1:close].decode("ascii").split(";"):
        statement = statement.strip()
        if not statement:
            continue
        key, sep, value = statement.partition("=")
        if not sep or key.strip() in fields:
            raise SourceError(f"{row['member']}: malformed SMV statement {statement!r}")
        fields[key.strip()] = value.strip()
    if list(fields) != SMV_KEYS:
        raise SourceError(f"{row['member']}: SMV key set changed: {list(fields)}")
    for key, wanted in SMV_FIXED.items():
        if fields[key] != wanted:
            raise SourceError(f"{row['member']}: SMV {key}={fields[key]!r}, expected {wanted!r}")
    if fields["PHI"] != row["phi_deg"] or fields["OSC_START"] != row["phi_deg"]:
        raise SourceError(f"{row['member']}: rotation angle {fields['PHI']} differs from pin {row['phi_deg']}")
    if hashlib.sha256(header).hexdigest() != row["smv_header_sha256"]:
        raise SourceError(f"{row['member']}: SMV header SHA-256 changed")
    return fields


# ---------------------------------------------------------------- pixel statistics


def pixel_stats(pixels: bytes) -> dict[str, object]:
    if len(pixels) != PIXEL_BYTES:
        raise SourceError("pixel block has the wrong size")
    values = array.array("H")
    values.frombytes(pixels)
    if sys.byteorder != "little":
        values.byteswap()
    hist = collections.Counter(values)
    total = len(values)
    ordered = sorted(hist)
    modal_value, modal_count = max(hist.items(), key=lambda item: (item[1], -item[0]))

    def quantile(q: float) -> int:
        target = q * total
        running = 0
        for value in ordered:
            running += hist[value]
            if running >= target:
                return value
        return ordered[-1]

    row_bytes = WIDTH * 2
    constant_rows = 0
    for r in range(HEIGHT):
        line = pixels[r * row_bytes : (r + 1) * row_bytes]
        if line == line[:2] * WIDTH:
            constant_rows += 1
    constant_cols = 0
    for c in range(WIDTH):
        column = values[c::WIDTH]
        if column.count(column[0]) == HEIGHT:
            constant_cols += 1
    zeros = hist.get(0, 0)
    stats = {
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "distinct_values": len(ordered),
        "mean": round(sum(v * c for v, c in hist.items()) / total, 6),
        "median": quantile(0.5),
        "p99": quantile(0.99),
        "p99_99": quantile(0.9999),
        "zero_values": zeros,
        "zero_fraction": round(zeros / total, 6),
        "above_255": sum(c for v, c in hist.items() if v > 255),
        "above_1000": sum(c for v, c in hist.items() if v > 1000),
        "above_32767": sum(c for v, c in hist.items() if v > 32767),
        "max_values": hist.get(65535, 0),
        "modal_value": modal_value,
        "modal_fraction": round(modal_count / total, 9),
        "constant_rows": constant_rows,
        "constant_cols": constant_cols,
        "zlib1_ratio": round(len(zlib.compress(pixels, 1)) / len(pixels), 6),
        "sha256": hashlib.sha256(pixels).hexdigest(),
    }
    problems = []
    if stats["minimum"] == stats["maximum"]:
        problems.append("constant frame")
    if stats["distinct_values"] < MIN_DISTINCT:
        problems.append(f"only {stats['distinct_values']} distinct values")
    if stats["zero_fraction"] > MAX_ZERO_FRACTION:
        problems.append(f"zero fraction {stats['zero_fraction']}")
    if stats["modal_fraction"] > MAX_MODAL_FRACTION:
        problems.append(f"modal value {modal_value} covers {stats['modal_fraction']:.3f} of pixels")
    if stats["above_255"] < MIN_ABOVE_255 or stats["maximum"] < MIN_MAXIMUM:
        problems.append(f"no diffraction signal above background (above_255={stats['above_255']}, max={stats['maximum']})")
    if constant_rows or constant_cols:
        problems.append(f"{constant_rows} constant rows / {constant_cols} constant columns")
    if problems:
        raise SourceError("degenerate frame: " + "; ".join(problems))
    return stats


STAT_KEYS = [
    "minimum", "maximum", "distinct_values", "mean", "median", "p99", "p99_99", "zero_values", "zero_fraction",
    "above_255", "above_1000", "above_32767", "max_values", "modal_value", "modal_fraction", "constant_rows",
    "constant_cols", "zlib1_ratio", "sha256",
]


# ---------------------------------------------------------------- build / verify


def decode_frame(download_dir: Path, row: dict[str, str]) -> tuple[dict[str, str], bytes]:
    payload, offset = read_local_member(download_dir / member_file(row), row)
    data = inflate_member(payload, offset, row)
    fields = parse_smv_header(data[:HEADER_BYTES], row)
    return fields, data[HEADER_BYTES:]


def check_metadata(download_dir: Path) -> dict[str, object]:
    entry = check_entry(download_dir / "empiar_10318_entry.json")
    check_license(download_dir / "empiar_faq.html")
    check_listing(download_dir / "data_listing.html")
    for name in load_archives():
        check_cd_against_pins(name, (download_dir / cd_file(name)).read_bytes())
    return entry


def scan_all(download_dir: Path) -> list[dict[str, object]]:
    rows = load_frames()
    check_metadata(download_dir)
    reports = []
    seen: set[str] = set()
    centers: dict[str, tuple[str, str]] = {}
    for row in rows:
        fields, pixels = decode_frame(download_dir, row)
        center = (fields["BEAM_CENTER_X"], fields["BEAM_CENTER_Y"])
        if centers.setdefault(row["archive"], center) != center:
            raise SourceError(f"{row['archive']}: beam centre differs between frames of one series")
        try:
            stats = pixel_stats(pixels)
        except SourceError as error:
            raise SourceError(f"{row['archive']}/{row['member']}: {error}") from error
        if stats["sha256"] in seen:
            raise SourceError(f"{row['archive']}/{row['member']}: duplicate pixel payload")
        seen.add(str(stats["sha256"]))
        report = {
            "archive": row["archive"],
            "member": row["member"],
            "frame_position": int(row["frame_position"]),
            "series_frames": int(row["series_frames"]),
            "phi_deg": float(fields["PHI"]),
            "beam_center_x_mm": float(fields["BEAM_CENTER_X"]),
            "beam_center_y_mm": float(fields["BEAM_CENTER_Y"]),
            "crc32": row["crc32"],
            **stats,
        }
        reports.append(report)
        print(
            f"{row['archive']}/{row['member']} phi={fields['PHI']} min={stats['minimum']} max={stats['maximum']} "
            f"distinct={stats['distinct_values']} mean={stats['mean']:.2f} zero_frac={stats['zero_fraction']:.4f} "
            f">255={stats['above_255']} >1000={stats['above_1000']} zlib1={stats['zlib1_ratio']}",
            flush=True,
        )
    return reports


def summarize(reports: list[dict[str, object]], enforce_digest: bool = True) -> dict[str, object]:
    ratios = [float(r["zlib1_ratio"]) for r in reports]
    zero_fracs = [float(r["zero_fraction"]) for r in reports]
    global_max = max(int(r["maximum"]) for r in reports)
    digest = hashlib.sha256(
        "".join(f"{output_name(r)}\t{r['sha256']}\n" for r in reports).encode()  # type: ignore[arg-type]
    ).hexdigest()
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "series_count": len({r["archive"] for r in reports}),
        "value_count": len(reports) * PIXELS,
        "total_size_bytes": len(reports) * PIXEL_BYTES,
        "unique_payloads": len({r["sha256"] for r in reports}),
        "global_minimum": min(int(r["minimum"]) for r in reports),
        "global_maximum": global_max,
        "all_frames_max_le_32767": global_max <= 32767,
        "pixels_above_32767": sum(int(r["above_32767"]) for r in reports),
        "minimum_distinct_values": min(int(r["distinct_values"]) for r in reports),
        "zero_fraction_min": min(zero_fracs),
        "zero_fraction_median": statistics.median(zero_fracs),
        "zero_fraction_max": max(zero_fracs),
        "maximum_modal_fraction": max(float(r["modal_fraction"]) for r in reports),
        "minimum_above_255": min(int(r["above_255"]) for r in reports),
        "constant_rows": sum(int(r["constant_rows"]) for r in reports),
        "constant_cols": sum(int(r["constant_cols"]) for r in reports),
        "minimum_zlib1_ratio": min(ratios),
        "median_zlib1_ratio": statistics.median(ratios),
        "maximum_zlib1_ratio": max(ratios),
        "phi_range_deg": [min(float(r["phi_deg"]) for r in reports), max(float(r["phi_deg"]) for r in reports)],
        "output_digest": digest,
    }
    if enforce_digest and EXPECTED_OUTPUT_DIGEST and digest != EXPECTED_OUTPUT_DIGEST:
        raise SourceError(f"output digest {digest} != pinned {EXPECTED_OUTPUT_DIGEST}")
    return summary


def index_row(report: dict[str, object], sample_path: str) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_path,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": PIXEL_BYTES,
        "value_count": PIXELS,
        "sample_format": "raw homogeneous little-endian uint16 MicroED diffraction frame",
        "sample_geometry": "electron_diffraction_detector_frame_2d",
        "sample_rank": 2,
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["detector_slow_y", "detector_fast_x"],
        "natural_record_kind": "microed_rotation_series_smv_frame",
        "source_url": member_url(str(report["archive"])),
        "source_archive": f"{report['archive']}.zip",
        "source_member": report["member"],
        "source_member_crc32": report["crc32"],
        "source_pixel_offset": HEADER_BYTES,
        "series_frame_position": report["frame_position"],
        "series_frame_count": report["series_frames"],
        "phi_deg": report["phi_deg"],
        "osc_range_deg": 1.0,
        "exposure_s": 5.72,
        "wavelength_angstrom": 0.025071,
        "beam_center_x_mm": report["beam_center_x_mm"],
        "beam_center_y_mm": report["beam_center_y_mm"],
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "distinct_values": report["distinct_values"],
        "mean": report["mean"],
        "zero_fraction": report["zero_fraction"],
        "sha256": report["sha256"],
    }


def build(args: argparse.Namespace) -> None:
    rows = load_frames()
    reports = scan_all(args.download_dir)
    summary = summarize(reports)
    series_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    if summary["total_size_bytes"] >= 1_000_000_000:
        raise SourceError("primary output would reach the 1 GB cap")
    index_rows = []
    for row, report in zip(rows, reports, strict=True):
        _fields, pixels = decode_frame(args.download_dir, row)
        if hashlib.sha256(pixels).hexdigest() != report["sha256"]:
            raise SourceError(f"source changed during build: {row['member']}")
        output = series_dir / output_name(row)
        output.write_bytes(pixels)
        index_rows.append(index_row(report, output.relative_to(args.data_root).as_posix()))
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps({**summary, "frames": reports}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not EXPECTED_OUTPUT_DIGEST:
        print(f"NOTE: output digest not pinned yet; observed {summary['output_digest']}")


# Independent re-derivation for verify: one-shot inflate and a regex SMV parse,
# separate from the streaming decoder and statement parser used by build.


def verify_decode(download_dir: Path, row: dict[str, str]) -> bytes:
    blob = (download_dir / member_file(row)).read_bytes()
    if blob[:4] != b"PK\x03\x04":
        raise SourceError(f"{row['member']}: missing local header")
    name_len, extra_len = struct.unpack_from("<HH", blob, 26)
    start = 30 + name_len + extra_len
    if blob[30 : 30 + name_len] != row["member"].encode() or len(blob) - start != int(row["compressed_bytes"]):
        raise SourceError(f"{row['member']}: local header lengths disagree with pins")
    data = zlib.decompress(blob[start:], -15)
    if len(data) != MEMBER_BYTES or zlib.crc32(data) & 0xFFFFFFFF != int(row["crc32"], 16):
        raise SourceError(f"{row['member']}: independent inflate mismatch")
    header = data[:HEADER_BYTES].decode("ascii")
    pairs = dict(re.findall(r"([A-Z_0-9]+)=([^;\n]*);", header))
    want = {
        "HEADER_BYTES": str(HEADER_BYTES), "TYPE": "unsigned_short", "BYTE_ORDER": "little_endian",
        "SIZE1": str(WIDTH), "SIZE2": str(HEIGHT), "DIM": "2",
    }
    if any(pairs.get(k, "").strip() != v for k, v in want.items()):
        raise SourceError(f"{row['member']}: independent SMV header check failed: {pairs}")
    return data[HEADER_BYTES:]


def verify(args: argparse.Namespace) -> None:
    rows = load_frames()
    reports = scan_all(args.download_dir)
    summary = summarize(reports)
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SourceError("missing index or ingest stats; run build.sh first")
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index_rows) != len(rows):
        raise SourceError(f"index has {len(index_rows)} rows, expected {len(rows)}")
    expected_paths = set()
    for item, row, report in zip(index_rows, rows, reports, strict=True):
        expected = json.loads(json.dumps(index_row(report, f"samples/{DATASET_ID}/{SERIES_ID}/{output_name(row)}")))
        if item != expected:
            diff = sorted(k for k in set(item) | set(expected) if item.get(k) != expected.get(k))
            raise SourceError(f"index row mismatch for {row['member']}: {diff}")
        output = args.data_root / item["sample_path"]
        expected_paths.add(output.resolve())
        if not output.is_file() or output.stat().st_size != PIXEL_BYTES:
            raise SourceError(f"missing or mis-sized sample for {row['archive']}/{row['member']}")
        data = output.read_bytes()
        if data != verify_decode(args.download_dir, row):
            raise SourceError(f"sample for {row['archive']}/{row['member']} is not the source pixel block")
        recomputed = pixel_stats(data)
        if recomputed != {k: report[k] for k in STAT_KEYS}:
            raise SourceError(f"sample statistics differ for {row['member']}")
    actual = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if actual != expected_paths:
        raise SourceError("sample directory contents do not match the index")
    stored = json.loads(stats_path.read_text(encoding="utf-8"))
    for key, value in json.loads(json.dumps(summary)).items():
        if stored.get(key) != value:
            raise SourceError(f"ingest statistic {key} differs: {stored.get(key)!r} != {value!r}")
    if stored.get("frames") != json.loads(json.dumps(reports)):
        raise SourceError("stored per-frame reports differ")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1:
        raise SourceError("manifest must declare exactly the one primary series")
    if int(series[0]["sample_count"]) != summary["sample_count"] or int(series[0]["total_size_bytes"]) != summary["total_size_bytes"]:
        raise SourceError("manifest sample_count/total_size_bytes do not match realized output")
    if summary["unique_payloads"] != len(rows) or summary["series_count"] != 8 or summary["total_size_bytes"] >= 1_000_000_000:
        raise SourceError("aggregate scope or degeneracy check failed")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": summary["sample_count"],
        "verified_values": summary["value_count"],
        "verified_bytes": summary["total_size_bytes"],
        "global_maximum": summary["global_maximum"],
        "all_frames_max_le_32767": summary["all_frames_max_le_32767"],
        "zero_fraction_median": summary["zero_fraction_median"],
        "output_digest": summary["output_digest"],
        "output_digest_pinned": bool(EXPECTED_OUTPUT_DIGEST),
    }, indent=2, sort_keys=True))


# ---------------------------------------------------------------- download helpers


def cmd_check_member(args: argparse.Namespace) -> None:
    rows = [r for r in load_frames() if r["archive"] == args.archive and r["member"] == args.member]
    if len(rows) != 1:
        raise SourceError(f"{args.archive}/{args.member} is not a pinned frame")
    row = rows[0]
    payload, offset = read_local_member(args.path, row)
    data = inflate_member(payload, offset, row)
    fields = parse_smv_header(data[:HEADER_BYTES], row)
    pixels = data[HEADER_BYTES:]
    if pixels.count(pixels[:2]) * 2 == len(pixels):
        raise SourceError(f"{args.member}: constant pixel block")
    print(f"ok {args.archive}/{args.member} phi={fields['PHI']} crc32={row['crc32']}")


def cmd_inventory(args: argparse.Namespace) -> None:
    entry = check_metadata(args.download_dir)
    rows = load_frames()
    files = []
    for row in rows:
        path = args.download_dir / member_file(row)
        read_local_member(path, row)
        files.append({"archive": row["archive"], "member": row["member"], "range_bytes": path.stat().st_size, "crc32": row["crc32"]})
    meta_bytes = sum((args.download_dir / cd_file(name)).stat().st_size for name in load_archives())
    inventory = {
        "entry": ENTRY_KEY,
        "doi": ENTRY_DOI,
        "imageset": entry,
        "license": "CC0-1.0",
        "frames": files,
        "member_range_bytes": sum(f["range_bytes"] for f in files),
        "central_directory_bytes": meta_bytes,
    }
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"inventory frames={len(files)} member_range_bytes={inventory['member_range_bytes']} cd_bytes={meta_bytes}")


def cmd_archive_pins(_args: argparse.Namespace) -> None:
    """archive, URL, cd range start, cd range end, archive bytes (for download.sh)."""
    for name, row in load_archives().items():
        print("\t".join([name, member_url(name), row["cd_offset"], str(int(row["archive_bytes"]) - 1), row["archive_bytes"], cd_file(name)]))


def cmd_frame_pins(_args: argparse.Namespace) -> None:
    """archive, member, URL, range start, range end, archive bytes, local file name (for download.sh)."""
    archives = load_archives()
    for row in load_frames():
        start = int(row["local_header_offset"])
        end = start + int(row["range_bytes"]) - 1
        print("\t".join([row["archive"], row["member"], member_url(row["archive"]), str(start), str(end), archives[row["archive"]]["archive_bytes"], member_file(row)]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-entry"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-license"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-listing"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-range-headers")
    p.add_argument("path", type=Path); p.add_argument("start", type=int); p.add_argument("end", type=int); p.add_argument("total", type=int)
    p = sub.add_parser("check-cd"); p.add_argument("archive"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-member"); p.add_argument("archive"); p.add_argument("member"); p.add_argument("path", type=Path)
    p = sub.add_parser("inventory"); p.add_argument("--download-dir", type=Path, required=True)
    sub.add_parser("archive-pins")
    sub.add_parser("frame-pins")
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check-entry":
            print(json.dumps(check_entry(args.path)))
        elif args.command == "check-license":
            check_license(args.path)
            print("license=CC0-1.0 (EMPIAR FAQ sentence present)")
        elif args.command == "check-listing":
            print(f"listing ok: {len(check_listing(args.path))} archives")
        elif args.command == "check-range-headers":
            check_range_headers(args.path, args.start, args.end, args.total)
        elif args.command == "check-cd":
            count = check_cd_against_pins(args.archive, args.path.read_bytes())
            print(f"central directory ok: {args.archive} images={count}")
        elif args.command == "check-member":
            cmd_check_member(args)
        elif args.command == "inventory":
            cmd_inventory(args)
        elif args.command == "archive-pins":
            cmd_archive_pins(args)
        elif args.command == "frame-pins":
            cmd_frame_pins(args)
        elif args.command == "build":
            build(args)
        elif args.command == "verify":
            verify(args)
    except SourceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
