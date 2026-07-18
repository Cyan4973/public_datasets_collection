#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_goes16_abi_cloud_mask_netcdf_u8"
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
from pathlib import Path

DATASET_ID = "noaa_goes16_abi_cloud_mask_netcdf_u8"
FAMILY = "goes16_abi_cloud_mask_netcdf_bytes_u8"
MIN_SAMPLES = 12
MIN_PRIMARY_BYTES = 250_000_000
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def byte_variety(path: Path) -> int:
    size = path.stat().st_size
    chunks = []
    with path.open("rb") as fh:
        chunks.append(fh.read(min(1024 * 1024, size)))
        if size > 2 * 1024 * 1024:
            fh.seek(max(0, size // 2 - 512 * 1024))
            chunks.append(fh.read(1024 * 1024))
            fh.seek(max(0, size - 1024 * 1024))
            chunks.append(fh.read(1024 * 1024))
    return len(set(b"".join(chunks)))


out_dir = samples_dir / FAMILY
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
total_bytes = 0
for source in sorted(download_dir.glob("*.nc")):
    size = source.stat().st_size
    if size <= 0:
        raise SystemExit(f"empty NetCDF file: {source}")
    with source.open("rb") as fh:
        head = fh.read(8)
    if not (head.startswith(b"CDF") or head == b"\x89HDF\r\n\x1a\n"):
        raise SystemExit(f"not NetCDF classic or NetCDF4/HDF5: {source}")
    distinct = byte_variety(source)
    if distinct < 32:
        raise SystemExit(f"degenerate byte distribution in sampled chunks: {source}")
    out = out_dir / f"{source.stem}.bin"
    shutil.copyfile(source, out)
    total_bytes += size
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output exceeds cap: {total_bytes} > {MAX_PRIMARY_BYTES}")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": f"goes16_abi_cloud_mask_netcdf_{source.stem}_u8",
        "family": FAMILY,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": size,
        "value_count": size,
        "sample_format": "complete NetCDF/HDF5 product file bytes",
        "sample_geometry": "satellite_product_container_bytes",
        "sample_rank": 1,
        "sample_shape": [size],
        "sample_axes": ["byte"],
        "natural_record_kind": "goes16_abi_cloud_mask_netcdf_product",
        "source_file": source.name,
        "container_header": "hdf5" if head == b"\x89HDF\r\n\x1a\n" else "netcdf_classic",
        "distinct_values_sampled": distinct,
    }
    rows.append(row)
    records.append({
        "source_file": source.name,
        "sample_path": row["sample_path"],
        "bytes": size,
        "distinct_values_sampled": distinct,
        "container_header": row["container_header"],
    })

if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few GOES samples: {len(rows)} < {MIN_SAMPLES}")
if total_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {total_bytes} < {MIN_PRIMARY_BYTES}")

stats = {
    "dataset_id": DATASET_ID,
    "series_family": FAMILY,
    "sample_count": len(rows),
    "primary_values": total_bytes,
    "primary_sample_bytes": total_bytes,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(f"built samples={len(rows)} primary_values={total_bytes} primary_bytes={total_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
