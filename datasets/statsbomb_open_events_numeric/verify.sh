#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="statsbomb_open_events_numeric"
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
import math
import os
import statistics
import struct
from pathlib import Path

DATASET_ID = "statsbomb_open_events_numeric"
MIN_VALUES_PER_SAMPLE = int(os.environ.get("STATSBOMB_MIN_VALUES_PER_SAMPLE", "200"))
MIN_SAMPLE_COUNT = int(os.environ.get("STATSBOMB_MIN_SAMPLE_COUNT", "30"))
MIN_PRIMARY_VALUES = int(os.environ.get("STATSBOMB_MIN_PRIMARY_VALUES", "10000"))
MIN_PRIMARY_BYTES = int(os.environ.get("STATSBOMB_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_MEDIAN_VALUES = int(os.environ.get("STATSBOMB_MIN_MEDIAN_VALUES", "1000"))
MAX_PRIMARY_BYTES = int(os.environ.get("STATSBOMB_MAX_PRIMARY_BYTES", "1000000000"))

# series_id -> (role, numeric_kind, bit_width, element_size, struct_code, int_range_or_None)
SPECS = {
    "statsbomb_event_location_x": ("primary", "float", 32, 4, "<f", None),
    "statsbomb_event_location_y": ("primary", "float", 32, 4, "<f", None),
    "statsbomb_event_duration": ("primary", "float", 32, 4, "<f", None),
    "statsbomb_event_minute": ("auxiliary", "uint", 16, 2, "<H", (0, 65535)),
    "statsbomb_event_second": ("auxiliary", "uint", 8, 1, "<B", (0, 255)),
    "statsbomb_event_possession": ("auxiliary", "uint", 16, 2, "<H", (0, 65535)),
}

data_root = Path(os.environ["DATA_ROOT"])
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if not rows:
    raise SystemExit("empty sample index")

primary_series_counts: dict[str, int] = {}
seen_paths: set[str] = set()
primary_values_list: list[int] = []
primary_bytes = 0

for row in rows:
    sid = row.get("series_id")
    if row.get("dataset_id") != DATASET_ID or sid not in SPECS:
        raise SystemExit(f"unexpected dataset/series row: {row}")
    role, kind, bits, elem, code, int_range = SPECS[sid]
    if row.get("role") != role:
        raise SystemExit(f"role mismatch for {sid}: {row.get('role')} != {role}")
    if row.get("numeric_kind") != kind or int(row.get("bit_width", 0)) != bits or int(row.get("element_size_bytes", 0)) != elem:
        raise SystemExit(f"representation mismatch: {row}")
    if row.get("endianness") != "little":
        raise SystemExit(f"unexpected endianness: {row}")
    if row.get("sample_geometry") != "1d_sequence" or int(row.get("sample_rank", 0)) != 1:
        raise SystemExit(f"unexpected geometry: {row}")
    if row.get("natural_record_kind") != "statsbomb_match_event_stream":
        raise SystemExit(f"unexpected natural boundary: {row}")

    path = data_root / row["sample_path"]
    if row["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {row['sample_path']}")
    seen_paths.add(row["sample_path"])
    expected_bytes = int(row["sample_size_bytes"])
    expected_values = int(row["value_count"])
    if expected_values < MIN_VALUES_PER_SAMPLE:
        raise SystemExit(f"sample below min values: {path} ({expected_values})")
    if expected_bytes != expected_values * elem:
        raise SystemExit(f"byte/value mismatch: {path}")
    if not path.is_file() or path.stat().st_size != expected_bytes:
        raise SystemExit(f"size mismatch: {path}")

    data = path.read_bytes()
    values = [v for (v,) in struct.iter_unpack(code, data)]
    if len(values) != expected_values:
        raise SystemExit(f"value count unpack mismatch: {path}")
    if kind == "float" and any(not math.isfinite(v) for v in values):
        raise SystemExit(f"non-finite value in {path}")
    if int_range is not None:
        lo, hi = int_range
        if min(values) < lo or max(values) > hi:
            raise SystemExit(f"value outside declared range: {path}")
    vmin, vmax = min(values), max(values)
    if vmin == vmax:
        raise SystemExit(f"constant sample rejected: {path}")
    if abs(float(row["min"]) - float(vmin)) > 1e-6 or abs(float(row["max"]) - float(vmax)) > 1e-6:
        raise SystemExit(f"index min/max mismatch: {path}")

    if role == "primary":
        primary_series_counts[sid] = primary_series_counts.get(sid, 0) + 1
        primary_values_list.append(expected_values)
        primary_bytes += expected_bytes

# ---- Acceptance floors (primary payload only) --------------------------------
expected_primary = {sid for sid, spec in SPECS.items() if spec[0] == "primary"}
missing = expected_primary - set(primary_series_counts)
short = {sid: n for sid, n in primary_series_counts.items() if n < MIN_SAMPLE_COUNT}
if missing or short:
    raise SystemExit(f"primary series below sample-count floor: missing={sorted(missing)} short={short}")

primary_values = sum(primary_values_list)
median_primary = statistics.median(primary_values_list)
if primary_values < MIN_PRIMARY_VALUES and primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"below aggregate floor: values={primary_values} bytes={primary_bytes}")
if median_primary < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median primary sample below floor: {median_primary}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")
if int(stats.get("primary_bytes", -1)) != primary_bytes or int(stats.get("primary_sample_count", -1)) != len(primary_values_list):
    raise SystemExit("stats/index primary mismatch")

print(
    f"verified_rows={len(rows)} primary_samples={len(primary_values_list)} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_primary_values={int(median_primary)} primary_series={primary_series_counts}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
