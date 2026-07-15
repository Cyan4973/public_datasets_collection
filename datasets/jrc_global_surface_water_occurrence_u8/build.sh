#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jrc_global_surface_water_occurrence_u8"
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
MAX_PRIMARY_BYTES="${GSW_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import shutil
import zlib
from collections import Counter
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "jrc_global_surface_water_occurrence_u8"
SERIES_ID = "global_surface_water_occurrence_u8"
ALLOWED_VALUES = set(range(101)) | {255}


def decompress_block(block: bytes, compression: int) -> bytes:
    if compression == 1:
        return block
    if compression == 5:
        return decode_tiff_lzw(block)
    if compression in {8, 32946}:
        try:
            return zlib.decompress(block)
        except zlib.error:
            return zlib.decompress(block, -15)
    raise ValueError(f"unsupported compression {compression}")


def iter_lzw_codes(block: bytes):
    bit_pos = 0
    code_size = 9
    max_bits = len(block) * 8
    while bit_pos + code_size <= max_bits:
        code = 0
        for _ in range(code_size):
            byte = block[bit_pos >> 3]
            bit = 7 - (bit_pos & 7)
            code = (code << 1) | ((byte >> bit) & 1)
            bit_pos += 1
        yield code


def decode_tiff_lzw(block: bytes) -> bytes:
    clear = 256
    eoi = 257
    next_code = 258
    code_size = 9
    table = {i: bytes([i]) for i in range(256)}
    previous: bytes | None = None
    output = bytearray()
    bit_pos = 0
    max_bits = len(block) * 8

    def read_code(size: int) -> int | None:
        nonlocal bit_pos
        if bit_pos + size > max_bits:
            return None
        code = 0
        for _ in range(size):
            byte = block[bit_pos >> 3]
            bit = 7 - (bit_pos & 7)
            code = (code << 1) | ((byte >> bit) & 1)
            bit_pos += 1
        return code

    while True:
        code = read_code(code_size)
        if code is None:
            break
        if code == clear:
            table = {i: bytes([i]) for i in range(256)}
            next_code = 258
            code_size = 9
            previous = None
            continue
        if code == eoi:
            break
        if code in table:
            entry = table[code]
        elif previous is not None and code == next_code:
            entry = previous + previous[:1]
        else:
            raise ValueError(f"invalid TIFF LZW code {code}")
        output.extend(entry)
        if previous is not None and next_code < 4096:
            table[next_code] = previous + entry[:1]
            next_code += 1
            if next_code >= (1 << code_size) - 1 and code_size < 12:
                code_size += 1
        previous = entry
    return bytes(output)


def undo_predictor_u8(buf: bytearray, width: int, height: int) -> None:
    for y in range(height):
        row = y * width
        prev = buf[row]
        for x in range(1, width):
            pos = row + x
            value = (buf[pos] + prev) & 255
            buf[pos] = value
            prev = value


plan = download_dir / "download_plan.tsv"
if not plan.exists():
    raise SystemExit(f"missing download plan: {plan}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / SERIES_ID
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_constant = 0
skipped_nodata_dominated = 0
total_bytes = 0

with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        chunk_path = download_dir / row["chunk_path"]
        if not chunk_path.is_file():
            raise SystemExit(f"missing chunk {chunk_path}")
        width = int(row["tile_width"])
        height = int(row["tile_length"])
        compression = int(row["compression"])
        predictor = int(row["predictor"])
        raw = bytearray(decompress_block(chunk_path.read_bytes(), compression))
        expected = width * height
        if len(raw) != expected:
            raise SystemExit(f"decoded tile size mismatch for {row['sample_id']}: {len(raw)} != {expected}")
        if predictor == 2:
            undo_predictor_u8(raw, width, height)
        elif predictor != 1:
            raise SystemExit(f"unsupported predictor {predictor}")
        histogram = Counter(raw)
        unknown = set(histogram) - ALLOWED_VALUES
        if unknown:
            raise SystemExit(f"unexpected occurrence codes in {row['sample_id']}: {sorted(unknown)[:10]}")
        if len(histogram) <= 1:
            skipped_constant += 1
            continue
        if histogram.get(255, 0) / len(raw) > 0.995:
            skipped_nodata_dominated += 1
            continue
        if total_bytes + len(raw) > max_primary_bytes:
            break
        out = out_dir / f"{row['sample_id']}_n{len(raw):07d}.bin"
        out.write_bytes(raw)
        total_bytes += len(raw)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(raw),
            "sample_format": "raw homogeneous uint8 occurrence grid",
            "sample_geometry": "2d_occurrence_raster_tile",
            "sample_rank": 2,
            "sample_shape": [height, width],
            "sample_axes": ["y", "x"],
            "natural_record_kind": "jrc_gsw_occurrence_cog_internal_tile",
            "source_id": row["source_id"],
            "source_url": row["url"],
            "tiff_tile_index": int(row["tile_index"]),
            "tiff_tile_x": int(row["tile_x"]),
            "tiff_tile_y": int(row["tile_y"]),
            "min": min(histogram),
            "max": max(histogram),
        })
        records.append({
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "tile_index": int(row["tile_index"]),
            "shape": [height, width],
            "distinct_values": len(histogram),
            "min_value": min(histogram),
            "max_value": max(histogram),
            "most_common_value": histogram.most_common(1)[0][0],
            "most_common_fraction": histogram.most_common(1)[0][1] / len(raw),
        })

if len(index_rows) < 12:
    raise SystemExit(
        f"only {len(index_rows)} accepted tiles; "
        f"skipped_constant={skipped_constant} skipped_nodata_dominated={skipped_nodata_dominated}"
    )

counts = sorted(int(row["value_count"]) for row in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "samples": len(index_rows),
    "skipped_constant_tiles": skipped_constant,
    "skipped_nodata_dominated_tiles": skipped_nodata_dominated,
    "primary_values": sum(counts),
    "primary_sample_bytes": total_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "max_primary_bytes": max_primary_bytes,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        out.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(index_rows)} skipped_constant={skipped_constant} "
    f"skipped_nodata_dominated={skipped_nodata_dominated} bytes={total_bytes} "
    f"median={stats['median_value_count']} range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
