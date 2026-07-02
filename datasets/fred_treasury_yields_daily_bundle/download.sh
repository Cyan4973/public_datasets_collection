#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="fred_treasury_yields_daily_bundle"
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
from pathlib import Path
import sys
import urllib.parse

plan_path = Path(sys.argv[1])
base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
start_date = "1962-01-02"
end_date = "2024-12-31"
series = [
    ("DGS1MO", "1mo", "treasury_1mo.csv"),
    ("DGS3MO", "3mo", "treasury_3mo.csv"),
    ("DGS6MO", "6mo", "treasury_6mo.csv"),
    ("DGS1", "1y", "treasury_1y.csv"),
    ("DGS2", "2y", "treasury_2y.csv"),
    ("DGS3", "3y", "treasury_3y.csv"),
    ("DGS5", "5y", "treasury_5y.csv"),
    ("DGS7", "7y", "treasury_7y.csv"),
    ("DGS10", "10y", "treasury_10y.csv"),
    ("DGS20", "20y", "treasury_20y.csv"),
    ("DGS30", "30y", "treasury_30y.csv"),
]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for series_id, maturity, rel_out in series:
        params = {"id": series_id, "cosd": start_date, "coed": end_date}
        url = base_url + "?" + urllib.parse.urlencode(params)
        plan_file.write(f"{series_id}\t{maturity}\t{url}\t{rel_out}\n")
PY

validate_payload() {
  series_id=$1
  path=$2
  python3 - <<'PY' "${series_id}" "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import csv
import sys
from pathlib import Path

series_id = sys.argv[1]
path = Path(sys.argv[2])
with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames != ["observation_date", series_id]:
        raise SystemExit(f"unexpected CSV header in {path}: {reader.fieldnames!r}")
    first = next(reader, None)
    if first is None:
        raise SystemExit(f"empty CSV payload in {path}")
PY
}

fetch() {
  series_id=$1
  url=$2
  out=$3
  tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_payload "${series_id}" "${out}"; then
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
  validate_payload "${series_id}" "${tmp}"
  mv "${tmp}" "${out}"
  return 0
}

success_count=0
cached_count=0
failure_count=0
while IFS='	' read -r series_id maturity url rel_out; do
  [ -n "${series_id}" ] || continue
  out="${DOWNLOAD_ROOT}/${rel_out}"
  say "fetch ${series_id} ${maturity} ${url}"
  if fetch "${series_id}" "${url}" "${out}"; then
    success_count=$((success_count + 1))
    say "ok ${series_id} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      cached_count=$((cached_count + 1))
      say "cached ${series_id} ${out}"
    else
      failure_count=$((failure_count + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\t%s\n' "${series_id}" "${maturity}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed ${series_id} ${url}"
    fi
  fi
done < "${PLAN_FILE}"

find "${DOWNLOAD_ROOT}" -maxdepth 1 -type f -name 'treasury_*.csv' -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
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
