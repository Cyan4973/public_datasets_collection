#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="sec_companyfacts_net_income_quarterly"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
FAILURES_FILE="${DOWNLOAD_ROOT}/download_failures.tsv"
PLAN_FILE="${DOWNLOAD_ROOT}/download_plan.tsv"
CHECKSUM_FILE="${DOWNLOAD_ROOT}/collection_checksums.sha256"
USER_AGENT=${USER_AGENT:-"openzl-public-datasets-collection/1.0"}

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

plan_path = Path(sys.argv[1])
companies = [
    ("apple", "0000320193"),
    ("microsoft", "0000789019"),
    ("alphabet", "0001652044"),
    ("amazon", "0001018724"),
    ("meta", "0001326801"),
]
with plan_path.open("w", encoding="utf-8", newline="") as plan_file:
    for company_id, cik in companies:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        plan_file.write(f"{company_id}\t{cik}\t{url}\t{company_id}.json\n")
PY

validate_payload() {
  path=$1
  python3 - <<'PY' "${path}" >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
facts = payload.get("facts", {}).get("us-gaap", {}).get("NetIncomeLoss", {}).get("units", {}).get("USD")
if not isinstance(facts, list) or not facts:
    raise SystemExit(f"missing NetIncomeLoss USD facts in {path}")
if not any(isinstance(row, dict) and row.get("fy") and row.get("fp") and row.get("val") not in ("", None) for row in facts):
    raise SystemExit(f"no usable quarterly NetIncomeLoss facts in {path}")
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
    curl -fL --retry 3 --retry-delay 5 -A "${USER_AGENT}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget --user-agent="${USER_AGENT}" -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
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
while IFS='	' read -r company_id cik url rel_out; do
  [ -n "${company_id}" ] || continue
  out="${DOWNLOAD_ROOT}/${rel_out}"
  say "fetch ${company_id} ${url}"
  if fetch "${url}" "${out}"; then
    success_count=$((success_count + 1))
    say "ok ${company_id} ${out}"
  else
    status=$?
    if [ "${status}" -eq 2 ]; then
      cached_count=$((cached_count + 1))
      say "cached ${company_id} ${out}"
    else
      failure_count=$((failure_count + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\t%s\n' "${company_id}" "${cik}" "${url}" "${rel_out}" >> "${FAILURES_FILE}"
      say "failed ${company_id} ${url}"
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
