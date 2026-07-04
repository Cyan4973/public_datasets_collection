#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="nasa_power_daily_precip_temperature"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}
START_YEAR=${NASA_POWER_DAILY_PRECIP_TEMPERATURE_START_YEAR:-1981}
END_YEAR=${NASA_POWER_DAILY_PRECIP_TEMPERATURE_END_YEAR:-2024}
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

say "dataset=${DATASET_ID}"
say "run_ts=${RUN_TS}"
say "download_root=${DOWNLOAD_ROOT}"
say "log_file=${LOG_FILE}"
say "year_window=${START_YEAR}..${END_YEAR}"

python3 - <<'PY' "${PLAN_FILE}" "${START_YEAR}" "${END_YEAR}"
from __future__ import annotations

from pathlib import Path
import sys
import urllib.parse

plan_path = Path(sys.argv[1])
start_year = int(sys.argv[2])
end_year = int(sys.argv[3])
base_url = "https://power.larc.nasa.gov/api/temporal/daily/point"
locations = [
    ("san_francisco", "37.7749", "-122.4194"),
    ("phoenix", "33.4484", "-112.0740"),
    ("chicago", "41.8781", "-87.6298"),
    ("miami", "25.7617", "-80.1918"),
    ("anchorage", "61.2181", "-149.9003"),
    ("fairbanks", "64.8378", "-147.7164"),
    ("honolulu", "21.3069", "-157.8583"),
    ("denver", "39.7392", "-104.9903"),
    ("new_orleans", "29.9511", "-90.0715"),
    ("san_juan", "18.4655", "-66.1057"),
    ("seattle", "47.6062", "-122.3321"),
    ("boston", "42.3601", "-71.0589"),
    ("atlanta", "33.7490", "-84.3880"),
    ("dallas", "32.7767", "-96.7970"),
    ("minneapolis", "44.9778", "-93.2650"),
    ("las_vegas", "36.1699", "-115.1398"),
    ("albuquerque", "35.0844", "-106.6504"),
    ("portland", "45.5152", "-122.6784"),
    ("billings", "45.7833", "-108.5007"),
    ("fargo", "46.8772", "-96.7898"),
]
if start_year > end_year:
    raise SystemExit(f"invalid year window: {start_year}..{end_year}")
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for location_id, lat, lon in locations:
        for year in range(start_year, end_year + 1):
            params = {
                "parameters": "PRECTOTCORR",
                "community": "RE",
                "longitude": lon,
                "latitude": lat,
                "start": f"{year}0101",
                "end": f"{year}1231",
                "format": "JSON",
                "time-standard": "UTC",
            }
            url = base_url + "?" + urllib.parse.urlencode(params)
            out = f"{location_id}_{year}.json"
            plan_file.write(f"{location_id}\t{year}\t{lat}\t{lon}\t{url}\t{out}\n")
PY

validate_payload() {
  path=$1
  python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
params = payload.get("properties", {}).get("parameter")
if not isinstance(params, dict):
    raise SystemExit(f"missing properties.parameter in {path}")
values = params.get("PRECTOTCORR")
if not isinstance(values, dict) or not values:
    raise SystemExit(f"missing or empty parameter PRECTOTCORR in {path}")
PY
}

fetch() {
  url=$1
  out=$2
  tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_payload "${out}"; then
      return 2
    fi
    rm -f "${out}"
  fi
  rm -f "${tmp}"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fL --retry 3 --retry-delay 5 -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1; then
      rm -f "${tmp}"
      return 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1; then
      rm -f "${tmp}"
      return 1
    fi
  else
    printf 'error: need curl or wget\n' >&2
    exit 1
  fi
  if ! validate_payload "${tmp}"; then
    rm -f "${tmp}"
    return 1
  fi
  mv "${tmp}" "${out}"
  return 0
}

success_count=0
cached_count=0
failure_count=0
while IFS='	' read -r location year lat lon url rel_out; do
  [ -n "${location}" ] || continue
  out="${DOWNLOAD_ROOT}/${rel_out}"
  say "fetch ${location} ${year} ${url}"
  if fetch "${url}" "${out}"; then
    success_count=$((success_count + 1))
    say "ok ${location} ${year} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      cached_count=$((cached_count + 1))
      say "cached ${location} ${year} ${out}"
    else
      failure_count=$((failure_count + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "${location}" "${year}" "${lat}" "${lon}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed ${location} ${year} ${url}"
    fi
  fi
done < "${PLAN_FILE}"

find "${DOWNLOAD_ROOT}" -maxdepth 1 -type f -name '*.json' -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
say "success_count=${success_count}"
say "cached_count=${cached_count}"
say "failure_count=${failure_count}"
say "plan_file=${PLAN_FILE}"
say "failures_file=${FAILURES_FILE}"
say "checksum_file=${CHECKSUM_FILE}"
if [ "${failure_count}" -gt 0 ]; then
  say "download completed with failures"
  exit 1
fi
say "downloaded recipe inputs under ${DOWNLOAD_ROOT}"
