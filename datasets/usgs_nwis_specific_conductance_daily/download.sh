#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="usgs_nwis_specific_conductance_daily"
PARAMETER_CD="00095"
PARAMETER_LABEL="specific conductance"
START_YEAR=2021
END_YEAR=2024
TARGET_SITES=50
TARGET_CANDIDATES=250
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
STATE_PLAN_FILE="${DOWNLOAD_ROOT}/state_inventory_plan.tsv"
CANDIDATE_FILE="${DOWNLOAD_ROOT}/candidate_sites.tsv"
SELECTED_FILE="${DOWNLOAD_ROOT}/selected_sites.tsv"
PLAN_FILE="${DOWNLOAD_ROOT}/download_plan.tsv"
CHECKSUM_FILE="${DOWNLOAD_ROOT}/collection_checksums.sha256"
USER_AGENT=${USER_AGENT:-"openzl-public-datasets-collection/1.0"}

mkdir -p "${DOWNLOAD_ROOT}" "${INVENTORY_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
: > "${FAILURES_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT

say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

say "dataset=${DATASET_ID}"
say "parameter_cd=${PARAMETER_CD}"
say "run_ts=${RUN_TS}"
say "download_root=${DOWNLOAD_ROOT}"
say "inventory_root=${INVENTORY_ROOT}"
say "log_file=${LOG_FILE}"

STATE_CODES="${STATE_CODES}" SITE_BASE_URL="${SITE_BASE_URL}" python3 - <<'PY' "${STATE_PLAN_FILE}"
from __future__ import annotations
import os, sys, urllib.parse
from pathlib import Path
plan_path = Path(sys.argv[1])
site_base_url = os.environ["SITE_BASE_URL"]
state_codes = [code.strip().lower() for code in os.environ["STATE_CODES"].split() if code.strip()]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for state_code in state_codes:
        params = {"format":"rdb","siteOutput":"expanded","siteType":"ST","siteStatus":"active","stateCd":state_code}
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
        if line.startswith("#"): continue
        columns = line.rstrip("\n").split("\t")
        if columns and columns[0] == "agency_cd":
            header = columns
            break
if header is None: raise SystemExit(f"missing tabular header in {path}")
required = {"site_no","site_tp_cd","station_nm","instruments_cd","state_cd"}
missing = required.difference(header)
if missing: raise SystemExit(f"missing required columns in {path}: {sorted(missing)}")
PY
}

validate_daily_payload() {
  path=$1
  python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if "value" not in payload: raise SystemExit(f"missing value object in {path}")
PY
}

daily_payload_has_usable_values() {
  path=$1
  python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
time_series = payload.get("value", {}).get("timeSeries", [])
if not time_series: raise SystemExit(1)
selected_series = None
for candidate in time_series:
    if str(candidate.get("name", "")).endswith(":00003"):
        selected_series = candidate
        break
if selected_series is None: selected_series = time_series[0]
for wrapper in selected_series.get("values", []):
    rows = wrapper.get("value", [])
    if not isinstance(rows, list): continue
    for row in rows:
        raw_value = str(row.get("value", "")).strip()
        raw_date = str(row.get("dateTime", "")).strip()
        if raw_value == "" or raw_date == "": continue
        try: float(raw_value)
        except ValueError: continue
        pieces = raw_date[:10].split("-")
        if len(pieces) != 3: continue
        try: year = int(pieces[0]); month = int(pieces[1]); day = int(pieces[2])
        except ValueError: continue
        if year < 0 or year > 65535 or month < 1 or month > 12 or day < 1 or day > 31: continue
        raise SystemExit(0)
raise SystemExit(1)
PY
}

fetch_inventory() {
  url=$1; out=$2; tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_inventory_payload "${out}"; then return 2; fi
    rm -f "${out}"
  fi
  rm -f "${tmp}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 5 -A "${USER_AGENT}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget --user-agent="${USER_AGENT}" -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  else
    printf 'error: need curl or wget\n' >&2; exit 1
  fi
  validate_inventory_payload "${tmp}"
  mv "${tmp}" "${out}"
  return 0
}

