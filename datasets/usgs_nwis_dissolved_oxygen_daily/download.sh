#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="usgs_nwis_dissolved_oxygen_daily"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}
BASE_URL="https://waterservices.usgs.gov/nwis/dv/"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
FAILURES_FILE="${DOWNLOAD_ROOT}/download_failures.tsv"
PLAN_FILE="${DOWNLOAD_ROOT}/download_plan.tsv"
CHECKSUM_FILE="${DOWNLOAD_ROOT}/collection_checksums.sha256"
mkdir -p "${DOWNLOAD_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"; : > "${FAILURES_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT
say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }
say "dataset=${DATASET_ID}"; say "run_ts=${RUN_TS}"; say "download_root=${DOWNLOAD_ROOT}"; say "log_file=${LOG_FILE}"
python3 - <<'PY' "${PLAN_FILE}"
from __future__ import annotations
from pathlib import Path
import sys, urllib.parse
plan_path = Path(sys.argv[1]); base_url = "https://waterservices.usgs.gov/nwis/dv/"; sites = ["07374000"]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
 for site in sites:
  for year in range(2021, 2024):
   params = {"format":"json","sites":site,"parameterCd":"00300","siteStatus":"all","startDT":f"{year}-01-01","endDT":f"{year}-12-31"}
   url = base_url + "?" + urllib.parse.urlencode(params); out = f"dv_{site}_{year}.json"; plan_file.write(f"{site}\t{year}\t{url}\t{out}\n")
PY
validate_payload() {
 path=$1
 python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
time_series = payload.get("value", {}).get("timeSeries", [])
if not isinstance(time_series, list) or not time_series:
    raise SystemExit(f"no timeSeries data in {path}")
for series in time_series:
    values_wrappers = series.get("values", [])
    if not isinstance(values_wrappers, list) or not values_wrappers:
        continue
    rows = values_wrappers[0].get("value", [])
    if isinstance(rows, list) and rows:
        raise SystemExit(0)
raise SystemExit(f"no usable value rows in {path}")
PY
}
fetch() {
 url=$1; out=$2; tmp="${out}.tmp"
 if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
  if validate_payload "${out}"; then return 2; fi
  rm -f "${out}"
 fi
 rm -f "${tmp}"
 if command -v curl >/dev/null 2>&1; then
  if ! curl -fL --retry 3 --retry-delay 5 -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1; then rm -f "${tmp}"; return 1; fi
 elif command -v wget >/dev/null 2>&1; then
  if ! wget -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1; then rm -f "${tmp}"; return 1; fi
 else printf 'error: need curl or wget\n' >&2; exit 1; fi
 if ! validate_payload "${tmp}"; then rm -f "${tmp}"; return 1; fi
 mv "${tmp}" "${out}"; return 0
}
success_count=0; cached_count=0; failure_count=0
while IFS='	' read -r site year url rel_out; do
 [ -n "${site}" ] || continue
 out="${DOWNLOAD_ROOT}/${rel_out}"; say "fetch ${site} ${year} ${url}"
 if fetch "${url}" "${out}"; then success_count=$((success_count + 1)); say "ok ${site} ${year} ${out}"
 else status=$?; if [ "${status}" -eq 2 ]; then cached_count=$((cached_count + 1)); say "cached ${site} ${year} ${out}"
 else failure_count=$((failure_count + 1)); rm -f "${out}" "${out}.tmp"; printf '%s\t%s\t%s\t%s\n' "${site}" "${year}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"; say "failed ${site} ${year} ${url}"; fi; fi
done < "${PLAN_FILE}"
find "${DOWNLOAD_ROOT}" -maxdepth 1 -type f -name 'dv_*.json' -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
say "success_count=${success_count}"; say "cached_count=${cached_count}"; say "failure_count=${failure_count}"; say "plan_file=${PLAN_FILE}"; say "failures_file=${FAILURES_FILE}"; say "checksum_file=${CHECKSUM_FILE}"
if [ "${failure_count}" -gt 0 ]; then say "download completed with failures"; exit 1; fi
say "downloaded recipe inputs under ${DOWNLOAD_ROOT}"
