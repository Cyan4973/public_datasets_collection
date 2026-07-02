#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_themis_ir_mosaic_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from collections import Counter
from pathlib import Path
from typing import BinaryIO

DATASET_ID = "nasa_pds_themis_ir_mosaic_u8"
SERIES_ID = "themis_ir_mosaic_pixels_u8"
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_PRIMARY_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def tiff_scalar(data: bytes, endian: str, field_type: int, count: int, raw_value: int) -> list[int]:
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4}
    type_codes = {1: "B", 2: "c", 3: "H", 4: "I"}
    size = type_sizes.get(field_type)
    code = type_codes.get(field_type)
    if size is None or code is None:
        raise ValueError(f"unsupported TIFF field type: {field_type}")
    if count * size <= 4:
        value_bytes = struct.pack(endian + "I", raw_value)[: count * size]
    else:
        value_bytes = data[raw_value : raw_value + count * size]
    if code == "c":
        return [0]
    return list(struct.unpack(endian + code * count, value_bytes))


def parse_tiff(path: Path) -> dict:
    with path.open("rb") as fh:
        header = fh.read(1024 * 1024)
    if header[:2] == b"II":
        endian = "<"
        endianness = "little"
    elif header[:2] == b"MM":
        endian = ">"
        endianness = "big"
    else:
        raise ValueError(f"{path.name}: not a TIFF file")
    magic = struct.unpack_from(endian + "H", header, 2)[0]
    if magic != 42:
        raise ValueError(f"{path.name}: unsupported TIFF magic {magic}")
    ifd_offset = struct.unpack_from(endian + "I", header, 4)[0]
    if ifd_offset >= len(header):
        raise ValueError(f"{path.name}: first IFD outside header prefetch")
    entry_count = struct.unpack_from(endian + "H", header, ifd_offset)[0]
    tags: dict[int, tuple[int, int, int]] = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, field_type, count, raw_value = struct.unpack_from(endian + "HHII", header, offset)
        tags[tag] = (field_type, count, raw_value)

    def values(tag: int) -> list[int]:
        if tag not in tags:
            return []
        field_type, count, raw_value = tags[tag]
        return tiff_scalar(header, endian, field_type, count, raw_value)

    width = values(256)[0]
    height = values(257)[0]
    bits = values(258)[0]
    compression = (values(259) or [1])[0]
    samples_per_pixel = (values(277) or [1])[0]
    sample_format = (values(339) or [1])[0]
    strip_offsets = values(273)
    strip_counts = values(279)
    if bits != 8 or compression != 1 or samples_per_pixel != 1 or sample_format != 1:
        raise ValueError(
            f"{path.name}: unsupported TIFF format bits={bits} compression={compression} "
            f"samples_per_pixel={samples_per_pixel} sample_format={sample_format}"
        )
    expected = width * height
    if len(strip_offsets) != len(strip_counts) or sum(strip_counts) != expected:
        raise ValueError(f"{path.name}: invalid strip table expected={expected} strip_bytes={sum(strip_counts)}")
    return {
        "width": width,
        "height": height,
        "value_count": expected,
        "endianness": endianness,
        "strip_offsets": strip_offsets,
        "strip_counts": strip_counts,
    }


def copy_strips(source: Path, out: Path, offsets: list[int], counts: list[int]) -> Counter[int]:
    counts_by_value: Counter[int] = Counter()
    with source.open("rb") as src, out.open("wb") as dst:
        for offset, count in zip(offsets, counts):
            src.seek(offset)
            remaining = count
            while remaining:
                chunk = src.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError(f"{source.name}: truncated strip")
                dst.write(chunk)
                counts_by_value.update(chunk)
                remaining -= len(chunk)
    return counts_by_value


reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

tiffs = sorted(download_dir.glob("*.tif")) + sorted(download_dir.glob("*.tiff"))
if not tiffs:
    raise SystemExit(f"no TIFF downloads found in {download_dir}")

rows = []
records = []
total_bytes = 0
for sample_index, path in enumerate(tiffs, start=1):
    info = parse_tiff(path)
    out = out_dir / f"{sample_index:04d}_{path.stem}.bin"
    histogram = copy_strips(path, out, info["strip_offsets"], info["strip_counts"])
    size = out.stat().st_size
    if size != info["value_count"]:
        raise RuntimeError(f"{path.name}: output size mismatch {size} != {info['value_count']}")
    if len(histogram) <= 1:
        raise RuntimeError(f"{path.name}: constant raster rejected")
    total_bytes += size
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": info["endianness"],
        "element_size_bytes": 1,
        "sample_size_bytes": size,
        "value_count": info["value_count"],
        "sample_format": "raw homogeneous uint8 array copied from TIFF pixel plane",
        "sample_geometry": "2d_raster",
        "sample_rank": 2,
        "sample_shape": [info["height"], info["width"]],
        "sample_axes": ["y", "x"],
        "natural_record_kind": "themis_controlled_ir_mosaic",
        "source_path": path.as_posix(),
        "source_file": path.name,
        "min": min(histogram),
        "max": max(histogram),
    }
    rows.append(row)
    records.append(
        {
            "source_file": path.name,
            "source_bytes": path.stat().st_size,
            "sample_path": row["sample_path"],
            "sample_bytes": size,
            "value_count": info["value_count"],
            "shape": [info["height"], info["width"]],
            "distinct_values": len(histogram),
            "min_value": min(histogram),
            "max_value": max(histogram),
            "most_common_value": histogram.most_common(1)[0][0],
            "most_common_fraction": histogram.most_common(1)[0][1] / size,
        }
    )

sizes = [row["sample_size_bytes"] for row in rows]
if sum(sizes) < MIN_PRIMARY_BYTES or sum(sizes) < MIN_PRIMARY_VALUES:
    raise RuntimeError("primary payload below aggregate floor")
if sorted(sizes)[len(sizes) // 2] < MIN_MEDIAN_VALUES:
    raise RuntimeError("median sample below floor")

stats = {
    "dataset_id": DATASET_ID,
    "record_count": len(records),
    "total_primary_bytes": sum(sizes),
    "total_primary_values": sum(row["value_count"] for row in rows),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built_samples={len(rows)} primary_values={stats['total_primary_values']} "
    f"primary_bytes={stats['total_primary_bytes']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
