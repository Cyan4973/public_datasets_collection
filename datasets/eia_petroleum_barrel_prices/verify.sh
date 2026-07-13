#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_petroleum_barrel_prices"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
export EIA_BARREL_PRICE_MIN_RETAINED_SERIES="${EIA_BARREL_PRICE_MIN_RETAINED_SERIES:-5}"
export EIA_BARREL_PRICE_MIN_PRIMARY_BYTES="${EIA_BARREL_PRICE_MIN_PRIMARY_BYTES:-102400}"
export EIA_BARREL_PRICE_MIN_MEDIAN_VALUES="${EIA_BARREL_PRICE_MIN_MEDIAN_VALUES:-240}"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import statistics
import struct
from collections import defaultdict
from pathlib import Path

FAMILY = "eia_petroleum_crude_oil_price_usd_per_barrel_f64"

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
min_series = int(os.environ["EIA_BARREL_PRICE_MIN_RETAINED_SERIES"])
min_bytes = int(os.environ["EIA_BARREL_PRICE_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["EIA_BARREL_PRICE_MIN_MEDIAN_VALUES"])


def is_barrel_unit(units: str) -> bool:
    u = re.sub(r"\s+", "", str(units).upper())
    return u in {"$/BBL", "DOLLARS/BARREL", "DOLLARSPERBARREL", "DOLLARS/BBL"}

stats = json.loads((filter_dir / "ingest_stats.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (index_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
if not rows:
    raise SystemExit("missing sample index rows")

by_series = defaultdict(list)
for row in rows:
    if row.get("series_id") != FAMILY or row.get("role") != "primary":
        raise SystemExit(f"unexpected row: {row.get('series_id')} role={row.get('role')}")
    if row["numeric_kind"] != "float" or int(row["bit_width"]) != 64:
        raise SystemExit(f"unexpected numeric type: {row}")
    if not is_barrel_unit(row.get("units", "")):
        raise SystemExit(f"unexpected unit for {row['sample_path']}: {row.get('units')}")
    by_series[row["eia_series"]].append(row)

if len(rows) < min_series:
    raise SystemExit(f"only {len(rows)} samples < {min_series}")
if len(by_series) < min_series:
    raise SystemExit(f"only {len(by_series)} independent EIA series < {min_series}")

counts = []
total_bytes = 0
for row in rows:
    p = root / row["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    size = p.stat().st_size
    expected = int(row["value_count"]) * 8
    if size != expected or size != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch for {row['sample_path']}: {size} != {expected}")
    raw = p.read_bytes()
    values = struct.unpack("<" + "d" * int(row["value_count"]), raw)
    if len(set(values)) <= 1:
        raise SystemExit(f"constant sample rejected: {row['sample_path']}")
    counts.append(int(row["value_count"]))
    total_bytes += size

if total_bytes != int(stats["primary_sample_bytes"]):
    raise SystemExit("primary_sample_bytes statistic mismatch")
if sum(counts) != int(stats["primary_values"]):
    raise SystemExit("primary_values statistic mismatch")
if total_bytes < min_bytes:
    raise SystemExit(f"primary bytes below floor: {total_bytes} < {min_bytes}")
if statistics.median(counts) < min_median_values:
    raise SystemExit(f"median values below floor: {statistics.median(counts)} < {min_median_values}")

print(
    f"verified family={FAMILY} samples={len(rows)} independent_series={len(by_series)} "
    f"median_values={int(statistics.median(counts))} primary_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
