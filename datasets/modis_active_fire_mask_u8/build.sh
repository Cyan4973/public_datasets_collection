#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="modis_active_fire_mask_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import struct
import zlib
from collections import Counter
from pathlib import Path

DATASET_ID = "modis_active_fire_mask_u8"
SERIES_ID = "modis_8day_active_fire_mask_u8"
WIDTH = 1200
HEIGHT = 1200
EXPECTED_VALUES = WIDTH * HEIGHT
EXPECTED_SAMPLES = 12
MIN_MINORITY_FRACTION = 0.001
ALLOWED = set(range(10))
FIRE_CLASSES = {7, 8, 9}

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
TYPE_FORMAT = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i"}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
plan_path = download_dir / "download_plan.tsv"
source_dir = download_dir / "rasters"
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def tiff_values(data: bytes, endian: str, field_type: int, count: int, raw: bytes) -> list[int]:
    size = TYPE_SIZE.get(field_type)
    if size is None:
        raise ValueError(f"unsupported TIFF field type {field_type}")
    byte_count = size * count
    if byte_count <= 4:
        value_data = raw[:byte_count]
    else:
        offset = struct.unpack(endian + "I", raw)[0]
        if offset + byte_count > len(data):
            raise ValueError(f"TIFF value table outside file: offset={offset} bytes={byte_count}")
        value_data = data[offset:offset + byte_count]
    fmt = TYPE_FORMAT.get(field_type)
    if fmt is None:
        return []
    return list(struct.unpack(endian + fmt * count, value_data))


def parse_ifds(data: bytes) -> tuple[str, list[dict[int, list[int]]]]:
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError("not a TIFF file")
    if struct.unpack_from(endian + "H", data, 2)[0] != 42:
        raise ValueError("only classic TIFF is supported")
    offset = struct.unpack_from(endian + "I", data, 4)[0]
    ifds: list[dict[int, list[int]]] = []
    seen: set[int] = set()
    while offset:
        if offset in seen or offset + 2 > len(data):
            raise ValueError(f"invalid TIFF IFD chain at offset {offset}")
        seen.add(offset)
        entry_count = struct.unpack_from(endian + "H", data, offset)[0]
        if offset + 2 + entry_count * 12 + 4 > len(data):
            raise ValueError(f"truncated TIFF IFD at offset {offset}")
        tags: dict[int, list[int]] = {}
        for index in range(entry_count):
            entry = offset + 2 + index * 12
            tag, field_type, count = struct.unpack_from(endian + "HHI", data, entry)
            tags[tag] = tiff_values(data, endian, field_type, count, data[entry + 8:entry + 12])
        ifds.append(tags)
        offset = struct.unpack_from(endian + "I", data, offset + 2 + entry_count * 12)[0]
    return endian, ifds


def decompress_tile(payload: bytes) -> bytearray:
    try:
        return bytearray(zlib.decompress(payload))
    except zlib.error:
        return bytearray(zlib.decompress(payload, -15))


def decode_primary_grid(path: Path) -> tuple[bytes, dict[str, int]]:
    data = path.read_bytes()
    endian, ifds = parse_ifds(data)
    if len(ifds) != 3:
        raise ValueError(f"{path.name}: expected primary IFD plus two overviews, found {len(ifds)} IFDs")
    tags = ifds[0]

    def scalar(tag: int, default: int | None = None) -> int:
        values = tags.get(tag)
        if values:
            return int(values[0])
        if default is not None:
            return default
        raise ValueError(f"{path.name}: missing required TIFF tag {tag}")

    width = scalar(256)
    height = scalar(257)
    bits = scalar(258)
    compression = scalar(259, 1)
    photometric = scalar(262)
    samples_per_pixel = scalar(277, 1)
    planar_configuration = scalar(284, 1)
    predictor = scalar(317, 1)
    tile_width = scalar(322)
    tile_height = scalar(323)
    sample_format = scalar(339, 1)
    offsets = tags.get(324, [])
    byte_counts = tags.get(325, [])

    expected = {
        "width": WIDTH,
        "height": HEIGHT,
        "bits": 8,
        "compression": 8,
        "photometric": 1,
        "samples_per_pixel": 1,
        "planar_configuration": 1,
        "predictor": 1,
        "tile_width": 512,
        "tile_height": 512,
        "sample_format": 1,
    }
    actual = {
        "width": width,
        "height": height,
        "bits": bits,
        "compression": compression,
        "photometric": photometric,
        "samples_per_pixel": samples_per_pixel,
        "planar_configuration": planar_configuration,
        "predictor": predictor,
        "tile_width": tile_width,
        "tile_height": tile_height,
        "sample_format": sample_format,
    }
    if actual != expected:
        raise ValueError(f"{path.name}: unexpected primary TIFF structure: {actual}")

    tiles_across = math.ceil(width / tile_width)
    tiles_down = math.ceil(height / tile_height)
    expected_tiles = tiles_across * tiles_down
    if len(offsets) != expected_tiles or len(byte_counts) != expected_tiles:
        raise ValueError(
            f"{path.name}: tile table sizes offsets={len(offsets)} counts={len(byte_counts)} expected={expected_tiles}"
        )

    output = bytearray(width * height)
    for tile_index, (offset, byte_count) in enumerate(zip(offsets, byte_counts)):
        if offset < 0 or byte_count <= 0 or offset + byte_count > len(data):
            raise ValueError(f"{path.name}: invalid tile range index={tile_index} offset={offset} bytes={byte_count}")
        tile = decompress_tile(data[offset:offset + byte_count])
        expected_tile_bytes = tile_width * tile_height
        if len(tile) != expected_tile_bytes:
            raise ValueError(
                f"{path.name}: decoded tile {tile_index} bytes={len(tile)} expected={expected_tile_bytes}"
            )
        tile_x = tile_index % tiles_across
        tile_y = tile_index // tiles_across
        copy_width = min(tile_width, width - tile_x * tile_width)
        copy_height = min(tile_height, height - tile_y * tile_height)
        for row in range(copy_height):
            src = row * tile_width
            dst = (tile_y * tile_height + row) * width + tile_x * tile_width
            output[dst:dst + copy_width] = tile[src:src + copy_width]

    return bytes(output), {
        **actual,
        "ifd_count": len(ifds),
        "tile_count": expected_tiles,
        "source_size_bytes": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_endianness_little": int(endian == "<"),
    }


