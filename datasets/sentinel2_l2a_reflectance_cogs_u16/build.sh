#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sentinel2_l2a_reflectance_cogs_u16"
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
import statistics
import struct
import zlib
from pathlib import Path

DATASET_ID = "sentinel2_l2a_reflectance_cogs_u16"
SERIES_ID = "sentinel2_l2a_reflectance_pixels_u16"
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


def tiff_values(data: bytes, endian: str, field_type: int, count: int, raw_value: int) -> list[int]:
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
    data = path.read_bytes()
    if data[:2] == b"II":
        endian = "<"
        endianness = "little"
    elif data[:2] == b"MM":
        endian = ">"
        endianness = "big"
    else:
        raise ValueError(f"{path.name}: not a TIFF file")
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic != 42:
        raise ValueError(f"{path.name}: unsupported TIFF magic {magic}")
    ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
    entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
    tags: dict[int, tuple[int, int, int]] = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, field_type, count, raw_value = struct.unpack_from(endian + "HHII", data, offset)
        tags[tag] = (field_type, count, raw_value)

    def values(tag: int) -> list[int]:
        if tag not in tags:
            return []
        field_type, count, raw_value = tags[tag]
        return tiff_values(data, endian, field_type, count, raw_value)

    width = values(256)[0]
    height = values(257)[0]
    bits = values(258)[0]
    compression = (values(259) or [1])[0]
    samples_per_pixel = (values(277) or [1])[0]
    predictor = (values(317) or [1])[0]
    sample_format = (values(339) or [1])[0]
    if bits != 16 or samples_per_pixel != 1 or sample_format != 1:
        raise ValueError(
            f"{path.name}: not single-band uint16 bits={bits} samples={samples_per_pixel} sample_format={sample_format}"
        )
    if compression not in {1, 8, 32946}:
        raise ValueError(f"{path.name}: unsupported TIFF compression {compression}")
    if predictor not in {1, 2}:
        raise ValueError(f"{path.name}: unsupported TIFF predictor {predictor}")
    if values(324) and values(325):
        tile_width = values(322)[0]
        tile_length = values(323)[0]
        offsets = values(324)
        counts = values(325)
        layout = "tiled"
    else:
        tile_width = width
        tile_length = (values(278) or [height])[0]
        offsets = values(273)
        counts = values(279)
        layout = "striped"
    if len(offsets) != len(counts):
        raise ValueError(f"{path.name}: offset/count table length mismatch")
    return {
        "data": data,
        "endian": endian,
        "endianness": endianness,
        "width": width,
        "height": height,
        "compression": compression,
        "predictor": predictor,
        "tile_width": tile_width,
        "tile_length": tile_length,
        "offsets": offsets,
        "counts": counts,
        "layout": layout,
    }


def decompress_block(block: bytes, compression: int) -> bytes:
    if compression == 1:
        return block
    try:
        return zlib.decompress(block)
    except zlib.error:
        return zlib.decompress(block, -15)


def undo_horizontal_predictor(buf: bytearray, endian: str, width: int, height: int) -> None:
    for y in range(height):
        row = y * width * 2
        prev = struct.unpack_from(endian + "H", buf, row)[0]
        for x in range(1, width):
            offset = row + x * 2
            value = (struct.unpack_from(endian + "H", buf, offset)[0] + prev) & 0xFFFF
            struct.pack_into(endian + "H", buf, offset, value)
            prev = value


