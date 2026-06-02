#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="worldclim_tavg_10m"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import zipfile
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

archive_path = download_dir / "wc2.1_10m_tavg.zip"
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
sample_dir = samples_dir / "worldclim_tavg_f32"
if sample_dir.exists():
    shutil.rmtree(sample_dir)
sample_dir.mkdir(parents=True, exist_ok=True)

SELECTED_BANDS = [
    {"tif": "wc2.1_10m_tavg_01.tif", "month": 1, "row_start": 120, "row_count": 8, "output": "wc2_1_10m_tavg_01_rows_0120_0127.bin"},
    {"tif": "wc2.1_10m_tavg_02.tif", "month": 2, "row_start": 660, "row_count": 8, "output": "wc2_1_10m_tavg_02_rows_0660_0667.bin"},
    {"tif": "wc2.1_10m_tavg_03.tif", "month": 3, "row_start": 480, "row_count": 8, "output": "wc2_1_10m_tavg_03_rows_0480_0487.bin"},
    {"tif": "wc2.1_10m_tavg_07.tif", "month": 7, "row_start": 1020, "row_count": 8, "output": "wc2_1_10m_tavg_07_rows_1020_1027.bin"},
    {"tif": "wc2.1_10m_tavg_08.tif", "month": 8, "row_start": 300, "row_count": 8, "output": "wc2_1_10m_tavg_08_rows_0300_0307.bin"},
    {"tif": "wc2.1_10m_tavg_12.tif", "month": 12, "row_start": 840, "row_count": 8, "output": "wc2_1_10m_tavg_12_rows_0840_0847.bin"},
]
NODATA_THRESHOLD = -3e38


def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lzw_decode_tiff(data: bytes) -> bytes:
    bit = 0
    nbits = 9

    def read_code(n: int) -> int:
        nonlocal bit
        code = 0
        for _ in range(n):
            if bit >= len(data) * 8:
                raise RuntimeError("truncated TIFF LZW stream")
            code = (code << 1) | ((data[bit >> 3] >> (7 - (bit & 7))) & 1)
            bit += 1
        return code

    table: list[bytes | None] = [bytes([i]) for i in range(256)] + [None, None]
    next_code = 258
    prev: bytes | None = None
    out = bytearray()
    while bit + nbits <= len(data) * 8:
        code = read_code(nbits)
        if code == 256:
            table = [bytes([i]) for i in range(256)] + [None, None]
            next_code = 258
            nbits = 9
            prev = None
            continue
        if code == 257:
            break
        if code < len(table) and table[code] is not None:
            entry = table[code]
        elif code == next_code and prev is not None:
            entry = prev + prev[:1]
        else:
            raise RuntimeError(f"bad TIFF LZW code {code}, next={next_code}, bits={nbits}")

        out.extend(entry)
        if prev is not None and next_code < 4096:
            table.append(prev + entry[:1])
            next_code += 1
            if next_code == (1 << nbits) - 1 and nbits < 12:
                nbits += 1
        prev = entry
    return bytes(out)


def tiff_values(buf: bytes, endian: str, typ: int, count: int, value_or_offset: int):
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}
    formats = {1: "B", 2: "c", 3: "H", 4: "I", 11: "f", 12: "d"}
    size = sizes[typ] * count
    if size <= 4:
        raw = value_or_offset.to_bytes(4, "little" if endian == "<" else "big")[:size]
    else:
        raw = buf[value_or_offset:value_or_offset + size]
    if typ == 2:
        return raw
    return struct.unpack(endian + formats[typ] * count, raw)


def parse_tiff(buf: bytes) -> dict[str, object]:
    endian = "<" if buf[:2] == b"II" else ">" if buf[:2] == b"MM" else None
    if endian is None:
        raise RuntimeError("missing TIFF byte-order marker")
    magic = struct.unpack(endian + "H", buf[2:4])[0]
    if magic != 42:
        raise RuntimeError(f"unexpected TIFF magic {magic}")
    ifd = struct.unpack(endian + "I", buf[4:8])[0]
    count = struct.unpack(endian + "H", buf[ifd:ifd + 2])[0]
    tags: dict[int, tuple[int, int, int]] = {}
    for i in range(count):
        off = ifd + 2 + i * 12
        tag, typ, tag_count, value_or_offset = struct.unpack(endian + "HHII", buf[off:off + 12])
        tags[tag] = (typ, tag_count, value_or_offset)

    required = [256, 257, 258, 259, 273, 277, 278, 279, 317, 339, 42113]
    missing = [tag for tag in required if tag not in tags]
    if missing:
        raise RuntimeError(f"missing required TIFF tags: {missing}")

    meta = {
        "endian": endian,
        "width": tiff_values(buf, endian, *tags[256])[0],
        "height": tiff_values(buf, endian, *tags[257])[0],
        "bits_per_sample": tiff_values(buf, endian, *tags[258])[0],
        "compression": tiff_values(buf, endian, *tags[259])[0],
        "strip_offsets": tiff_values(buf, endian, *tags[273]),
        "samples_per_pixel": tiff_values(buf, endian, *tags[277])[0],
        "rows_per_strip": tiff_values(buf, endian, *tags[278])[0],
        "strip_byte_counts": tiff_values(buf, endian, *tags[279]),
        "predictor": tiff_values(buf, endian, *tags[317])[0],
        "sample_format": tiff_values(buf, endian, *tags[339])[0],
        "nodata": tiff_values(buf, endian, *tags[42113]).decode("ascii").rstrip("\x00"),
    }
    if (
        meta["width"] != 2160
        or meta["height"] != 1080
        or meta["bits_per_sample"] != 32
        or meta["compression"] != 5
        or meta["samples_per_pixel"] != 1
        or meta["rows_per_strip"] != 1
        or meta["predictor"] != 1
        or meta["sample_format"] != 3
    ):
        raise RuntimeError(f"unexpected WorldClim GeoTIFF layout: {meta}")
    return meta


