#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="noaa_ghcn_daily_tsun_by_station"
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
import sys

plan_path = Path(sys.argv[1])
base_url = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
stations = [
    "USC00011084",
    "USC00024849",
    "USC00034756",
    "USC00043761",
    "USC00047916",
    "USC00053038",
    "USC00079605",
    "USC00091500",
    "USC00101408",
    "USC00110072",
    "USC00115943",
    "USC00122149",
    "USC00129113",
    "USC00137147",
    "USC00144972",
    "USC00158709",
    "USC00173046",
    "USC00190736",
    "USC00204090",
    "USC00213303",
    "USC00221389",
    "USC00229079",
    "USC00235834",
    "USC00243139",
    "USC00248597",
    "USC00253630",
    "USC00258480",
    "USC00284229",
    "USC00295960",
    "USC00301974",
    "USC00306164",
    "USC00314938",
    "USC00322365",
    "USC00331890",
    "USC00340017",
    "USC00345063",
    "USC00351765",
    "USC00356634",
    "USC00368449",
    "USC00384690",
    "USC00393217",
    "USC00406371",
    "USC00412679",
    "USC00417336",
    "USC00425402",
    "USC00431580",
    "USC00449263",
    "USC00455946",
    "USC00465224",
    "USC00476208",
    "USC00486440",
    "USW00013724",
    "USW00014739",
    "USW00014922",
    "USW00023062",
    "USW00024149",
    "USW00025339",
    "USW00094728",
    "USW00094846",
]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    plan_file.write(f"metadata\tghcnd-stations\t{base_url}/ghcnd-stations.txt\tghcnd-stations.txt\n")
    for station_id in stations:
        url = f"{base_url}/by_station/{station_id}.csv.gz"
        out = f"{station_id}.csv.gz"
        plan_file.write(f"station\t{station_id}\t{url}\t{out}\n")
PY

validate_payload() {
  kind=$1
  ident=$2
  path=$3
  python3 - <<'PY' "${kind}" "${ident}" "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import gzip, sys
from pathlib import Path

kind, ident, raw_path = sys.argv[1:4]
path = Path(raw_path)
if kind == "metadata":
    text = path.read_text(encoding="utf-8", errors="replace")
    if ident not in text:
        raise SystemExit(f"metadata file {path} does not mention {ident}")
else:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        first_line = handle.readline().strip()
    if not first_line.startswith(ident + ","):
        raise SystemExit(f"station archive {path} does not start with expected station id {ident}")
PY
}

fetch() {
  kind=$1
  ident=$2
  url=$3
  out=$4
  tmp="${out}.tmp"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    if validate_payload "${kind}" "${ident}" "${out}"; then
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
  validate_payload "${kind}" "${ident}" "${tmp}"
  mv "${tmp}" "${out}"
  return 0
}

success_count=0
cached_count=0
failure_count=0
while IFS='	' read -r kind ident url rel_out; do
  [ -n "${kind}" ] || continue
  out="${DOWNLOAD_ROOT}/${rel_out}"
  say "fetch ${kind} ${ident} ${url}"
  if fetch "${kind}" "${ident}" "${url}" "${out}"; then
    success_count=$((success_count + 1))
    say "ok ${kind} ${ident} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      cached_count=$((cached_count + 1))
      say "cached ${kind} ${ident} ${out}"
    else
      failure_count=$((failure_count + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\t%s\n' "${kind}" "${ident}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed ${kind} ${ident} ${url}"
    fi
  fi
done < "${PLAN_FILE}"

find "${DOWNLOAD_ROOT}" -maxdepth 1 -type f \( -name '*.csv.gz' -o -name 'ghcnd-stations.txt' \) -print0 | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}"
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
