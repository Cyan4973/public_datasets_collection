#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/usgs_nwis_ph_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/usgs_nwis_ph_daily"
INDEX_ROOT="${DATA_DIR}/index/usgs_nwis_ph_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/usgs_nwis_ph_daily"
LOG_ROOT="${DATA_DIR}/logs/usgs_nwis_ph_daily"
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
import csv, json, os
from pathlib import Path
download_root = Path(os.environ["DOWNLOAD_ROOT"]); filtered_root = Path(os.environ["FILTERED_ROOT"]); index_root = Path(os.environ["INDEX_ROOT"]); samples_root = Path(os.environ["SAMPLES_ROOT"]); data_root = samples_root.parent.parent
stats_path = filtered_root / "site_year_stats.tsv"; index_path = index_root / "samples.jsonl"; failures_path = download_root / "download_failures.tsv"
site_ids = ["07374000"]
series_defs = [
 {"series_id":"usgs_ph_f64","numeric_kind":"float","bit_width":64,"endianness":"little","element_size_bytes":8},
 {"series_id":"obs_year_u16","numeric_kind":"uint","bit_width":16,"endianness":"little","element_size_bytes":2},
 {"series_id":"obs_month_u8","numeric_kind":"uint","bit_width":8,"endianness":"little","element_size_bytes":1},
 {"series_id":"obs_day_u8","numeric_kind":"uint","bit_width":8,"endianness":"little","element_size_bytes":1},
]
if failures_path.is_file() and failures_path.stat().st_size > 0: raise SystemExit(f"download failures recorded in {failures_path}")
if not stats_path.is_file(): raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file(): raise SystemExit(f"missing sample index: {index_path}")
with stats_path.open("r", encoding="utf-8", newline="") as handle: stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_key = {(row["site_id"], row["year"]): row for row in stats_rows}; expected_records = {}
for site_id in site_ids:
 total_values = 0
 for year in range(2021, 2024):
  json_path = download_root / f"dv_{site_id}_{year}.json"
  if not json_path.is_file(): raise SystemExit(f"missing raw JSON: {json_path}")
  if json_path.stat().st_size <= 0: raise SystemExit(f"empty raw JSON: {json_path}")
  payload = json.loads(json_path.read_text(encoding="utf-8"))
  time_series = payload.get("value", {}).get("timeSeries", [])
  if not time_series: raise SystemExit(f"no timeSeries data in {json_path}")
  selected_series = None
  for candidate in time_series:
   name = str(candidate.get("name", ""))
   if name.endswith(":00003"): selected_series = candidate; break
  if selected_series is None: selected_series = time_series[0]
  values_wrappers = selected_series.get("values", [])
  if not values_wrappers: raise SystemExit(f"no values data in {json_path}")
  rows = values_wrappers[0].get("value", [])
  if not isinstance(rows, list): raise SystemExit(f"unexpected values payload in {json_path}")
  row_count = len(rows); value_count = skipped_count = 0; first_date = last_date = ""
  for row in rows:
   raw_value = str(row.get("value", "")).strip(); raw_date = str(row.get("dateTime", "")).strip()
   if raw_value == "" or raw_date == "": skipped_count += 1; continue
   try: float(raw_value)
   except ValueError: skipped_count += 1; continue
   date_part = raw_date[:10]; pieces = date_part.split("-")
   if len(pieces) != 3: skipped_count += 1; continue
   try: obs_year = int(pieces[0]); obs_month = int(pieces[1]); obs_day = int(pieces[2])
   except ValueError: skipped_count += 1; continue
   if obs_year < 0 or obs_year > 65535 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31: skipped_count += 1; continue
   value_count += 1; total_values += 1
   if first_date == "": first_date = date_part
   last_date = date_part
  stats_row = stats_by_key.get((site_id, str(year)))
  if stats_row is None: raise SystemExit(f"missing stats row for {site_id} {year}")
  if int(stats_row["row_count"]) != row_count: raise SystemExit(f"row count mismatch for {site_id} {year}: stats={stats_row['row_count']} raw={row_count}")
  if int(stats_row["value_count"]) != value_count: raise SystemExit(f"value count mismatch for {site_id} {year}: stats={stats_row['value_count']} raw={value_count}")
  if int(stats_row["skipped_count"]) != skipped_count: raise SystemExit(f"skipped count mismatch for {site_id} {year}: stats={stats_row['skipped_count']} raw={skipped_count}")
  if stats_row["start_date"] != first_date: raise SystemExit(f"start date mismatch for {site_id} {year}: stats={stats_row['start_date']!r} raw={first_date!r}")
  if stats_row["end_date"] != last_date: raise SystemExit(f"end date mismatch for {site_id} {year}: stats={stats_row['end_date']!r} raw={last_date!r}")
  if stats_row["series_name"] != str(selected_series.get("name", "")): raise SystemExit(f"series name mismatch for {site_id} {year}: stats={stats_row['series_name']!r} raw={str(selected_series.get('name', ''))!r}")
 site_slug = f"site_{site_id}"
 for series in series_defs:
  sample_path = samples_root / series["series_id"] / f"{site_slug}.bin"
  if not sample_path.is_file(): raise SystemExit(f"missing sample file: {sample_path}")
  sample_size_bytes = sample_path.stat().st_size; expected_size = total_values * int(series["element_size_bytes"])
  if sample_size_bytes != expected_size: raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
  expected_records[(series["series_id"], site_slug)] = {"dataset_id": "usgs_nwis_ph_daily", "series_id": series["series_id"], "sample_path": sample_path.relative_to(data_root).as_posix(), "numeric_kind": series["numeric_kind"], "bit_width": series["bit_width"], "endianness": series["endianness"], "element_size_bytes": series["element_size_bytes"], "sample_size_bytes": sample_size_bytes, "value_count": total_values}
index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
 for line_number, line in enumerate(handle, start=1):
  if not line.strip(): continue
  record = json.loads(line); sample_path = record.get("sample_path"); sample_key = Path(sample_path).stem if isinstance(sample_path, str) else ""; key = (record.get("series_id"), sample_key)
  if key in index_records: raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
  index_records[key] = record
if set(index_records) != set(expected_records): raise SystemExit(f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_records)}")
for key, expected in expected_records.items():
 record = index_records[key]
 for field, expected_value in expected.items():
  if record.get(field) != expected_value: raise SystemExit(f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}")
print("verified raw inventory, generated sample sizes, stats, and sample index")
PY
say "verified raw inventory, generated sample sizes, stats, and sample index"
