#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/usgs_nwis_streamflow_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/usgs_nwis_streamflow_daily"
INDEX_ROOT="${DATA_DIR}/index/usgs_nwis_streamflow_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/usgs_nwis_streamflow_daily"
LOG_ROOT="${DATA_DIR}/logs/usgs_nwis_streamflow_daily"
MIN_VALUES_PER_SAMPLE=${USGS_NWIS_STREAMFLOW_MIN_VALUES_PER_SAMPLE:-7000}
MIN_SAMPLE_COUNT=${USGS_NWIS_STREAMFLOW_MIN_SAMPLE_COUNT:-20}
MIN_TOTAL_VALUES=${USGS_NWIS_STREAMFLOW_MIN_TOTAL_VALUES:-150000}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT

say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

say "download_root=${DOWNLOAD_ROOT}"
say "filtered_root=${FILTERED_ROOT}"
say "index_root=${INDEX_ROOT}"
say "samples_root=${SAMPLES_ROOT}"
say "min_values_per_sample=${MIN_VALUES_PER_SAMPLE}"
say "min_sample_count=${MIN_SAMPLE_COUNT}"
say "min_total_values=${MIN_TOTAL_VALUES}"
say "log_file=${LOG_FILE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" \
FILTERED_ROOT="${FILTERED_ROOT}" \
INDEX_ROOT="${INDEX_ROOT}" \
SAMPLES_ROOT="${SAMPLES_ROOT}" \
MIN_VALUES_PER_SAMPLE="${MIN_VALUES_PER_SAMPLE}" \
MIN_SAMPLE_COUNT="${MIN_SAMPLE_COUNT}" \
MIN_TOTAL_VALUES="${MIN_TOTAL_VALUES}" \
python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import json
import os
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])
min_sample_count = int(os.environ["MIN_SAMPLE_COUNT"])
min_total_values = int(os.environ["MIN_TOTAL_VALUES"])
data_root = samples_root.parent.parent

failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")

plan_path = download_root / "download_plan.tsv"
if not plan_path.is_file():
    raise SystemExit(f"missing download plan: {plan_path}")

stats_path = filtered_root / "site_stats.tsv"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")

summary_path = filtered_root / "quality_summary.json"
if not summary_path.is_file():
    raise SystemExit(f"missing quality summary: {summary_path}")

index_path = index_root / "samples.jsonl"
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

with index_path.open("r", encoding="utf-8") as handle:
    records = [json.loads(line) for line in handle if line.strip()]

if not records:
    raise SystemExit("sample index is empty; no sites cleared the quality threshold")

seen_keys: set[tuple[str, str]] = set()
total_values = 0
for record in records:
    series_id = record.get("series_id", "")
    if series_id != "usgs_discharge_cfs_f64":
        raise SystemExit(f"unexpected series_id in index: {series_id}")
    sample_path_str = record.get("sample_path", "")
    if not sample_path_str:
        raise SystemExit(f"index record missing sample_path: {record}")
    key = (series_id, sample_path_str)
    if key in seen_keys:
        raise SystemExit(f"duplicate index entry for {key}")
    seen_keys.add(key)
    sample_path = data_root / sample_path_str
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    actual_size = sample_path.stat().st_size
    expected_size = int(record.get("sample_size_bytes", 0))
    if actual_size != expected_size:
        raise SystemExit(f"size mismatch for {sample_path}: expected {expected_size}, got {actual_size}")
    value_count = int(record.get("value_count", 0))
    if value_count < min_values_per_sample:
        raise SystemExit(
            f"sample below minimum value count: {sample_path} has {value_count}, "
            f"minimum is {min_values_per_sample}"
        )
    element_size = int(record.get("element_size_bytes", 1))
    expected_bytes = value_count * element_size
    if actual_size != expected_bytes:
        raise SystemExit(f"count/size mismatch for {sample_path}: {value_count} x {element_size} = {expected_bytes}, got {actual_size}")
    total_values += value_count

sample_count = len(records)
if sample_count < min_sample_count:
    raise SystemExit(f"only {sample_count} samples, minimum is {min_sample_count}")
if total_values < min_total_values:
    raise SystemExit(f"only {total_values} total values, minimum is {min_total_values}")

summary = json.loads(summary_path.read_text(encoding="utf-8"))
if int(summary.get("sample_count", -1)) != sample_count:
    raise SystemExit(f"quality summary sample_count mismatch: {summary.get('sample_count')} != {sample_count}")
if int(summary.get("total_values", -1)) != total_values:
    raise SystemExit(f"quality summary total_values mismatch: {summary.get('total_values')} != {total_values}")

print(
    f"verified {sample_count} streamflow samples, {total_values} values, "
    f"all samples >= {min_values_per_sample} values"
)
PY

say "verified raw inventory, quality thresholds, generated sample sizes, stats, and sample index"
