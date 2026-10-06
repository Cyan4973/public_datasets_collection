#!/usr/bin/env python3
"""GEO GSE23678 PerkinElmer ScanArray Express microarray scans -> raw uint16 rasters.

Pure standard-library Python. Subcommands:

  selftest                 round-trip synthetic ScanArray-layout TIFFs through
                           the build parser and the independent verify reader,
                           and check that malformed variants are rejected
  probe-header FILE        print the header fields of a (possibly partial)
                           .tif.gz prefix as one TSV line (discover.sh)
  check-file --sources S --file F
                           validate one downloaded .tif.gz against its pinned
                           sources.tsv row (download.sh)
  build                    decode the pinned local files into samples + index
  verify                   re-derive every sample with a separate TIFF reader
                           and re-check index, stats, manifest totals and the
                           non-degeneracy rules

Only local files are read by build/verify; network I/O lives in the shell
scripts (curl).
"""
from __future__ import annotations

import argparse
import array
import collections
import csv
import gzip
import hashlib
import json
import re
import shutil
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "ncbi_geo_gpl5423_scanarray_cdna_scan_u16"
SERIES_BY_DYE = {"Cy3": "scanarray_cy3_scan_u16", "Cy5": "scanarray_cy5_scan_u16"}
FLUOR_BY_DYE = {"Cy3": "Cyanine 3", "Cy5": "Cyanine 5"}
WIDTH = 2200
BYTES_PER_PIXEL = 2
STRIP_BYTES = WIDTH * BYTES_PER_PIXEL  # one row per strip -> 4400 bytes
HEIGHT_RANGE = (6000, 8000)
EXPECTED_FILES = 24
EXPECTED_DOWNLOAD_BYTES = 584_061_895
EXPECTED_PRIMARY_BYTES = 744_268_800
SATURATED = 65535

MAKE = "PerkinElmer"
MODEL_PREFIX = "Express"
MODEL_SERIAL = "430723"
SOFTWARE_PREFIX = "ScanArray Express"
COPYRIGHT = "Copyright (C) 2002 PerkinElmer, Inc."
PROTOCOL_NAME = "Easy Scan"
RESOLUTION_UM = "10"
LASER_POWER = "90"
DPI = (2540, 1)  # 2540 pixels per inch = 10 um pixels

# Non-degeneracy thresholds (applied identically by build and verify).
MIN_DISTINCT = 1000
MAX_ZERO_FRACTION = 0.05
MAX_SATURATED_FRACTION = 0.02
MAX_CONSTANT_ROW_FRACTION = 0.05

# The exact tag set every ScanArray Express 2.1 file in the selection carries.
EXPECTED_TAGS = (
    254, 256, 257, 258, 259, 262, 270, 271, 272, 273, 274, 277, 278, 279,
    282, 283, 284, 296, 305, 306, 315, 316, 33432,
)
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i"}
SOURCE_COLUMNS = [
    "gsm", "hyb", "dye", "filename", "size_bytes", "gzip_crc32", "tiff_bytes",
    "height", "scan_datetime", "sha256", "url",
]
FILENAME_RE = re.compile(r"^(GSM\d+)_(NK\d+)_(Cy3|Cy5)_(Aug_\d+_06)\.tif\.gz$")
DATETIME_RE = re.compile(r"^\d{4}:\d\d:\d\d \d\d:\d\d:\d\d$")


class FormatError(ValueError):
    pass


def fail(message: str) -> None:
    raise FormatError(message)


# --------------------------------------------------------------------------
# Build-side TIFF parser: full IFD decode, strict layout checks.
# --------------------------------------------------------------------------

def _tag_values(data: bytes, entry_offset: int) -> tuple[int, int, object, int]:
    """Return (tag, type, value, end) where end is the file offset just past an
    out-of-line value (0 for values stored inline in the entry)."""
    tag, typ, count = struct.unpack_from("<HHI", data, entry_offset)
    if typ not in TYPE_SIZES or count == 0:
        fail(f"tag {tag}: unsupported type/count {typ}/{count}")
    size = TYPE_SIZES[typ] * count
    start = entry_offset + 8 if size <= 4 else struct.unpack_from("<I", data, entry_offset + 8)[0]
    if start + size > len(data):
        fail(f"tag {tag}: values beyond available bytes")
    if typ == 2:
        raw = data[start:start + count]
        if not raw.endswith(b"\0"):
            fail(f"tag {tag}: ASCII value not NUL-terminated")
        value: object = raw[:-1].decode("latin-1")
    elif typ in (5, 10):
        value = struct.unpack_from("<%d%s" % (2 * count, "I" if typ == 5 else "i"), data, start)
    elif typ in TYPE_FMT:
        value = struct.unpack_from("<%d%s" % (count, TYPE_FMT[typ]), data, start)
    else:
        fail(f"tag {tag}: unhandled type {typ}")
    return tag, typ, value, (start + size if size > 4 else 0)


