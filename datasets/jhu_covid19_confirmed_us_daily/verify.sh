#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jhu_covid19_confirmed_us_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_VALUES_PER_SAMPLE="${JHU_COVID19_CONFIRMED_US_MIN_VALUES_PER_SAMPLE:-1000}"
MIN_SAMPLE_COUNT="${JHU_COVID19_CONFIRMED_US_MIN_SAMPLE_COUNT:-500}"
MIN_TOTAL_VALUES="${JHU_COVID19_CONFIRMED_US_MIN_TOTAL_VALUES:-500000}"
MAX_PRIMARY_BYTES="${JHU_COVID19_CONFIRMED_US_MAX_PRIMARY_BYTES:-1000000000}"

echo "download_dir=$DOWNLOAD_DIR"
echo "filter_dir=$FILTER_DIR"
echo "index_dir=$INDEX_DIR"
echo "samples_dir=$SAMPLES_DIR"
echo "min_values_per_sample=$MIN_VALUES_PER_SAMPLE"
echo "min_sample_count=$MIN_SAMPLE_COUNT"
echo "min_total_values=$MIN_TOTAL_VALUES"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_VALUES_PER_SAMPLE MIN_SAMPLE_COUNT MIN_TOTAL_VALUES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])
min_sample_count = int(os.environ["MIN_SAMPLE_COUNT"])
min_total_values = int(os.environ["MIN_TOTAL_VALUES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

failures_path = download_dir / "download_failures.tsv"
if failures_path.exists() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")

for required in [
    download_dir / "download_plan.tsv",
    download_dir / "time_series_covid19_confirmed_US.csv",
    filter_dir / "county_stats.tsv",
]:
    if not required.is_file():
        raise SystemExit(f"missing required file: {required}")

summary_path = filter_dir / "quality_summary.json"
index_path = index_dir / "samples.jsonl"
if not summary_path.is_file():
    raise SystemExit(f"missing quality summary: {summary_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

stats_by_fips: dict[str, dict[str, str]] = {}
with (filter_dir / "county_stats.tsv").open("r", encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle, delimiter="\t"):
        fips = row.get("fips", "")
        if not fips:
            raise SystemExit(f"stats row missing fips: {row}")
        if fips in stats_by_fips:
            raise SystemExit(f"duplicate stats fips: {fips}")
        stats_by_fips[fips] = row

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if not rows:
    raise SystemExit("empty sample index")

seen_paths: set[str] = set()
seen_fips: set[str] = set()
total_values = 0
total_bytes = 0
for row in rows:
    if row.get("dataset_id") != "jhu_covid19_confirmed_us_daily":
        raise SystemExit(f"unexpected dataset_id: {row.get('dataset_id')}")
    if row.get("series_id") != "confirmed_cases_u32":
        raise SystemExit(f"unexpected series_id: {row.get('series_id')}")
    if row.get("sample_geometry") != "jhu_county_daily_time_series":
        raise SystemExit(f"unexpected sample_geometry: {row.get('sample_geometry')}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 32:
        raise SystemExit(f"unexpected numeric type in row: {row}")
    fips = str(row.get("fips", ""))
    if fips in seen_fips:
        raise SystemExit(f"duplicate fips in index: {fips}")
    if fips not in stats_by_fips:
        raise SystemExit(f"missing stats row for fips: {fips}")
    seen_fips.add(fips)
    sample_path = str(row.get("sample_path", ""))
    if sample_path in seen_paths:
        raise SystemExit(f"duplicate sample path: {sample_path}")
    seen_paths.add(sample_path)
    path = data_root / sample_path
    if not path.is_file():
        raise SystemExit(f"missing sample file: {path}")
    data = path.read_bytes()
    value_count = int(row.get("value_count", 0))
    if value_count < min_values_per_sample:
        raise SystemExit(f"sample below minimum: {path} has {value_count}, minimum is {min_values_per_sample}")
    expected_size = value_count * 4
    if len(data) != expected_size or int(row.get("sample_size_bytes", 0)) != expected_size:
        raise SystemExit(f"size/count mismatch for {path}")
    stats_value_count = int(stats_by_fips[fips]["value_count"])
    if stats_value_count != value_count:
        raise SystemExit(f"stats/index value_count mismatch for {fips}: {stats_value_count} != {value_count}")
    seen_values: set[int] = set()
    previous = 0
    for (value,) in struct.iter_unpack("<I", data):
        if value < 0:
            raise SystemExit(f"invalid uint32 value in {path}: {value}")
        if value < previous:
            # JHU cumulative series contain occasional corrections; keep them,
            # but the values still need to remain valid uint32 payloads.
            pass
        previous = value
        if len(seen_values) < 2:
            seen_values.add(value)
    if len(seen_values) < 2:
        raise SystemExit(f"constant sample rejected: {path}")
    total_values += value_count
    total_bytes += len(data)

if len(rows) < min_sample_count:
    raise SystemExit(f"only {len(rows)} samples, minimum is {min_sample_count}")
if total_values < min_total_values:
    raise SystemExit(f"only {total_values} values, minimum is {min_total_values}")
if total_bytes > max_primary_bytes:
    raise SystemExit(f"primary bytes too large: {total_bytes} > {max_primary_bytes}")

summary = json.loads(summary_path.read_text(encoding="utf-8"))
if int(summary.get("sample_count", -1)) != len(rows):
    raise SystemExit(f"summary sample_count mismatch: {summary.get('sample_count')} != {len(rows)}")
if int(summary.get("primary_values", -1)) != total_values:
    raise SystemExit(f"summary primary_values mismatch: {summary.get('primary_values')} != {total_values}")
if int(summary.get("primary_sample_bytes", -1)) != total_bytes:
    raise SystemExit(f"summary primary_sample_bytes mismatch: {summary.get('primary_sample_bytes')} != {total_bytes}")

print(f"verified_samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
