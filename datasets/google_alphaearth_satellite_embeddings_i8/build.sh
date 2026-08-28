#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_alphaearth_satellite_embeddings_i8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

# The download phase has already isolated independent TIFF tile frames.
if ! command -v zstd >/dev/null 2>&1; then
  echo "FATAL: zstd command is required to decode TIFF Compression=50000 chunks" >&2
  exit 1
fi

MAX_PRIMARY_BYTES="${ALPHAEARTH_MAX_PRIMARY_BYTES:-950000000}"
MAX_NODATA_FRACTION="${ALPHAEARTH_MAX_NODATA_FRACTION:-0.25}"
MIN_DISTINCT_VALUES="${ALPHAEARTH_MIN_DISTINCT_VALUES:-16}"
export DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR MAX_NODATA_FRACTION MAX_PRIMARY_BYTES MIN_DISTINCT_VALUES REPO_ROOT SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])
max_nodata_fraction = float(os.environ["MAX_NODATA_FRACTION"])
min_distinct_values = int(os.environ["MIN_DISTINCT_VALUES"])

dataset_id = "google_alphaearth_satellite_embeddings_i8"
family = "alphaearth_embedding_axis_i8"
plan_path = download_dir / "download_plan.tsv"
if not plan_path.is_file():
    raise SystemExit(f"missing download plan: {plan_path}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
output_dir = samples_dir / family
output_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = list(csv.DictReader(plan_path.open("r", encoding="utf-8", newline=""), delimiter="\t"))
if len(rows) != 384:
    raise SystemExit(f"expected 384 planned samples, found {len(rows)}")

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
total_bytes = 0
for ordinal, row in enumerate(rows):
    chunk_path = download_dir / row["chunk_path"]
    if not chunk_path.is_file() or chunk_path.stat().st_size != int(row["byte_count"]):
        raise SystemExit(f"missing or invalid compressed chunk: {chunk_path}")
    completed = subprocess.run(
        ["zstd", "-q", "-d", "-c", str(chunk_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"zstd decode failed for {row['sample_id']}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    raw = completed.stdout
    width = int(row["tile_width"])
    height = int(row["tile_length"])
    expected = width * height
    if len(raw) != expected:
        raise SystemExit(f"decoded size mismatch {row['sample_id']}: {len(raw)} != {expected}")
    histogram = Counter(raw)
    if len(histogram) < min_distinct_values:
        raise SystemExit(
            f"degenerate sample {row['sample_id']}: distinct={len(histogram)} < {min_distinct_values}"
        )
    nodata_count = histogram.get(128, 0)  # signed int8 -128 is byte 0x80
    nodata_fraction = nodata_count / len(raw)
    if nodata_fraction > max_nodata_fraction:
        raise SystemExit(
            f"excess NoData sample {row['sample_id']}: fraction={nodata_fraction:.6f} "
            f"> {max_nodata_fraction:.6f}"
        )
    if total_bytes + len(raw) > max_primary_bytes:
        raise SystemExit(f"primary output would exceed cap: {total_bytes + len(raw)}")

    output = output_dir / f"{row['sample_id']}_n{len(raw):07d}.bin"
    output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    signed_values = [(byte if byte < 128 else byte - 256) for byte in histogram]
    index_rows.append(
        {
            "dataset_id": dataset_id,
            "series_id": family,
            "role": "primary",
            "sample_path": output.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(raw),
            "value_count": len(raw),
            "sample_geometry": f"grid_{height}x{width}",
            "sample_rank": 2,
            "sample_shape": [height, width],
            "sample_axes": ["y", "x"],
            "source_id": row["source_id"],
            "source_year": int(row["year"]),
            "utm_zone": row["utm_zone"],
            "source_object": row["object_name"],
            "source_generation": row["generation"],
            "embedding_axis": row["embedding_axis"],
            "embedding_axis_index": int(row["embedding_axis_index"]),
            "tiff_tile_x": int(row["tile_x"]),
            "tiff_tile_y": int(row["tile_y"]),
            "tiff_spatial_tile_index": int(row["spatial_tile_index"]),
            "tiff_chunk_index": int(row["tiff_chunk_index"]),
            "compressed_chunk_path": row["chunk_path"],
            "compressed_chunk_bytes": int(row["byte_count"]),
            "sha256": digest,
            "natural_record_kind": "alphaearth_embedding_axis_cog_internal_tile",
        }
    )
    records.append(
        {
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "embedding_axis": row["embedding_axis"],
            "shape": [height, width],
            "distinct_values": len(histogram),
            "minimum_signed_value": min(signed_values),
            "maximum_signed_value": max(signed_values),
            "nodata_count": nodata_count,
            "nodata_fraction": nodata_fraction,
            "compressed_bytes": int(row["byte_count"]),
            "sample_sha256": digest,
        }
    )
    total_bytes += len(raw)
    if (ordinal + 1) % 32 == 0:
        print(f"decoded samples={ordinal + 1}/{len(rows)} bytes={total_bytes}")

index_rows.sort(key=lambda row: str(row["sample_path"]))
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
    for row in index_rows:
        handle.write(json.dumps(row, sort_keys=True) + "\n")

stats = {
    "dataset_id": dataset_id,
    "family": family,
    "source_count": len({row["source_id"] for row in index_rows}),
    "sample_count": len(index_rows),
    "primary_values": sum(int(row["value_count"]) for row in index_rows),
    "primary_sample_bytes": total_bytes,
    "sample_size_bytes": 1024 * 1024,
    "maximum_nodata_fraction": max(record["nodata_fraction"] for record in records),
    "minimum_distinct_values": min(record["distinct_values"] for record in records),
    "zstd_version": subprocess.check_output(["zstd", "--version"], text=True).strip(),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"built samples={stats['sample_count']} sources={stats['source_count']} "
    f"values={stats['primary_values']} bytes={stats['primary_sample_bytes']} "
    f"max_nodata_fraction={stats['maximum_nodata_fraction']:.6f}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