def decode_pixels(info: dict) -> bytes:
    width = info["width"]
    height = info["height"]
    tile_width = info["tile_width"]
    tile_length = info["tile_length"]
    output = bytearray(width * height * 2)
    tiles_across = (width + tile_width - 1) // tile_width
    for index, (offset, count) in enumerate(zip(info["offsets"], info["counts"])):
        block = info["data"][offset : offset + count]
        raw = bytearray(decompress_block(block, info["compression"]))
        if len(raw) != tile_width * tile_length * 2:
            raise ValueError(f"decoded tile has unexpected size: got={len(raw)} expected={tile_width * tile_length * 2}")
        if info["predictor"] == 2:
            undo_horizontal_predictor(raw, info["endian"], tile_width, tile_length)
        tile_x = (index % tiles_across) * tile_width
        tile_y = (index // tiles_across) * tile_length
        copy_width = max(0, min(tile_width, width - tile_x))
        copy_height = max(0, min(tile_length, height - tile_y))
        for row in range(copy_height):
            src = row * tile_width * 2
            dst = ((tile_y + row) * width + tile_x) * 2
            output[dst : dst + copy_width * 2] = raw[src : src + copy_width * 2]
    return bytes(output)


def read_plan() -> list[dict]:
    plan = download_dir / "download_plan.tsv"
    if not plan.exists():
        raise SystemExit(f"missing download plan: {plan}")
    rows = []
    for line in plan.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        local_name, url, scene_id, band_label, asset_key, search_label, datetime, cloud_cover = line.split("\t")
        rows.append(
            {
                "local_name": local_name,
                "url": url,
                "scene_id": scene_id,
                "band_label": band_label,
                "asset_key": asset_key,
                "search_label": search_label,
                "datetime": datetime,
                "cloud_cover": cloud_cover,
            }
        )
    return rows


reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
total_bytes = 0
for sample_index, plan_row in enumerate(read_plan(), start=1):
    source = download_dir / plan_row["local_name"]
    if not source.exists():
        raise SystemExit(f"missing download: {source}")
    info = parse_tiff(source)
    payload = decode_pixels(info)
    if len(payload) != info["width"] * info["height"] * 2:
        raise RuntimeError(f"{source.name}: decoded payload size mismatch")
    prefix_count = min(len(payload) // 2, 200_000)
    prefix_values = struct.unpack(info["endian"] + "H" * prefix_count, payload[: prefix_count * 2])
    if len(set(prefix_values)) <= 1:
        raise RuntimeError(f"{source.name}: constant prefix rejected")
    total_bytes += len(payload)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
    out = out_dir / f"{sample_index:04d}_{source.stem}.bin"
    out.write_bytes(payload)
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": info["endianness"],
        "element_size_bytes": 2,
        "sample_size_bytes": len(payload),
        "value_count": len(payload) // 2,
        "sample_geometry": "2d_raster",
        "sample_rank": 2,
        "sample_shape": [info["height"], info["width"]],
        "sample_axes": ["y", "x"],
        "source_path": source.as_posix(),
        "scene_id": plan_row["scene_id"],
        "band_label": plan_row["band_label"],
        "asset_key": plan_row["asset_key"],
        "datetime": plan_row["datetime"],
        "cloud_cover": plan_row["cloud_cover"],
        "tiff_layout": info["layout"],
        "tiff_compression": info["compression"],
        "tiff_predictor": info["predictor"],
    }
    rows.append(row)
    records.append(
        {
            **plan_row,
            "source_file": source.name,
            "source_bytes": source.stat().st_size,
            "sample_path": row["sample_path"],
            "sample_bytes": len(payload),
            "value_count": len(payload) // 2,
            "shape": [info["height"], info["width"]],
            "endianness": info["endianness"],
            "tiff_layout": info["layout"],
            "tiff_compression": info["compression"],
            "tiff_predictor": info["predictor"],
            "prefix_distinct_values": len(set(prefix_values)),
            "prefix_min_value": min(prefix_values),
            "prefix_max_value": max(prefix_values),
        }
    )

sizes = [row["sample_size_bytes"] for row in rows]
values = [row["value_count"] for row in rows]
if sum(sizes) < MIN_PRIMARY_BYTES or sum(values) < MIN_PRIMARY_VALUES:
    raise RuntimeError("primary payload below aggregate floor")
if statistics.median(values) < MIN_MEDIAN_VALUES:
    raise RuntimeError("median sample below floor")

stats = {
    "dataset_id": DATASET_ID,
    "record_count": len(records),
    "total_primary_bytes": sum(sizes),
    "total_primary_values": sum(values),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_values={sum(values)} primary_bytes={sum(sizes)}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
