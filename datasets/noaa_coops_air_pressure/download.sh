#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="noaa_coops_air_pressure"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
FAILURES_FILE="${DOWNLOAD_ROOT}/download_failures.tsv"
PLAN_FILE="${DOWNLOAD_ROOT}/download_plan.tsv"
CHECKSUM_FILE="${DOWNLOAD_ROOT}/collection_checksums.sha256"
mkdir -p "${DOWNLOAD_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
: > "${FAILURES_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT
say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }
say "dataset=${DATASET_ID}"; say "run_ts=${RUN_TS}"; say "download_root=${DOWNLOAD_ROOT}"; say "log_file=${LOG_FILE}"
python3 - <<'PY' "${PLAN_FILE}"
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import sys, urllib.parse
plan_path = Path(sys.argv[1]); api_url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
stations = [
 ("9414290", "san_francisco", "noaa_coops_9414290_san_francisco"),
 ("8518750", "the_battery", "noaa_coops_8518750_the_battery"),
 ("8443970", "boston", "noaa_coops_8443970_boston"),
]
begin = datetime.strptime("20220101", "%Y%m%d"); end = datetime.strptime("20231231", "%Y%m%d"); chunk_days = 30
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
 for station_id, slug, family in stations:
  current = begin
  while current <= end:
   chunk_end = min(current + timedelta(days=chunk_days - 1), end)
   begin_date = current.strftime("%Y%m%d"); end_date = chunk_end.strftime("%Y%m%d")
   params = {"product":"air_pressure","application":"openzl_public_datasets_collection","begin_date":begin_date,"end_date":end_date,"station":station_id,"time_zone":"gmt","units":"metric","format":"json"}
   url = api_url + "?" + urllib.parse.urlencode(params)
   out = f"{family}/{family}_{begin_date}_{end_date}.json"
   plan_file.write("\t".join([station_id, slug, family, begin_date, end_date, url, out]) + "\n")
   current = chunk_end + timedelta(days=1)
PY
fetch() {
 url=$1; out=$2; tmp="${out}.tmp"
 if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
  if python3 - <<'PY' "${out}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if "error" in payload:
    raise SystemExit(f"cached API error payload in {path}: {payload['error']}")
rows = payload.get("data")
if not isinstance(rows, list) or not rows:
    raise SystemExit(f"cached payload missing non-empty data[] in {path}")
PY
  then
   return 2
  fi
  rm -f "${out}"
 fi
 mkdir -p "$(dirname "${out}")"; rm -f "${tmp}"
 if command -v curl >/dev/null 2>&1; then curl -fL --retry 3 --retry-delay 2 -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
 elif command -v wget >/dev/null 2>&1; then wget -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
 else printf 'error: need curl or wget\n' >&2; exit 1; fi
 python3 - <<'PY' "${tmp}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if "error" in payload:
    raise SystemExit(f"API error payload in {path}: {payload['error']}")
rows = payload.get("data")
if not isinstance(rows, list) or not rows:
    raise SystemExit(f"payload missing non-empty data[] in {path}")
PY
 mv "${tmp}" "${out}"; return 0
}
success_count=0; cached_count=0; failure_count=0
while IFS='	' read -r station_id slug family begin_date end_date url rel_out; do
 [ -n "${station_id}" ] || continue
 out="${DOWNLOAD_ROOT}/${rel_out}"; say "fetch ${station_id} ${slug} ${begin_date} ${end_date} ${url}"
 if fetch "${url}" "${out}"; then success_count=$((success_count + 1)); say "ok ${station_id} ${slug} ${begin_date} ${end_date} ${out}"
 else status=$?; if [ "${status}" -eq 2 ]; then cached_count=$((cached_count + 1)); say "cached ${station_id} ${slug} ${begin_date} ${end_date} ${out}"
 else failure_count=$((failure_count + 1)); rm -f "${out}" "${out}.tmp"; printf '%s\t%s\t%s\t%s\t%s\t%s\n' "${station_id}" "${slug}" "${begin_date}" "${end_date}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"; say "failed ${station_id} ${slug} ${begin_date} ${end_date} ${url}"; fi; fi
done < "${PLAN_FILE}"
find "${DOWNLOAD_ROOT}" -type f -name '*.json' -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
say "success_count=${success_count}"; say "cached_count=${cached_count}"; say "failure_count=${failure_count}"; say "plan_file=${PLAN_FILE}"; say "failures_file=${FAILURES_FILE}"; say "checksum_file=${CHECKSUM_FILE}"
if [ "${failure_count}" -gt 0 ]; then say "download completed with failures"; exit 1; fi
say "downloaded recipe inputs under ${DOWNLOAD_ROOT}"