def parse_description(text: str) -> dict[str, str]:
    """ScanArray ImageDescription: '#'-separated key=value pairs (some
    fragments such as 'LaserWavelength543' carry no '=' and are ignored)."""
    fields: dict[str, str] = {}
    for part in text.split("#"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    return fields


def parse_tiff(data: bytes, full: bool = True, height_range: tuple[int, int] | None = None) -> dict:
    """Parse and validate one ScanArray Express TIFF. With full=False only
    the header/IFD/strip tables need to be present (partial prefix)."""
    if len(data) < 8 or data[:4] != b"II*\x00":
        fail("not a little-endian classic TIFF ('II', 42)")
    ifd = struct.unpack_from("<I", data, 4)[0]
    if ifd < 8 or ifd + 2 > len(data):
        fail("IFD0 offset out of bounds")
    count = struct.unpack_from("<H", data, ifd)[0]
    if ifd + 2 + 12 * count + 4 > len(data):
        fail("truncated IFD0")
    tags: dict[int, tuple[int, object]] = {}
    previous = -1
    meta_end = ifd + 2 + 12 * count + 4
    for index in range(count):
        tag, typ, value, end = _tag_values(data, ifd + 2 + 12 * index)
        meta_end = max(meta_end, end)
        if tag <= previous:
            fail("IFD0 tags not strictly ascending")
        previous = tag
        tags[tag] = (typ, value)
    next_ifd = struct.unpack_from("<I", data, ifd + 2 + 12 * count)[0]
    if next_ifd != 0:
        fail(f"more than one IFD (next IFD offset {next_ifd})")
    if tuple(sorted(tags)) != EXPECTED_TAGS:
        fail(f"unexpected tag set {sorted(tags)}")

    def scalar(tag: int) -> int:
        typ, value = tags[tag]
        if typ not in (3, 4) or len(value) != 1:  # type: ignore[arg-type]
            fail(f"tag {tag} is not a scalar SHORT/LONG")
        return int(value[0])  # type: ignore[index]

    def text(tag: int) -> str:
        typ, value = tags[tag]
        if typ != 2:
            fail(f"tag {tag} is not ASCII")
        return str(value)

    width = scalar(256)
    height = scalar(257)
    height_range = height_range or HEIGHT_RANGE
    if width != WIDTH:
        fail(f"ImageWidth {width} != {WIDTH}")
    if not (height_range[0] <= height <= height_range[1]):
        fail(f"ImageLength {height} outside {height_range}")
    expected = {254: 0, 258: 16, 259: 1, 262: 1, 274: 1, 277: 1, 278: 1, 284: 1, 296: 2}
    for tag, value in expected.items():
        if scalar(tag) != value:
            fail(f"tag {tag} = {scalar(tag)}, expected {value}")
    for tag in (282, 283):
        typ, value = tags[tag]
        if typ != 5 or tuple(value) != DPI:  # type: ignore[arg-type]
            fail(f"tag {tag} resolution {value} != {DPI}")
    off_typ, offsets = tags[273]
    cnt_typ, counts = tags[279]
    if off_typ != 4 or cnt_typ not in (3, 4):
        fail("StripOffsets/StripByteCounts have unexpected types")
    if len(offsets) != height or len(counts) != height:  # type: ignore[arg-type]
        fail("strip count != ImageLength (RowsPerStrip 1)")
    if any(c != STRIP_BYTES for c in counts):  # type: ignore[union-attr]
        fail(f"a StripByteCount differs from {STRIP_BYTES}")
    make = text(271)
    model = text(272)
    software = text(305)
    stamp = text(306)
    copyright_text = text(33432)
    if make != MAKE:
        fail(f"Make {make!r} != {MAKE!r}")
    if not model.startswith(MODEL_PREFIX) or MODEL_SERIAL not in model:
        fail(f"Model {model!r} is not the Express {MODEL_SERIAL} scanner")
    if not software.startswith(SOFTWARE_PREFIX):
        fail(f"Software {software!r} is not ScanArray Express")
    if not DATETIME_RE.match(stamp):
        fail(f"DateTime {stamp!r} malformed")
    if copyright_text != COPYRIGHT:
        fail(f"Copyright tag {copyright_text!r} differs from the scanner-software boilerplate")
    desc = parse_description(text(270))
    if desc.get("FluorName") not in FLUOR_BY_DYE.values():
        fail(f"FluorName {desc.get('FluorName')!r} is not Cyanine 3/5")
    if desc.get("Resolution") != RESOLUTION_UM:
        fail(f"Resolution {desc.get('Resolution')!r} != {RESOLUTION_UM} um")
    if desc.get("ProtocolName") != PROTOCOL_NAME:
        fail(f"ProtocolName {desc.get('ProtocolName')!r} != {PROTOCOL_NAME!r}")
    if desc.get("LaserPower") != LASER_POWER:
        fail(f"LaserPower {desc.get('LaserPower')!r} != {LASER_POWER}")
    if not desc.get("PMTGain", "").isdigit():
        fail("PMTGain missing or non-numeric")
    # All metadata (IFD, values, strip tables) must precede the pixel strips.
    ordered = sorted(offsets)  # type: ignore[arg-type]
    if ordered[0] < meta_end:
        fail("pixel strips overlap TIFF metadata")
    if any(b - a != STRIP_BYTES for a, b in zip(ordered, ordered[1:])):
        fail("strips are not a gap-free, non-overlapping tiling of the pixel area")
    if full and ordered[-1] + STRIP_BYTES != len(data):
        fail(f"file size {len(data)} != end of last strip {ordered[-1] + STRIP_BYTES}")
    return {
        "width": width,
        "height": height,
        "strip_offsets": list(offsets),  # type: ignore[arg-type]
        "pixel_offset": ordered[0],
        "make": make,
        "model": model,
        "software": software,
        "datetime": stamp,
        "copyright": copyright_text,
        "artist": text(315),
        "host_computer": text(316),
        "fluor_name": desc["FluorName"],
        "pmt_gain": int(desc["PMTGain"]),
        "laser_power": int(desc["LaserPower"]),
        "excitation_nm": desc.get("Excitation", ""),
        "emission_nm": desc.get("Emission", ""),
        "protocol_name": desc["ProtocolName"],
    }


def extract_raster(data: bytes, info: dict) -> bytes:
    """Concatenate the one-row strips in StripOffsets order (TIFF row order)."""
    return b"".join(data[o:o + STRIP_BYTES] for o in info["strip_offsets"])


# --------------------------------------------------------------------------
# Verify-side reader: minimal, streams the gzip file and reads only the tags
# needed to locate pixels; written separately from parse_tiff on purpose.
# --------------------------------------------------------------------------

def stream_rows(path: Path, prefix_bytes: int = 262_144):
    """Yield (height, width) then each 4400-byte row, reading the gzip file
    sequentially. Strip offsets must be ascending for the streaming path;
    otherwise the whole file is decompressed and sliced."""
    with gzip.open(path, "rb") as fh:
        head = fh.read(prefix_bytes)
        if head[:4] != b"II*\x00":
            raise FormatError("verify reader: bad TIFF signature")
        ifd = int.from_bytes(head[4:8], "little")
        n = int.from_bytes(head[ifd:ifd + 2], "little")
        found: dict[int, tuple[int, int, int]] = {}
        for i in range(n):
            e = ifd + 2 + 12 * i
            tag = int.from_bytes(head[e:e + 2], "little")
            typ = int.from_bytes(head[e + 2:e + 4], "little")
            cnt = int.from_bytes(head[e + 4:e + 8], "little")
            val = int.from_bytes(head[e + 8:e + 12], "little")
            if typ == 3 and cnt == 1:
                val &= 0xFFFF
            found[tag] = (typ, cnt, val)
        if int.from_bytes(head[ifd + 2 + 12 * n:ifd + 6 + 12 * n], "little") != 0:
            raise FormatError("verify reader: multi-page TIFF")
        width = found[256][2]
        height = found[257][2]
        if found[258][2] != 16 or found[259][2] != 1 or found[277][2] != 1:
            raise FormatError("verify reader: not uncompressed single-sample 16-bit")
        if found[278][2] != 1:
            raise FormatError("verify reader: RowsPerStrip != 1")
        typ, cnt, ptr = found[273]
        if typ != 4 or cnt != height or ptr + 4 * cnt > len(head):
            raise FormatError("verify reader: StripOffsets table not in prefix")
        offsets = [int.from_bytes(head[ptr + 4 * i:ptr + 4 * i + 4], "little") for i in range(cnt)]
        typ, cnt, ptr = found[279]
        size = 4 if typ == 4 else 2
        counts = [int.from_bytes(head[ptr + size * i:ptr + size * (i + 1)], "little") for i in range(cnt)]
        row_bytes = width * 2
        if any(c != row_bytes for c in counts):
            raise FormatError("verify reader: strip byte count != row bytes")
        yield height, width
        if all(b > a for a, b in zip(offsets, offsets[1:])):
            buffer = head
            base = 0  # file offset of buffer[0]
            for off in offsets:
                while off + row_bytes > base + len(buffer):
                    more = fh.read(1 << 20)
                    if not more:
                        raise FormatError("verify reader: truncated pixel data")
                    drop = max(0, off - base)
                    buffer = buffer[drop:] + more
                    base += drop
                start = off - base
                yield buffer[start:start + row_bytes]
            if base + len(buffer) > offsets[-1] + row_bytes or fh.read(1):
                raise FormatError("verify reader: trailing bytes after last strip")
        else:
            whole = head + fh.read()
            if len(whole) != max(offsets) + row_bytes:
                raise FormatError("verify reader: file does not end at the last strip")
            for off in offsets:
                row = whole[off:off + row_bytes]
                if len(row) != row_bytes:
                    raise FormatError("verify reader: strip beyond EOF")
                yield row


# --------------------------------------------------------------------------
# Statistics and degeneracy policy (shared thresholds, computed per raster).
# --------------------------------------------------------------------------

def raster_stats(raster: bytes, width: int) -> dict:
    values = array.array("H")
    values.frombytes(raster)
    if sys.byteorder == "big":
        values.byteswap()
    hist = collections.Counter(values)
    total = len(values)
    keys = sorted(hist)
    quantiles = {}
    targets = {"p01": 0.01, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p99": 0.99}
    running = 0
    pending = sorted(targets.items(), key=lambda kv: kv[1])
    for key in keys:
        running += hist[key]
        while pending and running >= pending[0][1] * total:
            quantiles[pending[0][0]] = key
            pending.pop(0)
    row_bytes = width * 2
    constant_rows = 0
    for start in range(0, len(raster), row_bytes):
        row = raster[start:start + row_bytes]
        if row == row[:2] * width:
            constant_rows += 1
    return {
        "min": keys[0],
        "max": keys[-1],
        "mean": round(sum(k * c for k, c in hist.items()) / total, 6),
        "distinct_values": len(keys),
        "zero_count": hist.get(0, 0),
        "saturated_count": hist.get(SATURATED, 0),
        "constant_rows": constant_rows,
        **quantiles,
    }


def degeneracy_problems(stats: dict, value_count: int, height: int) -> list[str]:
    problems = []
    if stats["max"] <= stats["min"]:
        problems.append("constant raster")
    if stats["distinct_values"] < MIN_DISTINCT:
        problems.append(f"only {stats['distinct_values']} distinct values (< {MIN_DISTINCT})")
    if stats["zero_count"] > MAX_ZERO_FRACTION * value_count:
        problems.append(f"zero fraction {stats['zero_count'] / value_count:.4f} > {MAX_ZERO_FRACTION}")
    if stats["saturated_count"] > MAX_SATURATED_FRACTION * value_count:
        problems.append(f"saturated fraction {stats['saturated_count'] / value_count:.4f} > {MAX_SATURATED_FRACTION}")
    if stats["constant_rows"] > MAX_CONSTANT_ROW_FRACTION * height:
        problems.append(f"{stats['constant_rows']} constant rows (> {MAX_CONSTANT_ROW_FRACTION:.0%} of {height})")
    return problems


# --------------------------------------------------------------------------
# Sources, paths, helpers
# --------------------------------------------------------------------------

def read_sources(recipe_dir: Path) -> list[dict]:
    path = recipe_dir / "sources.tsv"
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames != SOURCE_COLUMNS:
            fail(f"sources.tsv columns {reader.fieldnames} != {SOURCE_COLUMNS}")
        rows = list(reader)
    if len(rows) != EXPECTED_FILES:
        fail(f"sources.tsv has {len(rows)} rows, expected {EXPECTED_FILES}")
    seen = set()
    for row in rows:
        match = FILENAME_RE.match(row["filename"])
        if not match or match.group(1) != row["gsm"] or match.group(3) != row["dye"]:
            fail(f"sources.tsv row inconsistent with filename: {row['filename']}")
        if row["filename"] in seen:
            fail(f"duplicate source {row['filename']}")
        seen.add(row["filename"])
        if row["sha256"] == "-":  # placeholder until pinned after the first download
            row["sha256"] = ""
        if row["sha256"] and not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            fail(f"sources.tsv sha256 for {row['filename']} is malformed")
    if sum(int(r["size_bytes"]) for r in rows) != EXPECTED_DOWNLOAD_BYTES:
        fail("sources.tsv byte total differs from EXPECTED_DOWNLOAD_BYTES")
    if sum(int(r["height"]) * STRIP_BYTES for r in rows) != EXPECTED_PRIMARY_BYTES:
        fail("sources.tsv heights do not sum to EXPECTED_PRIMARY_BYTES")
    order = [(r["gsm"], r["dye"]) for r in rows]
    if order != sorted(order):
        fail("sources.tsv rows are not in (GSM, dye) order")
    by_gsm = collections.defaultdict(set)
    for r in rows:
        by_gsm[r["gsm"]].add(r["dye"])
    if any(dyes != {"Cy3", "Cy5"} for dyes in by_gsm.values()):
        fail("every selected GSM must contribute exactly one Cy3 and one Cy5 scan")
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sample_name(row: dict) -> str:
    return f"{row['gsm']}_hyb{int(row['hyb']):02d}_{row['dye'].lower()}.bin"


def load_source(path: Path, row: dict) -> tuple[bytes, dict]:
    """Read one pinned .tif.gz, check pins, decompress, parse, cross-check.
    The returned info carries the source file's sha256 as 'source_sha256'."""
    if not path.is_file():
        fail(f"missing source file {path}")
    raw = path.read_bytes()
    if len(raw) != int(row["size_bytes"]):
        fail(f"{row['filename']}: size {len(raw)} != pinned {row['size_bytes']}")
    crc, isize = struct.unpack("<II", raw[-8:])
    if f"{crc:08x}" != row["gzip_crc32"] or isize != int(row["tiff_bytes"]):
        fail(f"{row['filename']}: gzip trailer CRC32/ISIZE differ from pins")
    digest = hashlib.sha256(raw).hexdigest()
    if row["sha256"] and digest != row["sha256"]:
        fail(f"{row['filename']}: sha256 {digest} != pinned {row['sha256']}")
    data = gzip.decompress(raw)
    if len(data) != int(row["tiff_bytes"]) or f"{zlib.crc32(data):08x}" != row["gzip_crc32"]:
        fail(f"{row['filename']}: decompressed TIFF size/CRC mismatch")
    info = parse_tiff(data)
    if info["height"] != int(row["height"]):
        fail(f"{row['filename']}: height {info['height']} != pinned {row['height']}")
    if info["datetime"] != row["scan_datetime"]:
        fail(f"{row['filename']}: DateTime {info['datetime']!r} != pinned {row['scan_datetime']!r}")
    if info["fluor_name"] != FLUOR_BY_DYE[row["dye"]]:
        fail(f"{row['filename']}: FluorName {info['fluor_name']!r} does not match dye {row['dye']}")
    info["source_sha256"] = digest
    return data, info


def data_paths(data_dir: Path) -> dict[str, Path]:
    return {
        "downloads": data_dir / "downloads" / DATASET_ID / "tiff",
        "samples": data_dir / "samples" / DATASET_ID,
        "index": data_dir / "index" / DATASET_ID,
        "filtered": data_dir / "filtered" / DATASET_ID,
    }


def manifest_series(recipe_dir: Path) -> dict[str, dict]:
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    return {s["id"]: s for s in manifest.get("series", [])}


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------

def cmd_probe_header(args: argparse.Namespace) -> int:
    raw = Path(args.file).read_bytes()
    data = zlib.decompressobj(31).decompress(raw)
    info = parse_tiff(data, full=False)
    print("\t".join(str(info[k]) for k in ("height", "datetime", "fluor_name", "pmt_gain", "laser_power", "pixel_offset")))
    return 0


def cmd_check_file(args: argparse.Namespace) -> int:
    recipe_dir = Path(args.sources).resolve().parent
    rows = {r["filename"]: r for r in read_sources(recipe_dir)}
    name = Path(args.file).name
    if name.endswith(".part"):
        name = name[: -len(".part")]
    row = rows.get(name)
    if row is None:
        print(f"check-file: {name} is not a pinned source", file=sys.stderr)
        return 1
    try:
        data, info = load_source(Path(args.file), row)
        extract_raster(data, info)
    except (FormatError, OSError, EOFError, zlib.error, struct.error) as exc:
        print(f"check-file: {name}: {exc}", file=sys.stderr)
        return 1
    print(f"check-file ok {name} height={info['height']} fluor={info['fluor_name']} pmt={info['pmt_gain']}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    recipe_dir = Path(args.recipe_dir)
    data_dir = Path(args.data_dir)
    paths = data_paths(data_dir)
    rows = read_sources(recipe_dir)
    if not all(r["sha256"] for r in rows):
        print("build: note: some sources.tsv sha256 pins are empty; size, gzip CRC32/ISIZE and layout are still enforced")
    for key in ("samples", "index", "filtered"):
        if paths[key].exists():
            shutil.rmtree(paths[key])
        paths[key].mkdir(parents=True)
    index_rows = []
    hashes: dict[str, str] = {}
    per_series = collections.Counter()
    per_series_bytes = collections.Counter()
    for row in rows:
        data, info = load_source(paths["downloads"] / row["filename"], row)
        raster = extract_raster(data, info)
        height = info["height"]
        value_count = height * WIDTH
        if len(raster) != value_count * BYTES_PER_PIXEL:
            fail(f"{row['filename']}: raster size mismatch")
        stats = raster_stats(raster, WIDTH)
        problems = degeneracy_problems(stats, value_count, height)
        if problems:
            fail(f"{row['filename']}: degenerate raster: {'; '.join(problems)}")
        digest = hashlib.sha256(raster).hexdigest()
        if digest in hashes:
            fail(f"{row['filename']}: raster duplicates {hashes[digest]}")
        hashes[digest] = row["filename"]
        series_id = SERIES_BY_DYE[row["dye"]]
        out_dir = paths["samples"] / series_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / sample_name(row)
        tmp = out.with_suffix(".bin.tmp")
        tmp.write_bytes(raster)
        tmp.replace(out)
        per_series[series_id] += 1
        per_series_bytes[series_id] += len(raster)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "sample_path": str(out.relative_to(data_dir)),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(raster),
            "value_count": value_count,
            "sample_shape": [height, WIDTH],
            "sample_axes": ["scan_row", "scan_column"],
            "gsm": row["gsm"],
            "hybridization": int(row["hyb"]),
            "dye": row["dye"],
            "fluor_name": info["fluor_name"],
            "pmt_gain": info["pmt_gain"],
            "laser_power_percent": info["laser_power"],
            "scan_datetime": info["datetime"],
            "source_file": row["filename"],
            "source_url": row["url"],
            "source_sha256": info["source_sha256"],
            "source_sha256_pinned": bool(row["sha256"]),
            "sha256": digest,
            **stats,
        })
        print(f"sample {out.relative_to(data_dir)} shape={height}x{WIDTH} min={stats['min']} "
              f"p50={stats['p50']} p99={stats['p99']} max={stats['max']} distinct={stats['distinct_values']} "
              f"zeros={stats['zero_count']} saturated={stats['saturated_count']}", flush=True)
    series = manifest_series(recipe_dir)
    for series_id in SERIES_BY_DYE.values():
        declared = series.get(series_id, {})
        if declared.get("sample_count") != per_series[series_id] or declared.get("total_size_bytes") != per_series_bytes[series_id]:
            fail(f"manifest totals for {series_id} ({declared.get('sample_count')}, {declared.get('total_size_bytes')}) "
                 f"!= realized ({per_series[series_id]}, {per_series_bytes[series_id]})")
    total_bytes = sum(per_series_bytes.values())
    if total_bytes != EXPECTED_PRIMARY_BYTES:
        fail(f"primary bytes {total_bytes} != expected {EXPECTED_PRIMARY_BYTES}")
    index_path = paths["index"] / "samples.jsonl"
    with index_path.open("w", encoding="utf-8") as fh:
        for item in index_rows:
            fh.write(json.dumps(item, sort_keys=False) + "\n")
    aggregate = hashlib.sha256("".join(r["sha256"] for r in index_rows).encode()).hexdigest()
    summary = {
        "dataset_id": DATASET_ID,
        "samples": len(index_rows),
        "samples_per_series": dict(per_series),
        "bytes_per_series": dict(per_series_bytes),
        "primary_values": total_bytes // 2,
        "primary_bytes": total_bytes,
        "height_range": [min(r["sample_shape"][0] for r in index_rows), max(r["sample_shape"][0] for r in index_rows)],
        "zero_values": sum(r["zero_count"] for r in index_rows),
        "saturated_values": sum(r["saturated_count"] for r in index_rows),
        "aggregate_sha256_of_sample_sha256s": aggregate,
    }
    (paths["filtered"] / "ingest_stats.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    recipe_dir = Path(args.recipe_dir)
    data_dir = Path(args.data_dir)
    paths = data_paths(data_dir)
    rows = read_sources(recipe_dir)
    index_path = paths["index"] / "samples.jsonl"
    if not index_path.is_file():
        fail("missing sample index")
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != len(rows):
        fail(f"index has {len(index)} rows, sources.tsv has {len(rows)}")
    by_source = {r["source_file"]: r for r in index}
    if set(by_source) != {r["filename"] for r in rows}:
        fail("index source files differ from sources.tsv")
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                "element_size_bytes", "sample_size_bytes", "value_count"]
    hashes = set()
    totals = collections.Counter()
    total_bytes = collections.Counter()
    expected_files = set()
    for row in rows:
        item = by_source[row["filename"]]
        missing = [k for k in required if k not in item]
        if missing:
            fail(f"index row for {row['filename']} lacks {missing}")
        series_id = SERIES_BY_DYE[row["dye"]]
        expected_path = f"samples/{DATASET_ID}/{series_id}/{sample_name(row)}"
        if (item["dataset_id"], item["series_id"], item["sample_path"]) != (DATASET_ID, series_id, expected_path):
            fail(f"index identity mismatch for {row['filename']}")
        if (item["numeric_kind"], item["bit_width"], item["endianness"], item["element_size_bytes"]) != ("uint", 16, "little", 2):
            fail(f"index dtype mismatch for {row['filename']}")
        height = int(row["height"])
        value_count = height * WIDTH
        sample = data_dir / item["sample_path"]
        expected_files.add(sample)
        if item["value_count"] != value_count or item["sample_size_bytes"] != value_count * 2:
            fail(f"index counts mismatch for {row['filename']}")
        if not sample.is_file() or sample.stat().st_size != value_count * 2:
            fail(f"sample file missing or wrong size: {sample}")
        source = paths["downloads"] / row["filename"]
        if source.stat().st_size != int(row["size_bytes"]):
            fail(f"source size changed: {row['filename']}")
        source_digest = sha256_file(source)
        if source_digest != (row["sha256"] or item.get("source_sha256")):
            fail(f"source sha256 differs from pin/index: {row['filename']}")
        # Independent re-derivation: stream the gzip TIFF with the separate
        # reader and compare row by row against the emitted sample.
        reader = stream_rows(source)
        h, w = next(reader)
        if (h, w) != (height, WIDTH):
            fail(f"verify reader shape {h}x{w} != pinned {height}x{WIDTH}")
        rows_seen = 0
        with sample.open("rb") as fh:
            for src_row in reader:
                if fh.read(len(src_row)) != src_row:
                    fail(f"{sample}: row {rows_seen} differs from source strip")
                rows_seen += 1
            if fh.read(1):
                fail(f"{sample}: trailing bytes beyond source raster")
        if rows_seen != height:
            fail(f"{sample}: {rows_seen} rows re-derived, expected {height}")
        raster = sample.read_bytes()
        digest = hashlib.sha256(raster).hexdigest()
        if digest != item.get("sha256"):
            fail(f"{sample}: sha256 differs from index")
        if digest in hashes:
            fail(f"{sample}: duplicate raster")
        hashes.add(digest)
        stats = raster_stats(raster, WIDTH)
        for key, value in stats.items():
            if item.get(key) != value:
                fail(f"{sample}: index {key}={item.get(key)} but recomputed {value}")
        problems = degeneracy_problems(stats, value_count, height)
        if problems:
            fail(f"{sample}: degenerate raster: {'; '.join(problems)}")
        if item.get("sample_shape") != [height, WIDTH] or item.get("dye") != row["dye"] or item.get("gsm") != row["gsm"]:
            fail(f"{sample}: index provenance fields mismatch")
        totals[series_id] += 1
        total_bytes[series_id] += value_count * 2
        print(f"verified {item['sample_path']} rows={rows_seen} distinct={stats['distinct_values']} max={stats['max']}", flush=True)
    actual_files = {p for p in paths["samples"].rglob("*") if p.is_file()}
    if actual_files != expected_files:
        fail(f"stray or missing files under samples/: {sorted(map(str, actual_files ^ expected_files))[:5]}")
    series = manifest_series(recipe_dir)
    for series_id in SERIES_BY_DYE.values():
        declared = series.get(series_id)
        if declared is None or declared.get("role") != "primary":
            fail(f"manifest lacks primary series {series_id}")
        if declared.get("sample_count") != totals[series_id] or declared.get("total_size_bytes") != total_bytes[series_id]:
            fail(f"manifest totals for {series_id} differ from realized output")
        if (declared.get("numeric_kind"), declared.get("bit_width"), declared.get("endianness")) != ("uint", 16, "little"):
            fail(f"manifest dtype for {series_id} is not uint16 little-endian")
    if sum(total_bytes.values()) != EXPECTED_PRIMARY_BYTES:
        fail("realized primary bytes differ from EXPECTED_PRIMARY_BYTES")
    print(f"verify ok samples={len(index)} primary_bytes={sum(total_bytes.values())} per_series={dict(totals)}")
    return 0


# --------------------------------------------------------------------------
# Self-test on synthetic ScanArray-layout TIFFs
# --------------------------------------------------------------------------

def make_synthetic_tiff(pixels: bytes, height: int, *, fluor: str = "Cyanine 3", shuffle: bool = False,
                        overrides: dict | None = None, next_ifd: int = 0, trailing: bytes = b"") -> bytes:
    """Write a TIFF with the same 23-tag layout as ScanArray Express 2.1."""
    overrides = overrides or {}
    desc = (f"ProtocolName={PROTOCOL_NAME}#Resolution={RESOLUTION_UM}#FluorName={fluor}#"
            f"LaserWavelength543#PMTGain=70#LaserPower={LASER_POWER}#").encode() + b"\0"
    ascii_tags = {
        270: desc,
        271: overrides.get(271, MAKE).encode() + b"\0",
        272: overrides.get(272, "Express\t430723\tEXP430723").encode() + b"\0",
        305: overrides.get(305, "ScanArray Express, Microarray Analysis System 2.1.0.0").encode() + b"\0",
        306: b"2006:08:01 16:59:49\0",
        315: b"Synthetic\0",
        316: b"Self test\0",
        33432: overrides.get(33432, COPYRIGHT).encode() + b"\0",
    }
    count = len(EXPECTED_TAGS)
    ifd_offset = 8
    cursor = ifd_offset + 2 + 12 * count + 4
    blobs: dict[int, tuple[int, bytes]] = {}
    for tag in sorted(ascii_tags):
        blobs[tag] = (cursor, ascii_tags[tag])
        cursor += len(ascii_tags[tag])
    for tag in (282, 283):
        blobs[tag] = (cursor, struct.pack("<II", *DPI))
        cursor += 8
    offsets_pos = cursor
    cursor += 4 * height
    counts_pos = cursor
    cursor += 4 * height
    pixel_base = cursor
    row_bytes = STRIP_BYTES
    order = list(range(height))
    if shuffle:
        order = order[1::2] + order[0::2]  # deterministic non-monotone placement
    offsets = [0] * height
    for slot, row in enumerate(order):
        offsets[row] = pixel_base + slot * row_bytes
    counts = [overrides.get("strip_bytes", row_bytes)] * height
    scalars = {254: (4, 0), 256: (4, WIDTH), 257: (4, height), 258: (3, overrides.get(258, 16)),
               259: (3, overrides.get(259, 1)), 262: (3, 1), 274: (3, 1), 277: (3, 1), 278: (4, 1),
               284: (3, 1), 296: (3, 2)}
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_offset))
    out += struct.pack("<H", count)
    for tag in EXPECTED_TAGS:
        if tag in scalars:
            typ, value = scalars[tag]
            out += struct.pack("<HHI", tag, typ, 1) + (struct.pack("<H", value) + b"\0\0" if typ == 3 else struct.pack("<I", value))
        elif tag in ascii_tags:
            pos, blob = blobs[tag]
            out += struct.pack("<HHII", tag, 2, len(blob), pos)
        elif tag in (282, 283):
            out += struct.pack("<HHII", tag, 5, 1, blobs[tag][0])
        elif tag == 273:
            out += struct.pack("<HHII", tag, 4, height, offsets_pos)
        elif tag == 279:
            out += struct.pack("<HHII", tag, 4, height, counts_pos)
    out += struct.pack("<I", next_ifd)
    for tag in sorted(blobs, key=lambda t: blobs[t][0]):
        assert len(out) == blobs[tag][0]
        out += blobs[tag][1]
    out += struct.pack("<%dI" % height, *offsets)
    out += struct.pack("<%dI" % height, *counts)
    assert len(out) == pixel_base
    body = bytearray(height * row_bytes)
    for row in range(height):
        start = offsets[row] - pixel_base
        body[start:start + row_bytes] = pixels[row * row_bytes:(row + 1) * row_bytes]
    return bytes(out + body) + trailing


