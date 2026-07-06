#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="usgs_nwis_gage_height_daily"
PARAMETER_CD="00065"
PARAMETER_LABEL="gage height"
START_DATE=${USGS_NWIS_GAGE_HEIGHT_START_DATE:-"2000-01-01"}
END_DATE=${USGS_NWIS_GAGE_HEIGHT_END_DATE:-"2024-12-31"}
TARGET_SITES=${USGS_NWIS_GAGE_HEIGHT_TARGET_SITES:-32}
TARGET_CANDIDATES=${USGS_NWIS_GAGE_HEIGHT_TARGET_CANDIDATES:-500}
MIN_VALUES_PER_SAMPLE=${USGS_NWIS_GAGE_HEIGHT_MIN_VALUES_PER_SAMPLE:-7000}
STATE_CODES="AL AK AZ AR CA CO CT DE FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
SITE_BASE_URL="https://waterservices.usgs.gov/nwis/site/"
DAILY_BASE_URL="https://waterservices.usgs.gov/nwis/dv/"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
INVENTORY_ROOT="${DOWNLOAD_ROOT}/site_inventory"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
FAILURES_FILE="${DOWNLOAD_ROOT}/download_failures.tsv"
REJECTIONS_FILE="${DOWNLOAD_ROOT}/candidate_rejections.tsv"
STATE_PLAN_FILE="${DOWNLOAD_ROOT}/state_inventory_plan.tsv"
CANDIDATE_FILE="${DOWNLOAD_ROOT}/candidate_sites.tsv"
SELECTED_FILE="${DOWNLOAD_ROOT}/selected_sites.tsv"
PLAN_FILE="${DOWNLOAD_ROOT}/download_plan.tsv"
CHECKSUM_FILE="${DOWNLOAD_ROOT}/collection_checksums.sha256"
USER_AGENT=${USER_AGENT:-"openzl-public-datasets-collection/1.0"}

mkdir -p "${DOWNLOAD_ROOT}" "${INVENTORY_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
: > "${FAILURES_FILE}"
: > "${REJECTIONS_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT

say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

say "dataset=${DATASET_ID}"
say "parameter_cd=${PARAMETER_CD}"
say "start_date=${START_DATE}"
say "end_date=${END_DATE}"
say "target_sites=${TARGET_SITES}"
say "target_candidates=${TARGET_CANDIDATES}"
say "min_values_per_sample=${MIN_VALUES_PER_SAMPLE}"
say "run_ts=${RUN_TS}"
say "download_root=${DOWNLOAD_ROOT}"
say "inventory_root=${INVENTORY_ROOT}"
say "log_file=${LOG_FILE}"

STATE_CODES="${STATE_CODES}" SITE_BASE_URL="${SITE_BASE_URL}" python3 - <<'PY' "${STATE_PLAN_FILE}"
from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

plan_path = Path(sys.argv[1])
site_base_url = os.environ["SITE_BASE_URL"]
state_codes = [code.strip().lower() for code in os.environ["STATE_CODES"].split() if code.strip()]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for state_code in state_codes:
        params = {
            "format": "rdb",
            "siteOutput": "expanded",
            "siteType": "ST",
            "siteStatus": "active",
            "stateCd": state_code,
        }
        url = site_base_url + "?" + urllib.parse.urlencode(params)
        rel_out = f"site_inventory_{state_code}.txt"
        plan_file.write(f"{state_code}\t{url}\t{rel_out}\n")
PY

validate_inventory_payload() {
  path=$1
  python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
header = None
with path.open("r", encoding="utf-8", errors="replace") as handle:
    for line in handle:
        if line.startswith("#"):
            continue
        columns = line.rstrip("\n").split("\t")
        if columns and columns[0] == "agency_cd":
            header = columns
            break
if header is None:
    raise SystemExit(f"missing tabular header in {path}")
required = {"site_no", "site_tp_cd", "station_nm", "instruments_cd", "state_cd"}
missing = required.difference(header)
if missing:
    raise SystemExit(f"missing required columns in {path}: {sorted(missing)}")
PY
}

validate_daily_payload() {
  path=$1
  python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if "value" not in payload:
    raise SystemExit(f"missing value object in {path}")
PY
}