fetch_daily() {
  url=$1; out=$2; tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_daily_payload "${out}"; then return 2; fi
    rm -f "${out}"
  fi
  rm -f "${tmp}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 5 -A "${USER_AGENT}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget --user-agent="${USER_AGENT}" -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  else
    printf 'error: need curl or wget\n' >&2; exit 1
  fi
  validate_daily_payload "${tmp}"
  mv "${tmp}" "${out}"
  return 0
}

inventory_success=0; inventory_cached=0; inventory_failures=0
while IFS='	' read -r state_code url rel_out; do
  [ -n "${state_code}" ] || continue
  out="${INVENTORY_ROOT}/${rel_out}"
  say "fetch inventory ${state_code} ${url}"
  if fetch_inventory "${url}" "${out}"; then
    inventory_success=$((inventory_success + 1)); say "ok inventory ${state_code} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      inventory_cached=$((inventory_cached + 1)); say "cached inventory ${state_code} ${out}"
    else
      inventory_failures=$((inventory_failures + 1))
      rm -f "${out}" "${out}.tmp"
      printf 'inventory\t%s\t%s\t%s\n' "${state_code}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed inventory ${state_code} ${url}"
    fi
  fi
done < "${STATE_PLAN_FILE}"
if [ "${inventory_failures}" -gt 0 ]; then say "inventory fetch completed with failures"; exit 1; fi

STATE_CODES="${STATE_CODES}" INVENTORY_ROOT="${INVENTORY_ROOT}" TARGET_CANDIDATES="${TARGET_CANDIDATES}" python3 - <<'PY' "${CANDIDATE_FILE}"
from __future__ import annotations
import csv, os, sys
from pathlib import Path
candidate_path = Path(sys.argv[1]); inventory_root = Path(os.environ["INVENTORY_ROOT"]); target_candidates = int(os.environ["TARGET_CANDIDATES"])
state_codes = [code.strip().lower() for code in os.environ["STATE_CODES"].split() if code.strip()]
per_state = {}
for state_code in state_codes:
    path = inventory_root / f"site_inventory_{state_code}.txt"
    if not path.is_file(): raise SystemExit(f"missing inventory file: {path}")
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        header = None
        for line in handle:
            if line.startswith("#"): continue
            columns = line.rstrip("\n").split("\t")
            if header is None:
                header = columns
                indexes = {name: header.index(name) for name in ["site_no","station_nm","site_tp_cd","instruments_cd","state_cd"]}
                continue
            if columns and columns[0] == "5s": continue
            if len(columns) < len(header): columns += [""] * (len(header) - len(columns))
            site_no = columns[indexes["site_no"]].strip()
            station_nm = columns[indexes["station_nm"]].strip()
            site_tp_cd = columns[indexes["site_tp_cd"]].strip()
            instruments_cd = columns[indexes["instruments_cd"]].strip()
            if not site_no.isdigit() or not site_tp_cd.startswith("ST"): continue
            if instruments_cd == "" or set(instruments_cd) == {"N"}: continue
            rows.append((site_no, station_nm, instruments_cd))
    deduped = []; seen = set()
    for row in sorted(rows):
        if row[0] in seen: continue
        seen.add(row[0]); deduped.append(row)
    per_state[state_code.upper()] = deduped
candidates = []; positions = {state: 0 for state in per_state}
while len(candidates) < target_candidates:
    progressed = False
    for state in sorted(per_state):
        rows = per_state[state]; pos = positions[state]
        if pos >= len(rows): continue
        site_no, station_nm, instruments_cd = rows[pos]
        positions[state] = pos + 1
        candidates.append((len(candidates) + 1, state, site_no, station_nm, instruments_cd))
        progressed = True
        if len(candidates) >= target_candidates: break
    if not progressed: break
with candidate_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["rank","state_code","site_no","station_nm","instruments_cd"])
    for row in candidates: writer.writerow(row)
if len(candidates) < 50: raise SystemExit(f"only {len(candidates)} candidate sites discovered")
PY

