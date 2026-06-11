#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/usgs_nwis_specific_conductance_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/usgs_nwis_specific_conductance_daily"
INDEX_ROOT="${DATA_DIR}/index/usgs_nwis_specific_conductance_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/usgs_nwis_specific_conductance_daily"
LOG_ROOT="${DATA_DIR}/logs/usgs_nwis_specific_conductance_daily"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"
mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT
say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }
say "download_root=${DOWNLOAD_ROOT}"; say "filtered_root=${FILTERED_ROOT}"; say "index_root=${INDEX_ROOT}"; say "samples_root=${SAMPLES_ROOT}"; say "log_file=${LOG_FILE}"
DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, os
from pathlib import Path
download_root = Path(os.environ["DOWNLOAD_ROOT"]); filtered_root = Path(os.environ["FILTERED_ROOT"]); index_root = Path(os.environ["INDEX_ROOT"]); samples_root = Path(os.environ["SAMPLES_ROOT"]); data_root = samples_root.parent.parent
failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0: raise SystemExit(f"download failures recorded in {failures_path}")
stats_path = filtered_root / "site_year_stats.tsv"
if not stats_path.is_file(): raise SystemExit(f"missing stats file: {stats_path}")
index_path = index_root / "samples.jsonl"
if not index_path.is_file(): raise SystemExit(f"missing sample index: {index_path}")
with index_path.open("r", encoding="utf-8") as handle: records = [json.loads(line) for line in handle if line.strip()]
if not records: raise SystemExit("sample index is empty — no sites produced usable data")
seen_keys: set[tuple[str, str]] = set()
for record in records:
 series_id = record.get("series_id", ""); sample_path_str = record.get("sample_path", "")
 if not sample_path_str: raise SystemExit(f"index record missing sample_path: {record}")
 key = (series_id, sample_path_str)
 if key in seen_keys: raise SystemExit(f"duplicate index entry for {key}")
 seen_keys.add(key)
 sample_path = data_root / sample_path_str
 if not sample_path.is_file(): raise SystemExit(f"missing sample file: {sample_path}")
 actual_size = sample_path.stat().st_size; expected_size = record.get("sample_size_bytes")
 if actual_size != expected_size: raise SystemExit(f"size mismatch for {sample_path}: expected {expected_size}, got {actual_size}")
 value_count = record.get("value_count", 0); element_size = record.get("element_size_bytes", 1); expected_bytes = value_count * element_size
 if actual_size != expected_bytes: raise SystemExit(f"count/size mismatch for {sample_path}: {value_count} x {element_size} = {expected_bytes}, got {actual_size}")
sites_verified = len({r["sample_path"].split("/")[-1] for r in records if r.get("series_id") == "usgs_specific_conductance_f64"})
print(f"verified {len(records)} index records across {sites_verified} sites, all sample files present and correct sizes")
PY
say "verified index records, all sample files present and correct sizes"
