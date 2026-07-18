#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_goes16_abi_cloud_mask_netcdf_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

DATASET_ID = "noaa_goes16_abi_cloud_mask_netcdf_u8"
FAMILY = "goes16_abi_cloud_mask_netcdf_bytes_u8"
MIN_SAMPLES = 12
MIN_PRIMARY_BYTES = 250_000_000
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few indexed samples: {len(rows)} < {MIN_SAMPLES}")

total_bytes = 0
seen = set()
for row in rows:
    if row.get("dataset_id") != DATASET_ID:
        raise SystemExit(f"unexpected dataset id: {row}")
    if row.get("family") != FAMILY:
        raise SystemExit(f"unexpected family: {row}")
    if row.get("role") != "primary":
        raise SystemExit(f"unexpected role: {row}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 8:
        raise SystemExit(f"unexpected numeric type: {row}")
    if row.get("natural_record_kind") != "goes16_abi_cloud_mask_netcdf_product":
        raise SystemExit(f"unexpected natural record kind: {row}")
    sample_path = row["sample_path"]
    if sample_path in seen:
        raise SystemExit(f"duplicate sample path: {sample_path}")
    seen.add(sample_path)
    path = root / sample_path
    if not path.is_file():
        raise SystemExit(f"missing sample: {sample_path}")
    size = path.stat().st_size
    if size != int(row["sample_size_bytes"]) or size != int(row["value_count"]):
        raise SystemExit(f"sample metadata size mismatch: {sample_path}")
    with path.open("rb") as fh:
        head = fh.read(8)
        first = fh.read(1024 * 1024)
        if size > 2 * 1024 * 1024:
            fh.seek(max(0, size // 2 - 512 * 1024))
            middle = fh.read(1024 * 1024)
            fh.seek(max(0, size - 1024 * 1024))
            last = fh.read(1024 * 1024)
        else:
            middle = b""
            last = b""
    if not (head.startswith(b"CDF") or head == b"\x89HDF\r\n\x1a\n"):
        raise SystemExit(f"bad NetCDF/HDF5 header: {sample_path}")
    if len(set(head + first + middle + last)) < 32:
        raise SystemExit(f"sample appears degenerate: {sample_path}")
    total_bytes += size

if total_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {total_bytes} < {MIN_PRIMARY_BYTES}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes} > {MAX_PRIMARY_BYTES}")
if int(stats.get("primary_sample_bytes", -1)) != total_bytes:
    raise SystemExit("stats/index primary byte mismatch")
if int(stats.get("sample_count", -1)) != len(rows):
    raise SystemExit("stats/index sample count mismatch")

print(f"verified dataset={DATASET_ID} samples={len(rows)} primary_bytes={total_bytes}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