def cmd_selftest(_args: argparse.Namespace) -> int:
    import tempfile
    height = 7
    rng_bytes = bytearray()
    state = 12345
    for i in range(height * WIDTH):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        value = (state >> 8) & 0xFFFF
        if i % 997 == 0:
            value = SATURATED
        rng_bytes += struct.pack("<H", value)
    pixels = bytes(rng_bytes)
    small = (1, 16)
    checks = 0
    for shuffle in (False, True):
        tiff = make_synthetic_tiff(pixels, height, shuffle=shuffle)
        info = parse_tiff(tiff, height_range=small)
        assert info["height"] == height and info["width"] == WIDTH
        assert extract_raster(tiff, info) == pixels, "build parser raster mismatch"
        header_only = parse_tiff(tiff[: info["pixel_offset"]], full=False, height_range=small)
        assert header_only["height"] == height
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            path = Path(tmp) / "synthetic.tif.gz"
            path.write_bytes(gzip.compress(tiff))
            reader = stream_rows(path, prefix_bytes=5000 if not shuffle else 262_144)
            assert next(reader) == (height, WIDTH)
            assert b"".join(reader) == pixels, "verify reader raster mismatch"
        checks += 1
    # Streaming reader with a prefix that ends right after the strip tables,
    # plus rejection of trailing bytes after the last strip.
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        path = Path(tmp) / "synthetic.tif.gz"
        tiff = make_synthetic_tiff(pixels, height)
        path.write_bytes(gzip.compress(tiff))
        reader = stream_rows(path, prefix_bytes=parse_tiff(tiff, height_range=small)["pixel_offset"])
        next(reader)
        assert b"".join(reader) == pixels
        path.write_bytes(gzip.compress(tiff + b"\0\0"))
        try:
            list(stream_rows(path, prefix_bytes=5000))
        except FormatError:
            pass
        else:
            raise AssertionError("selftest: verify reader accepted trailing bytes")
        checks += 1
    stats = raster_stats(pixels, WIDTH)
    values = array.array("H")
    values.frombytes(pixels)
    assert stats["min"] == min(values) and stats["max"] == max(values)
    assert stats["saturated_count"] == values.count(SATURATED)
    assert stats["distinct_values"] == len(set(values))
    assert stats["constant_rows"] == 0
    flat = struct.pack("<H", 500) * (WIDTH * 3)
    flat_stats = raster_stats(flat, WIDTH)
    assert flat_stats["constant_rows"] == 3 and degeneracy_problems(flat_stats, WIDTH * 3, 3)
    checks += 1
    bad_cases = {
        "bits_per_sample_8": dict(overrides={258: 8}),
        "lzw_compression": dict(overrides={259: 5}),
        "second_ifd": dict(next_ifd=123),
        "wrong_make": dict(overrides={271: "Agilent"}),
        "wrong_model": dict(overrides={272: "GenePix 4000B"}),
        "wrong_software": dict(overrides={305: "GenePix Pro 6.0"}),
        "copyright_changed": dict(overrides={33432: "Copyright (C) 2006 Someone"}),
        "strip_bytes": dict(overrides={"strip_bytes": STRIP_BYTES - 2}),
        "trailing_byte": dict(trailing=b"\0"),
        "wrong_fluor": dict(fluor="Alexa 647"),
    }
    for name, kwargs in bad_cases.items():
        tiff = make_synthetic_tiff(pixels, height, **kwargs)
        try:
            parse_tiff(tiff, height_range=small)
        except (FormatError, struct.error):
            checks += 1
            continue
        raise AssertionError(f"selftest: malformed case {name} was accepted")
    good = make_synthetic_tiff(pixels, height)
    for name, blob in {"truncated": good[:-10], "big_endian": b"MM" + good[2:]}.items():
        try:
            parse_tiff(blob, height_range=small)
        except (FormatError, struct.error):
            checks += 1
            continue
        raise AssertionError(f"selftest: malformed case {name} was accepted")
    try:
        parse_tiff(good)  # default height range rejects a 7-row image
    except FormatError:
        checks += 1
    else:
        raise AssertionError("selftest: height range not enforced")
    assert parse_description("A=1#LaserWavelength543#B=x=y#") == {"A": "1", "B": "x=y"}
    print(f"selftest ok ({checks} checks)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("probe-header")
    p.add_argument("file")
    p = sub.add_parser("check-file")
    p.add_argument("--sources", required=True)
    p.add_argument("--file", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--recipe-dir", required=True)
    args = parser.parse_args()
    handlers = {
        "selftest": cmd_selftest,
        "probe-header": cmd_probe_header,
        "check-file": cmd_check_file,
        "build": cmd_build,
        "verify": cmd_verify,
    }
    try:
        return handlers[args.command](args)
    except FormatError as exc:
        print(f"{args.command}: FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
