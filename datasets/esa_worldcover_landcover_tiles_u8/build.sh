#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="esa_worldcover_landcover_tiles_u8"
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
MAX_PRIMARY_BYTES="${WORLDCOVER_MAX_PRIMARY_BYTES:-950000000}"
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

DATASET_ID = "esa_worldcover_landcover_tiles_u8"
FAMILY = "worldcover_landcover_class_u8"
ALLOWED_VALUES = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}


def decompress_block(block: bytes, compression: int) -> bytes:
    if compression == 1:
        return block
    if compression in {8, 32946}:
        try:
            return zlib.decompress(block)
        except zlib.error:
            return zlib.decompress(block, -15)
    raise ValueError(f"unsupported compression {compression}")


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
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_constant = 0
bad_value_samples = 0
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
        hist = Counter(raw)
        unknown = set(hist) - ALLOWED_VALUES
        if unknown:
            bad_value_samples += 1
            raise SystemExit(f"unexpected class codes in {row['sample_id']}: {sorted(unknown)[:10]}")
        if len(hist) <= 1:
            skipped_constant += 1
            continue
        if total_bytes + len(raw) > max_primary_bytes:
            break
        out = out_dir / f"{row['sample_id']}_n{len(raw):07d}.bin"
        out.write_bytes(raw)
        total_bytes += len(raw)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": FAMILY,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(raw),
            "sample_geometry": f"grid_{height}x{width}",
            "sample_rank": 2,
            "sample_shape": [height, width],
            "sample_axes": ["y", "x"],
            "source_id": row["source_id"],
            "source_url": row["url"],
            "tiff_tile_index": int(row["tile_index"]),
            "tiff_tile_x": int(row["tile_x"]),
            "tiff_tile_y": int(row["tile_y"]),
            "natural_record_kind": "worldcover_cog_internal_tile",
        })
        records.append({
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "tile_index": int(row["tile_index"]),
            "shape": [height, width],
            "distinct_values": len(hist),
            "min_value": min(hist),
            "max_value": max(hist),
            "most_common_value": hist.most_common(1)[0][0],
            "most_common_fraction": hist.most_common(1)[0][1] / len(raw),
        })

if len(index_rows) < 12:
    raise SystemExit(f"only {len(index_rows)} non-constant decoded tiles; skipped_constant={skipped_constant}")
counts = sorted(int(r["value_count"]) for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "samples": len(index_rows),
    "skipped_constant_tiles": skipped_constant,
    "bad_value_samples": bad_value_samples,
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
    f"bytes={total_bytes} median={stats['median_value_count']} "
    f"range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