daily_payload_stats() {
  path=$1
  PARAMETER_CD="${PARAMETER_CD}" python3 - <<'PY' "${path}"
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
parameter_cd = os.environ["PARAMETER_CD"]
payload = json.loads(path.read_text(encoding="utf-8"))
time_series = payload.get("value", {}).get("timeSeries", [])

selected_series = None
for candidate in time_series:
    name = str(candidate.get("name", ""))
    if f":{parameter_cd}:" in name and name.endswith(":00003"):
        selected_series = candidate
        break

value_count = 0
first_date = ""
last_date = ""
series_name = ""
if selected_series is not None:
    series_name = str(selected_series.get("name", ""))
    for wrapper in selected_series.get("values", []):
        rows = wrapper.get("value", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            raw_value = str(row.get("value", "")).strip()
            raw_date = str(row.get("dateTime", "")).strip()
            if raw_value == "" or raw_date == "":
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            date_part = raw_date[:10]
            pieces = date_part.split("-")
            if len(pieces) != 3:
                continue
            try:
                obs_year = int(pieces[0])
                obs_month = int(pieces[1])
                obs_day = int(pieces[2])
            except ValueError:
                continue
            if obs_year < 0 or obs_year > 65535 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                continue
            value_count += 1
            if first_date == "":
                first_date = date_part
            last_date = date_part

print(f"{value_count}\t{first_date}\t{last_date}\t{series_name}")
PY
}

fetch_inventory() {
  url=$1
  out=$2
  tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_inventory_payload "${out}"; then
      return 2
    fi
    rm -f "${out}"
  fi
  rm -f "${tmp}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 5 -A "${USER_AGENT}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget --user-agent="${USER_AGENT}" -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  else
    printf 'error: need curl or wget\n' >&2
    exit 1
  fi
  validate_inventory_payload "${tmp}"
  mv "${tmp}" "${out}"
  return 0
}

fetch_daily() {
  url=$1
  out=$2
  tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_daily_payload "${out}"; then
      return 2
    fi
    rm -f "${out}"
  fi
  rm -f "${tmp}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 5 -A "${USER_AGENT}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget --user-agent="${USER_AGENT}" -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  else
    printf 'error: need curl or wget\n' >&2
    exit 1
  fi
  validate_daily_payload "${tmp}"
  mv "${tmp}" "${out}"
  return 0
}

inventory_success=0
inventory_cached=0
inventory_failures=0
while IFS='	' read -r state_code url rel_out; do
  [ -n "${state_code}" ] || continue
  out="${INVENTORY_ROOT}/${rel_out}"
  say "fetch inventory ${state_code} ${url}"
  if fetch_inventory "${url}" "${out}"; then
    inventory_success=$((inventory_success + 1))
    say "ok inventory ${state_code} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      inventory_cached=$((inventory_cached + 1))
      say "cached inventory ${state_code} ${out}"
    else
      inventory_failures=$((inventory_failures + 1))
      rm -f "${out}" "${out}.tmp"
      printf 'inventory\t%s\t%s\t%s\n' "${state_code}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed inventory ${state_code} ${url}"
    fi
  fi
done < "${STATE_PLAN_FILE}"
if [ "${inventory_failures}" -gt 0 ]; then
  say "inventory fetch completed with failures"
  exit 1
fi

STATE_CODES="${STATE_CODES}" INVENTORY_ROOT="${INVENTORY_ROOT}" TARGET_CANDIDATES="${TARGET_CANDIDATES}" python3 - <<'PY' "${CANDIDATE_FILE}"
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

candidate_path = Path(sys.argv[1])
inventory_root = Path(os.environ["INVENTORY_ROOT"])
target_candidates = int(os.environ["TARGET_CANDIDATES"])
state_codes = [code.strip().lower() for code in os.environ["STATE_CODES"].split() if code.strip()]

per_state: dict[str, list[tuple[str, str, str]]] = {}
for state_code in state_codes:
    path = inventory_root / f"site_inventory_{state_code}.txt"
    if not path.is_file():
        raise SystemExit(f"missing inventory file: {path}")
    rows: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        header = None
        for line in handle:
            if line.startswith("#"):
                continue
            columns = line.rstrip("\n").split("\t")
            if header is None:
                header = columns
                indexes = {
                    name: header.index(name)
                    for name in ["site_no", "station_nm", "site_tp_cd", "instruments_cd", "state_cd"]
                }
                continue
            if columns and columns[0] == "5s":
                continue
            if len(columns) < len(header):
                columns += [""] * (len(header) - len(columns))
            site_no = columns[indexes["site_no"]].strip()
            station_nm = columns[indexes["station_nm"]].strip()
            site_tp_cd = columns[indexes["site_tp_cd"]].strip()
            instruments_cd = columns[indexes["instruments_cd"]].strip()
            if not site_no.isdigit() or not site_tp_cd.startswith("ST"):
                continue
            if instruments_cd == "" or set(instruments_cd) == {"N"}:
                continue
            rows.append((site_no, station_nm, instruments_cd))
    deduped: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in sorted(rows):
        if row[0] in seen:
            continue
        seen.add(row[0])
        deduped.append(row)
    per_state[state_code.upper()] = deduped

candidates: list[tuple[int, str, str, str, str]] = []
positions = {state: 0 for state in per_state}
while len(candidates) < target_candidates:
    progressed = False
    for state in sorted(per_state):
        rows = per_state[state]
        pos = positions[state]
        if pos >= len(rows):
            continue
        site_no, station_nm, instruments_cd = rows[pos]
        positions[state] = pos + 1
        candidates.append((len(candidates) + 1, state, site_no, station_nm, instruments_cd))
        progressed = True
        if len(candidates) >= target_candidates:
            break
    if not progressed:
        break

with candidate_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["rank", "state_code", "site_no", "station_nm", "instruments_cd"])
    for row in candidates:
        writer.writerow(row)
if len(candidates) < target_candidates:
    raise SystemExit(f"only {len(candidates)} candidate sites discovered, target was {target_candidates}")