printf 'rank\tstate_code\tsite_no\tstation_nm\tinstruments_cd\tusable_years\n' > "${SELECTED_FILE}"
: > "${PLAN_FILE}"
daily_success=0; daily_cached=0; daily_failures=0; selected_count=0
while IFS='	' read -r rank state_code site_no station_nm instruments_cd; do
  [ "${rank}" != "rank" ] || continue
  [ -n "${site_no}" ] || continue
  site_has_data=0; usable_years=""
  for year in $(seq "${START_YEAR}" "${END_YEAR}"); do
    url="${DAILY_BASE_URL}?format=json&sites=${site_no}&parameterCd=${PARAMETER_CD}&siteStatus=all&startDT=${year}-01-01&endDT=${year}-12-31"
    out="${DOWNLOAD_ROOT}/dv_${site_no}_${year}.json"
    say "fetch daily ${site_no} ${year} ${url}"
    if fetch_daily "${url}" "${out}"; then
      daily_success=$((daily_success + 1)); say "ok daily ${site_no} ${year} ${out}"
    else
      status=$?
      if [ "${status}" -eq 2 ]; then
        daily_cached=$((daily_cached + 1)); say "cached daily ${site_no} ${year} ${out}"
      else
        daily_failures=$((daily_failures + 1))
        rm -f "${out}" "${out}.tmp"
        printf 'daily\t%s\t%s\t%s\n' "${site_no}" "${year}" "${url}" >> "${FAILURES_FILE}"
        say "failed daily ${site_no} ${year} ${url}"
        continue
      fi
    fi
    if daily_payload_has_usable_values "${out}"; then
      site_has_data=1
      if [ -z "${usable_years}" ]; then usable_years="${year}"; else usable_years="${usable_years},${year}"; fi
    fi
  done
  if [ "${site_has_data}" -eq 1 ]; then
    selected_count=$((selected_count + 1))
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "${rank}" "${state_code}" "${site_no}" "${station_nm}" "${instruments_cd}" "${usable_years}" >> "${SELECTED_FILE}"
    for year in $(seq "${START_YEAR}" "${END_YEAR}"); do
      url="${DAILY_BASE_URL}?format=json&sites=${site_no}&parameterCd=${PARAMETER_CD}&siteStatus=all&startDT=${year}-01-01&endDT=${year}-12-31"
      rel_out="dv_${site_no}_${year}.json"
      printf '%s\t%s\t%s\t%s\n' "${site_no}" "${year}" "${url}" "${rel_out}" >> "${PLAN_FILE}"
    done
    say "selected site ${site_no} usable_years=${usable_years} selected_count=${selected_count}"
    if [ "${selected_count}" -ge "${TARGET_SITES}" ]; then break; fi
  else
    rm -f "${DOWNLOAD_ROOT}/dv_${site_no}_"*.json
    say "rejected site ${site_no} no usable ${PARAMETER_LABEL} observations across ${START_YEAR}-${END_YEAR}"
  fi
done < "${CANDIDATE_FILE}"
if [ "${daily_failures}" -gt 0 ]; then say "daily fetch completed with failures"; exit 1; fi
if [ "${selected_count}" -lt "${TARGET_SITES}" ]; then
  say "selected_count=${selected_count} target_sites=${TARGET_SITES}"
  say "download completed below the target number of usable sites"
fi
find "${INVENTORY_ROOT}" -maxdepth 1 -type f -name 'site_inventory_*.txt' -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
find "${DOWNLOAD_ROOT}" -maxdepth 1 -type f -name 'dv_*.json' -print0 | sort -z | xargs -0 sha256sum >> "${CHECKSUM_FILE}"
say "inventory_success=${inventory_success}"
say "inventory_cached=${inventory_cached}"
say "inventory_failures=${inventory_failures}"
say "daily_success=${daily_success}"
say "daily_cached=${daily_cached}"
say "daily_failures=${daily_failures}"
say "candidate_file=${CANDIDATE_FILE}"
say "selected_file=${SELECTED_FILE}"
say "plan_file=${PLAN_FILE}"
say "checksum_file=${CHECKSUM_FILE}"
say "downloaded recipe inputs under ${DOWNLOAD_ROOT}"
