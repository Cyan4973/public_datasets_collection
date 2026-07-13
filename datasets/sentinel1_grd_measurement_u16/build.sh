#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="sentinel1_grd_measurement_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLES_DIR="$DATA_ROOT/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import shutil
import statistics
import struct
import subprocess
import zlib
from pathlib import Path

DATASET_ID = "sentinel1_grd_measurement_u16"
MAX_PRIMARY_BYTES = int(os.environ.get("SENTINEL1_MAX_PRIMARY_BYTES", "1000000000"))
MIN_PRIMARY_BYTES = int(os.environ.get("SENTINEL1_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_PRIMARY_VALUES = int(os.environ.get("SENTINEL1_MIN_PRIMARY_VALUES", "10000"))
MIN_MEDIAN_VALUES = int(os.environ.get("SENTINEL1_MIN_MEDIAN_VALUES", "1000"))
MIN_SAMPLE_COUNT = int(os.environ.get("SENTINEL1_MIN_SAMPLE_COUNT", "2"))
ZSTD_BIN = os.environ.get("ZSTD_BIN", "zstd")
VALID_POLARIZATIONS = {"VV", "VH", "HH", "HV"}

data_root = Path(os.environ["DATA_ROOT"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def series_id_for(pol: str) -> str:
    return f"sentinel1_grd_{pol.lower()}_dn_u16"


def tiff_values(data: bytes, endian: str, bigtiff: bool, field_type: int, count: int, raw_value: int) -> list[int]:
    type_sizes = {
        1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
        11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8,
    }
    type_codes = {
        1: "B", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i",
        11: "f", 12: "d", 13: "I", 16: "Q", 17: "q", 18: "Q",
    }
    size = type_sizes.get(field_type)
    if size is None:
        raise ValueError(f"unsupported TIFF field type: {field_type}")
    inline_limit = 8 if bigtiff else 4
    byte_count = count * size
    if byte_count <= inline_limit:
        value_bytes = int(raw_value).to_bytes(inline_limit, byteorder="little" if endian == "<" else "big")[:byte_count]
    else:
        value_bytes = data[raw_value : raw_value + byte_count]
    if len(value_bytes) != byte_count:
        raise ValueError("truncated TIFF tag value")
    if field_type == 2:
        return [0]
    if field_type in {5, 10}:
        code = "I" if field_type == 5 else "i"
        vals = struct.unpack(endian + code * (count * 2), value_bytes)
        return [vals[i] for i in range(0, len(vals), 2)]
    code = type_codes.get(field_type)
    if code is None:
        raise ValueError(f"unsupported numeric TIFF field type: {field_type}")
    return list(struct.unpack(endian + code * count, value_bytes))


def parse_tiff(path: Path) -> dict:
    data = path.read_bytes()
    if data[:2] == b"II":
        endian, endianness = "<", "little"
    elif data[:2] == b"MM":
        endian, endianness = ">", "big"
    else:
        raise ValueError(f"{path.name}: not a TIFF file")
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic == 42:
        bigtiff = False
        ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
        entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
        base, entry_size = ifd_offset + 2, 12
        tags: dict[int, tuple[int, int, int]] = {}
        for index in range(entry_count):
            tag, field_type, count, raw_value = struct.unpack_from(endian + "HHII", data, base + index * entry_size)
            tags[tag] = (field_type, count, raw_value)
    elif magic == 43:
        bigtiff = True
        bytesize, zero = struct.unpack_from(endian + "HH", data, 4)
        if bytesize != 8 or zero != 0:
            raise ValueError(f"{path.name}: unsupported BigTIFF header")
        ifd_offset = struct.unpack_from(endian + "Q", data, 8)[0]
        entry_count = struct.unpack_from(endian + "Q", data, ifd_offset)[0]
        base, entry_size = ifd_offset + 8, 20
        tags = {}
        for index in range(entry_count):
            tag, field_type, count, raw_value = struct.unpack_from(endian + "HHQQ", data, base + index * entry_size)
            tags[tag] = (field_type, count, raw_value)
    else:
        raise ValueError(f"{path.name}: unsupported TIFF magic {magic}")

    def values(tag: int) -> list[int]:
        if tag not in tags:
            return []
        field_type, count, raw_value = tags[tag]
        return tiff_values(data, endian, bigtiff, field_type, count, raw_value)

    width_vals, height_vals, bits_vals = values(256), values(257), values(258)
    if not width_vals or not height_vals or not bits_vals:
        raise ValueError(f"{path.name}: missing required TIFF image tags")
    width, height, bits = int(width_vals[0]), int(height_vals[0]), int(bits_vals[0])
    compression = int((values(259) or [1])[0])
    samples_per_pixel = int((values(277) or [1])[0])
    predictor = int((values(317) or [1])[0])
    sample_format = int((values(339) or [1])[0])
    if bits != 16 or samples_per_pixel != 1 or sample_format != 1:
        raise ValueError(
            f"{path.name}: not single-band uint16 bits={bits} samples={samples_per_pixel} sample_format={sample_format}"
        )
    # 1=none, 8/32946=Deflate, 50000=Zstandard (Planetary Computer COG default).
    if compression not in {1, 8, 32946, 50000}:
        raise ValueError(f"{path.name}: unsupported TIFF compression {compression}")
    if predictor not in {1, 2}:
        raise ValueError(f"{path.name}: unsupported TIFF predictor {predictor}")

    if values(324) and values(325):
        tile_width = int(values(322)[0])
        tile_length = int(values(323)[0])
        offsets = [int(v) for v in values(324)]
        counts = [int(v) for v in values(325)]
        layout = "tiled"
    else:
        tile_width = width
        tile_length = int((values(278) or [height])[0])
        offsets = [int(v) for v in values(273)]
        counts = [int(v) for v in values(279)]
        layout = "striped"
    if not offsets or not counts or len(offsets) != len(counts):
        raise ValueError(f"{path.name}: invalid offset/count table")
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
        "bigtiff": bigtiff,
    }


def decompress_block(block: bytes, compression: int) -> bytes:
    if compression == 1:
        return block
    if compression in {8, 32946}:
        try:
            return zlib.decompress(block)
        except zlib.error:
            return zlib.decompress(block, -15)
    if compression == 50000:
        proc = subprocess.run(
            [ZSTD_BIN, "-d", "-c", "-q"],
            input=block,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise ValueError(f"zstd decode failed (rc={proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:200]}")
        return proc.stdout
    raise ValueError(f"unsupported compression {compression}")


def undo_horizontal_predictor(buf: bytearray, endian: str, width: int, height: int) -> None:
    for y in range(height):
        row = y * width * 2
        prev = struct.unpack_from(endian + "H", buf, row)[0]
        for x in range(1, width):
            offset = row + x * 2
            value = (struct.unpack_from(endian + "H", buf, offset)[0] + prev) & 0xFFFF
            struct.pack_into(endian + "H", buf, offset, value)
            prev = value


def decode_full_raster(info: dict) -> bytes:
    """Losslessly decode the whole measurement raster (the natural sample boundary
    is one source measurement GeoTIFF). Deflate via zlib, Zstandard via the zstd
    CLI; horizontal predictor reversed when present."""
    width = int(info["width"])
    height = int(info["height"])
    tile_width = int(info["tile_width"])
    tile_length = int(info["tile_length"])
    output = bytearray(width * height * 2)
    tiles_across = (width + tile_width - 1) // tile_width
    for index, (offset, count) in enumerate(zip(info["offsets"], info["counts"])):
        block = info["data"][offset : offset + count]
        raw = bytearray(decompress_block(block, int(info["compression"])))
        if info["layout"] == "tiled":
            tile_x = (index % tiles_across) * tile_width
            tile_y = (index // tiles_across) * tile_length
            block_width = tile_width
            block_height = tile_length
            expected = tile_width * tile_length * 2
        else:
            tile_x = 0
            tile_y = index * tile_length
            block_width = width
            block_height = max(0, min(tile_length, height - tile_y))
            expected = block_width * block_height * 2
        if len(raw) != expected:
            raise ValueError(f"decoded TIFF block has unexpected size: got={len(raw)} expected={expected}")
        if info["predictor"] == 2:
            undo_horizontal_predictor(raw, str(info["endian"]), block_width, block_height)
        copy_width = max(0, min(block_width, width - tile_x))
        copy_height = max(0, min(block_height, height - tile_y))
        for row in range(copy_height):
            src = row * block_width * 2
            dst = ((tile_y + row) * width + tile_x) * 2
            output[dst : dst + copy_width * 2] = raw[src : src + copy_width * 2]
    return bytes(output)


def read_plan() -> list[dict]:
    plan = download_dir / "download_plan.tsv"
    if not plan.exists():
        raise SystemExit(f"missing download plan: {plan}")
    with plan.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
reset_dir(samples_dir)

rows = []
records = []
series_totals: dict[str, int] = {}
total_bytes = 0
for sample_index, plan_row in enumerate(read_plan(), start=1):
    pol = str(plan_row.get("polarization") or "").upper()
    if pol not in VALID_POLARIZATIONS:
        raise SystemExit(f"invalid polarization in plan: {plan_row}")
    sid = series_id_for(pol)
    source = download_dir / str(plan_row["local_name"])
    if not source.exists():
        raise SystemExit(f"missing download: {source}")
    info = parse_tiff(source)
    payload = decode_full_raster(info)
    if len(payload) != info["width"] * info["height"] * 2:
        raise RuntimeError(f"{source.name}: decoded payload size mismatch")
    prefix_count = min(len(payload) // 2, 200_000)
    prefix_values = struct.unpack(info["endian"] + "H" * prefix_count, payload[: prefix_count * 2])
    if len(set(prefix_values)) <= 1:
        raise RuntimeError(f"{source.name}: constant prefix rejected")
    total_bytes += len(payload)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
    out_dir = samples_dir / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sample_index:04d}_{source.stem}.bin"
    out.write_bytes(payload)
    row = {
        "dataset_id": DATASET_ID,
        "series_id": sid,
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
        "natural_record_kind": "sentinel1_grd_measurement_tiff",
        "source_path": source.as_posix(),
        "scene_id": plan_row.get("scene_id", ""),
        "polarization": pol,
        "asset_key": plan_row.get("asset_key", ""),
        "datetime": plan_row.get("datetime", ""),
        "platform": plan_row.get("platform", ""),
        "source_mode": plan_row.get("source_mode", ""),
        "tiff_layout": info["layout"],
        "tiff_compression": info["compression"],
        "tiff_predictor": info["predictor"],
        "tiff_bigtiff": info["bigtiff"],
    }
    rows.append(row)
    series_totals[sid] = series_totals.get(sid, 0) + len(payload)
    records.append(
        {
            **plan_row,
            "source_file": source.name,
            "source_bytes": source.stat().st_size,
            "sample_path": row["sample_path"],
            "series_id": sid,
            "sample_bytes": len(payload),
            "value_count": len(payload) // 2,
            "shape": [info["height"], info["width"]],
            "endianness": info["endianness"],
            "tiff_layout": info["layout"],
            "tiff_compression": info["compression"],
            "tiff_predictor": info["predictor"],
            "tiff_bigtiff": info["bigtiff"],
            "prefix_distinct_values": len(set(prefix_values)),
            "prefix_min_value": min(prefix_values),
            "prefix_max_value": max(prefix_values),
        }
    )

sizes = [int(row["sample_size_bytes"]) for row in rows]
values = [int(row["value_count"]) for row in rows]
if not rows:
    raise RuntimeError("no measurement rasters survived filtering")
if sum(sizes) < MIN_PRIMARY_BYTES or sum(values) < MIN_PRIMARY_VALUES:
    raise RuntimeError("primary payload below aggregate floor")
if statistics.median(values) < MIN_MEDIAN_VALUES:
    raise RuntimeError("median sample below floor")
if len(rows) < MIN_SAMPLE_COUNT:
    raise RuntimeError(f"expected at least {MIN_SAMPLE_COUNT} natural measurement samples")

stats = {
    "dataset_id": DATASET_ID,
    "record_count": len(records),
    "total_primary_bytes": sum(sizes),
    "total_primary_values": sum(values),
    "series_total_bytes": series_totals,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_values={sum(values)} primary_bytes={sum(sizes)} series={','.join(sorted(series_totals))}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