PY

printf 'rank\tstate_code\tsite_no\tstation_nm\tinstruments_cd\tvalue_count\tstart_date\tend_date\tseries_name\n' > "${SELECTED_FILE}"
printf 'site_no\tstart_date\tend_date\turl\trel_out\n' > "${PLAN_FILE}"

daily_success=0
daily_cached=0
daily_rejections=0
selected_count=0
while IFS='	' read -r rank state_code site_no station_nm instruments_cd; do
  [ "${rank}" != "rank" ] || continue
  [ -n "${site_no}" ] || continue
  if [ "${selected_count}" -ge "${TARGET_SITES}" ]; then
    break
  fi

  rel_out="dv_${site_no}.json"
  out="${DOWNLOAD_ROOT}/${rel_out}"
  url=$(DAILY_BASE_URL="${DAILY_BASE_URL}" PARAMETER_CD="${PARAMETER_CD}" START_DATE="${START_DATE}" END_DATE="${END_DATE}" SITE_NO="${site_no}" python3 - <<'PY'
from __future__ import annotations

import os
import urllib.parse

params = {
    "format": "json",
    "sites": os.environ["SITE_NO"],
    "parameterCd": os.environ["PARAMETER_CD"],
    "siteStatus": "all",
    "startDT": os.environ["START_DATE"],
    "endDT": os.environ["END_DATE"],
}
print(os.environ["DAILY_BASE_URL"] + "?" + urllib.parse.urlencode(params))
PY
)

  say "fetch daily candidate ${site_no} ${url}"
  if fetch_daily "${url}" "${out}"; then
    daily_success=$((daily_success + 1))
    say "ok daily candidate ${site_no} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      daily_cached=$((daily_cached + 1))
      say "cached daily candidate ${site_no} ${out}"
    else
      daily_rejections=$((daily_rejections + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\t%s\tfetch_or_validation_error\t%s\n' "${rank}" "${state_code}" "${site_no}" "${station_nm}" "${url}" >> "${REJECTIONS_FILE}"
      say "rejected candidate ${site_no} fetch_or_validation_error"
      continue
    fi
  fi

  stats=$(daily_payload_stats "${out}")
  value_count=$(printf '%s\n' "${stats}" | awk -F '\t' '{print $1}')
  first_date=$(printf '%s\n' "${stats}" | awk -F '\t' '{print $2}')
  last_date=$(printf '%s\n' "${stats}" | awk -F '\t' '{print $3}')
  series_name=$(printf '%s\n' "${stats}" | awk -F '\t' '{print $4}')

  if [ "${value_count}" -ge "${MIN_VALUES_PER_SAMPLE}" ]; then
    selected_count=$((selected_count + 1))
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${rank}" "${state_code}" "${site_no}" "${station_nm}" "${instruments_cd}" "${value_count}" "${first_date}" "${last_date}" "${series_name}" >> "${SELECTED_FILE}"
    printf '%s\t%s\t%s\t%s\t%s\n' "${site_no}" "${START_DATE}" "${END_DATE}" "${url}" "${rel_out}" >> "${PLAN_FILE}"
    say "selected site ${site_no} value_count=${value_count} range=${first_date}..${last_date} selected_count=${selected_count}"
  else
    daily_rejections=$((daily_rejections + 1))
    rm -f "${out}" "${out}.tmp"
    printf '%s\t%s\t%s\t%s\tvalue_count_%s_below_min_%s\t%s\n' "${rank}" "${state_code}" "${site_no}" "${station_nm}" "${value_count}" "${MIN_VALUES_PER_SAMPLE}" "${url}" >> "${REJECTIONS_FILE}"
    say "rejected candidate ${site_no} value_count=${value_count} below min ${MIN_VALUES_PER_SAMPLE}"
  fi
done < "${CANDIDATE_FILE}"

if [ "${selected_count}" -lt "${TARGET_SITES}" ]; then
  say "selected_count=${selected_count} target_sites=${TARGET_SITES}"
  say "download completed without reaching the target number of long ${PARAMETER_LABEL} sites"
  exit 1
fi

find "${INVENTORY_ROOT}" -maxdepth 1 -type f -name 'site_inventory_*.txt' -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
tail -n +2 "${PLAN_FILE}" | while IFS='	' read -r site_no start_date end_date url rel_out; do
  [ -n "${site_no}" ] || continue
  sha256sum "${DOWNLOAD_ROOT}/${rel_out}"
done >> "${CHECKSUM_FILE}"

say "inventory_success=${inventory_success}"
say "inventory_cached=${inventory_cached}"
say "inventory_failures=${inventory_failures}"
say "daily_success=${daily_success}"
say "daily_cached=${daily_cached}"
say "daily_rejections=${daily_rejections}"
say "candidate_file=${CANDIDATE_FILE}"
say "selected_file=${SELECTED_FILE}"
say "rejections_file=${REJECTIONS_FILE}"
say "plan_file=${PLAN_FILE}"
say "checksum_file=${CHECKSUM_FILE}"
say "downloaded recipe inputs under ${DOWNLOAD_ROOT}"