if not plan_path.is_file():
    raise SystemExit(f"missing download plan; run download.sh first: {plan_path}")
with plan_path.open("r", encoding="utf-8", newline="") as fh:
    plan = list(csv.DictReader(fh, delimiter="\t"))
if len(plan) != EXPECTED_SAMPLES:
    raise SystemExit(f"download plan rows={len(plan)} expected={EXPECTED_SAMPLES}")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
source_rows: list[dict[str, object]] = []
aggregate = Counter()
seen_items: set[str] = set()

for row in plan:
    item_id = row["item_id"]
    if item_id in seen_items:
        raise SystemExit(f"duplicate item in plan: {item_id}")
    seen_items.add(item_id)
    source = source_dir / f"{item_id}_FireMask.tif"
    if not source.is_file():
        raise SystemExit(f"missing source raster: {source}")
    pixels, structure = decode_primary_grid(source)
    if len(pixels) != EXPECTED_VALUES:
        raise SystemExit(f"decoded size mismatch item={item_id} bytes={len(pixels)}")
    histogram = Counter(pixels)
    unexpected = set(histogram) - ALLOWED
    if unexpected:
        raise SystemExit(f"unexpected FireMask codes item={item_id}: {sorted(unexpected)}")
    if len(histogram) <= 1:
        raise SystemExit(f"constant FireMask sample item={item_id}")
    minority_fraction = 1.0 - max(histogram.values()) / len(pixels)
    if minority_fraction < MIN_MINORITY_FRACTION:
        raise SystemExit(f"degenerate FireMask sample item={item_id} minority_fraction={minority_fraction:.8f}")
    fire_pixels = sum(histogram[code] for code in FIRE_CLASSES)
    if fire_pixels <= 0:
        raise SystemExit(f"FireMask sample has no fire-confidence pixels item={item_id}")

    filename = f"{row['region']}_{row['date_utc']}_{row['tile']}_1200x1200.bin"
    output = out_dir / filename
    output.write_bytes(pixels)
    aggregate.update(histogram)
    histogram_json = {str(code): histogram[code] for code in sorted(histogram)}
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(output),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(pixels),
        "value_count": len(pixels),
        "sample_format": "raw homogeneous uint8 categorical grid",
        "sample_geometry": "1200x1200_modis_sinusoidal_tile",
        "sample_rank": 2,
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["y", "x"],
        "natural_record_kind": "complete_mod14a2_8_day_firemask_tile",
        "source_format": "cloud_optimized_geotiff",
        "source_field": "FireMask.band_1.maximum_fire_mask_class_over_8_day_composite",
        "source_file": rel(source),
        "source_url": row["url"],
        "item_id": item_id,
        "region": row["region"],
        "analysis_start_date_utc": row["date_utc"],
        "day_of_year": int(row["day_of_year"]),
        "modis_tile": row["tile"],
        "category_histogram": histogram_json,
        "fire_confidence_pixels": fire_pixels,
        "minority_fraction": minority_fraction,
        "source_sha256": structure["source_sha256"],
    })
    source_rows.append({
        "item_id": item_id,
        "region": row["region"],
        "analysis_start_date_utc": row["date_utc"],
        "day_of_year": int(row["day_of_year"]),
        "modis_tile": row["tile"],
        "source_file": rel(source),
        "source_url": row["url"],
        "tiff_structure": structure,
        "category_histogram": histogram_json,
        "fire_confidence_pixels": fire_pixels,
        "minority_fraction": minority_fraction,
    })
    print(
        f"built item={item_id} region={row['region']} date={row['date_utc']} "
        f"values={len(pixels)} fire_pixels={fire_pixels} minority={minority_fraction:.6f} "
        f"histogram={dict(sorted(histogram.items()))}"
    )

index_path = index_dir / "samples.jsonl"
with index_path.open("w", encoding="utf-8") as fh:
    for index_row in index_rows:
        fh.write(json.dumps(index_row, sort_keys=True) + "\n")

total_values = sum(int(row["value_count"]) for row in index_rows)
total_bytes = sum(int(row["sample_size_bytes"]) for row in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "primary_values": total_values,
    "primary_sample_bytes": total_bytes,
    "sample_shape": [HEIGHT, WIDTH],
    "category_histogram": {str(code): aggregate[code] for code in sorted(aggregate)},
    "fire_confidence_pixels": sum(aggregate[code] for code in FIRE_CLASSES),
    "min_minority_fraction": min(float(row["minority_fraction"]) for row in index_rows),
    "sources": source_rows,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"built dataset={DATASET_ID} samples={len(index_rows)} values={total_values} "
    f"bytes={total_bytes} codes={sorted(aggregate)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