def decode_row(buf: bytes, meta: dict[str, object], row: int) -> bytes:
    width = int(meta["width"])
    offsets = meta["strip_offsets"]
    counts = meta["strip_byte_counts"]
    offset = offsets[row]
    byte_count = counts[row]
    decoded = lzw_decode_tiff(buf[offset:offset + byte_count])
    if len(decoded) != width * 4:
        raise RuntimeError(f"unexpected decoded row length {len(decoded)}; expected {width * 4}")
    if meta["endian"] == "<":
        return decoded
    values = struct.unpack(">" + "f" * width, decoded)
    return struct.pack("<" + "f" * width, *values)


sample_rows = []
stats_samples = []
total_values = 0
total_bytes = 0
total_nodata = 0
global_min = None
global_max = None
tiff_metadata = None

with zipfile.ZipFile(archive_path) as zf:
    names = set(zf.namelist())
    for selection in SELECTED_BANDS:
        tif_name = selection["tif"]
        if tif_name not in names:
            raise RuntimeError(f"missing {tif_name} in {archive_path}")
        tif_data = zf.read(tif_name)
        meta = parse_tiff(tif_data)
        if tiff_metadata is None:
            tiff_metadata = {
                "width": meta["width"],
                "height": meta["height"],
                "bits_per_sample": meta["bits_per_sample"],
                "sample_format": "IEEE float",
                "compression": "TIFF LZW",
                "rows_per_strip": meta["rows_per_strip"],
                "predictor": meta["predictor"],
                "nodata": meta["nodata"],
            }
        row_start = int(selection["row_start"])
        row_count = int(selection["row_count"])
        row_end = row_start + row_count - 1
        if row_start < 0 or row_start + row_count > int(meta["height"]):
            raise RuntimeError(f"row selection out of range for {tif_name}")

        out = bytearray()
        for row in range(row_start, row_start + row_count):
            out.extend(decode_row(tif_data, meta, row))

        values = struct.unpack("<" + "f" * (len(out) // 4), out)
        finite = [value for value in values if math.isfinite(value) and value > NODATA_THRESHOLD]
        nodata_count = len(values) - len(finite)
        if not finite:
            raise RuntimeError(f"{tif_name} selected band has no finite climate values")

        output_path = sample_dir / selection["output"]
        output_path.write_bytes(bytes(out))
        output_sha256 = sha256_file(output_path)
        file_min = min(finite)
        file_max = max(finite)
        global_min = file_min if global_min is None else min(global_min, file_min)
        global_max = file_max if global_max is None else max(global_max, file_max)
        total_values += len(values)
        total_bytes += output_path.stat().st_size
        total_nodata += nodata_count

        sample_rows.append({
            "dataset_id": "worldclim_tavg_10m",
            "series_id": "worldclim_tavg_f32",
            "sample_path": rel_data(output_path),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": output_path.stat().st_size,
            "value_count": len(values),
        })
        stats_samples.append({
            "file": rel_data(output_path),
            "source_tif": tif_name,
            "source_tif_sha256": sha256_bytes(tif_data),
            "month": selection["month"],
            "rows": [row_start, row_end],
            "values": len(values),
            "bytes": output_path.stat().st_size,
            "sha256": output_sha256,
            "finite_values": len(finite),
            "nodata_values": nodata_count,
            "min_tavg_c": file_min,
            "max_tavg_c": file_max,
        })

stats = {
    "dataset_id": "worldclim_tavg_10m",
    "family": "worldclim_tavg_f32",
    "source_archive": rel_data(archive_path),
    "source_archive_bytes": archive_path.stat().st_size,
    "source_archive_sha256": sha256_file(archive_path),
    "source_format": "WorldClim v2.1 GeoTIFF ZIP",
    "source_encoding": "LZW-compressed IEEE-754 float32 GeoTIFF strips",
    "output_encoding": "little-endian IEEE-754 float32",
    "accepted_scope": "six selected 8-row bands from six monthly average-temperature rasters",
    "tiff_metadata": tiff_metadata,
    "sample_count": len(stats_samples),
    "total_values": total_values,
    "total_bytes": total_bytes,
    "finite_values": total_values - total_nodata,
    "nodata_values": total_nodata,
    "min_tavg_c": global_min,
    "max_tavg_c": global_max,
    "samples": stats_samples,
}

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
