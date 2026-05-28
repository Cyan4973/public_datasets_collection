#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="earthquake_usgs"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}

BASE_URL="https://earthquake.usgs.gov/fdsnws/event/1/query"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
FAILURES_FILE="${DOWNLOAD_ROOT}/download_failures.tsv"
PLAN_FILE="${DOWNLOAD_ROOT}/download_plan.tsv"
CHECKSUM_FILE="${DOWNLOAD_ROOT}/collection_checksums.sha256"

mkdir -p "${DOWNLOAD_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
: > "${FAILURES_FILE}"
sync_latest_log() {
  cp "${LOG_FILE}" "${LATEST_LOG}"
}
trap sync_latest_log EXIT

say() {
  printf '%s\n' "$*" | tee -a "${LOG_FILE}"
}

say "dataset=${DATASET_ID}"
say "run_ts=${RUN_TS}"
say "download_root=${DOWNLOAD_ROOT}"
say "log_file=${LOG_FILE}"

python3 - <<'PY' "${PLAN_FILE}"
from __future__ import annotations

from pathlib import Path
import sys
import urllib.parse

plan_path = Path(sys.argv[1])
base_url = "https://earthquake.usgs.gov/fdsnws/event/1/query"

with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for year in range(2014, 2024):
        params = {
            "format": "csv",
            "starttime": f"{year}-01-01T00:00:00",
            "endtime": f"{year}-12-31T23:59:59.999",
            "minmagnitude": "4.0",
            "orderby": "time",
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        out = f"quakes_{year}.csv"
        plan_file.write(f"{year}\t{url}\t{out}\n")
PY

fetch() {
  url=$1
  out=$2
  tmp="${out}.tmp"

  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    return 2
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
  mv "${tmp}" "${out}"
  return 0
}

success_count=0
cached_count=0
failure_count=0

while IFS='	' read -r year url rel_out; do
  [ -n "${year}" ] || continue
  out="${DOWNLOAD_ROOT}/${rel_out}"
  say "fetch ${year} ${url}"
  if fetch "${url}" "${out}"; then
    success_count=$((success_count + 1))
    say "ok ${year} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      cached_count=$((cached_count + 1))
      say "cached ${year} ${out}"
    else
      failure_count=$((failure_count + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\n' "${year}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed ${year} ${url}"
    fi
  fi
done < "${PLAN_FILE}"

find "${DOWNLOAD_ROOT}" -maxdepth 1 -type f -name 'quakes_*.csv' -print0 \
  | sort -z \
  | xargs -0 sha256sum > "${CHECKSUM_FILE}"

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
