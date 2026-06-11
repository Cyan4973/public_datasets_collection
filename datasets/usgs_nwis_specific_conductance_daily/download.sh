#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="usgs_nwis_specific_conductance_daily"
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
plan_path = Path(sys.argv[1]); base_url = "https://waterservices.usgs.gov/nwis/dv/"; sites = [
    # Northeast / Mid-Atlantic
    "01100000",  # Merrimack R at Lawrence MA
    "01372500",  # Hudson R at Poughkeepsie NY
    "01463500",  # Delaware R at Trenton NJ
    "01481500",  # Brandywine Ck at Wilmington DE
    "01578310",  # Susquehanna R at Conowingo MD
    "01594440",  # Patuxent R at Bowie MD
    "01646500",  # Potomac R at Little Falls MD
    # Southeast
    "02087500",  # Neuse R near Kinston NC
    "02169500",  # Congaree R near Columbia SC
    "02215500",  # Oconee R at Milledgeville GA
    "02335000",  # Chattahoochee R at Atlanta GA
    "02342500",  # Apalachicola R at Chattahoochee FL
    # Midwest
    "04085427",  # Fox R at Green Bay WI
    "04193500",  # Maumee R at Waterville OH
    "05288500",  # Mississippi R at Minneapolis MN
    "05420500",  # Mississippi R at Clinton IA
    "05587450",  # Illinois R at Valley City IL
    "06892350",  # Kansas R at DeSoto KS
    "06934500",  # Missouri R at Hermann MO
    # South / Lower Mississippi
    "07022000",  # Mississippi R at Thebes IL
    "07144200",  # Arkansas R at Wichita KS
    "07374000",  # Mississippi R at Baton Rouge LA
    "07381490",  # Atchafalaya R at Melville LA
    # Great Plains
    "06805500",  # Platte R at Ashland NE
    # South / Texas
    "08158000",  # Colorado R at Austin TX
    # Mountain West
    "09085000",  # Colorado R near Dotsero CO
    "09163500",  # Colorado R near Colorado-Utah line
    # Pacific / West Coast
    "11447650",  # Sacramento R at Sacramento CA
    "12114500",  # Green R at Auburn WA
    "13011900",  # Snake R near Moran WY
    "14048000",  # Deschutes R at Moody OR
    "14211720",  # Willamette R at Portland OR
]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
 for site in sites:
  for year in range(2021, 2024):
   params = {"format":"json","sites":site,"parameterCd":"00095","siteStatus":"all","startDT":f"{year}-01-01","endDT":f"{year}-12-31"}
   url = base_url + "?" + urllib.parse.urlencode(params); out = f"dv_{site}_{year}.json"; plan_file.write(f"{site}\t{year}\t{url}\t{out}\n")
PY
validate_payload() {
 path=$1
 python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"invalid JSON in {path}: {exc}")
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
