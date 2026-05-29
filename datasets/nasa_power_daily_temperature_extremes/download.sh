#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="nasa_power_daily_temperature_extremes"
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

say "dataset=${DATASET_ID}"
say "run_ts=${RUN_TS}"
say "download_root=${DOWNLOAD_ROOT}"
say "log_file=${LOG_FILE}"

python3 - <<'PY' "${PLAN_FILE}"
from __future__ import annotations
from pathlib import Path
import sys, urllib.parse

plan_path = Path(sys.argv[1])
base_url = "https://power.larc.nasa.gov/api/temporal/daily/point"
locations = [
    ("san_francisco", "37.7749", "-122.4194"),
    ("phoenix", "33.4484", "-112.0740"),
    ("chicago", "41.8781", "-87.6298"),
    ("miami", "25.7617", "-80.1918"),
    ("anchorage", "61.2181", "-149.9003"),
]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for location_id, lat, lon in locations:
        for year in range(2021, 2024):
            params = {
                "parameters": "T2M,T2M_MAX,T2M_MIN",
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
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
params = payload.get("properties", {}).get("parameter")
if not isinstance(params, dict):
    raise SystemExit(f"missing properties.parameter in {path}")
for key in ["T2M", "T2M_MAX", "T2M_MIN"]:
    values = params.get(key)
    if not isinstance(values, dict) or not values:
        raise SystemExit(f"missing or empty parameter {key} in {path}")
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
    curl -fL --retry 3 --retry-delay 5 -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  else
    printf 'error: need curl or wget\n' >&2
    exit 1
  fi
  validate_payload "${tmp}"
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
