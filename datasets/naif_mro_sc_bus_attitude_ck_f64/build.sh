#!/usr/bin/env bash
# Local build from files written by download.sh; no network access.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
DATASET_ID="naif_mro_sc_bus_attitude_ck_f64"
LOG_DIR="${DATA_DIR}/logs/${DATASET_ID}"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/build.${RUN_TS}.log" "${LOG_DIR}/build.latest.log") 2>&1
echo "[$(date -u -Is)] build start dataset=${DATASET_ID}"

python3 "${SCRIPT_DIR}/scripts/selftest.py"
python3 "${SCRIPT_DIR}/scripts/build.py" --sources "${SCRIPT_DIR}/sources.tsv" --data-dir "${DATA_DIR}"
echo "[$(date -u -Is)] build complete"
