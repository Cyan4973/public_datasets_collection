#!/usr/bin/env bash
# Local build: decode pinned mzML runs into one float64 m/z sample per MS1 spectrum.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
DATA_DIR="$(mkdir -p "${DATA_DIR}" && cd "${DATA_DIR}" && pwd)"
ID="metabolights_mtbls12824_maxis_centroid_mz_f64"
LOG_DIR="${DATA_DIR}/logs/${ID}"
mkdir -p "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/build.${RUN_TS}.log" "${LOG_DIR}/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=${ID}"
python3 -I "${SCRIPT_DIR}/scripts/mtbls_neg_ms1.py" extract --downloads "${DATA_DIR}/downloads/${ID}" --data-root "${DATA_DIR}"
echo "[$(date -Is)] build done"
