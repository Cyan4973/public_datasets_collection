#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="hyg_star_photometry_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export DATA_ROOT FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

DATASET_ID = "hyg_star_photometry_i16"
EXPECTED = {
    "hyg_star_apparent_mag_mmag_i16",
    "hyg_star_absolute_mag_mmag_i16",
    "hyg_star_color_index_mmag_i16",
}
MIN_VALUES_PER_SAMPLE = int(os.environ.get("HYG_MIN_VALUES_PER_SAMPLE", "10000"))
MIN_SAMPLE_COUNT = int(os.environ.get("HYG_MIN_SAMPLE_COUNT", "3"))
MAX_PRIMARY_BYTES = int(os.environ.get("HYG_MAX_PRIMARY_BYTES", "1000000000"))
I16_MIN, I16_MAX = -32768, 32767

data_root = Path(os.environ["DATA_ROOT"])
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
if len(rows) < MIN_SAMPLE_COUNT:
    raise SystemExit(f"expected >= {MIN_SAMPLE_COUNT} series, found {len(rows)}")
if {r["series_id"] for r in rows} != EXPECTED:
    raise SystemExit(f"unexpected series set: {sorted(r['series_id'] for r in rows)}")

primary_bytes = 0
for row in rows:
    if row.get("dataset_id") != DATASET_ID or row.get("role") != "primary":
        raise SystemExit(f"unexpected row identity: {row}")
    if row.get("numeric_kind") != "int" or int(row.get("bit_width", 0)) != 16 or int(row.get("element_size_bytes", 0)) != 2:
        raise SystemExit(f"unexpected representation: {row}")
    if row.get("endianness") != "little" or row.get("natural_record_kind") != "hyg_catalog_column":
        raise SystemExit(f"unexpected metadata: {row}")
    path = data_root / row["sample_path"]
    expected_bytes = int(row["sample_size_bytes"])
    expected_values = int(row["value_count"])
    if expected_values < MIN_VALUES_PER_SAMPLE:
        raise SystemExit(f"{path}: below min values ({expected_values})")
    if expected_bytes != expected_values * 2:
        raise SystemExit(f"byte/value mismatch: {path}")
    if not path.is_file() or path.stat().st_size != expected_bytes:
        raise SystemExit(f"size mismatch: {path}")
    data = path.read_bytes()
    values = [v for (v,) in struct.iter_unpack("<h", data)]
    if len(values) != expected_values:
        raise SystemExit(f"value count unpack mismatch: {path}")
    vmin, vmax = min(values), max(values)
    if vmin < I16_MIN or vmax > I16_MAX:
        raise SystemExit(f"value outside int16 range: {path}")
    if vmin == vmax:
        raise SystemExit(f"constant sample: {path}")
    if int(row["min"]) != vmin or int(row["max"]) != vmax:
        raise SystemExit(f"index min/max mismatch: {path}")
    primary_bytes += expected_bytes

if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if set(stats.get("series", {})) != {r["series_id"] for r in rows}:
    raise SystemExit("stats/index series mismatch")

print(
    f"verified_rows={len(rows)} primary_bytes={primary_bytes} "
    f"values={[r['value_count'] for r in rows]}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
