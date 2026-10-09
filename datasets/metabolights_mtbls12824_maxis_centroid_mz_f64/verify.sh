#!/usr/bin/env bash
# Independent verification: re-decode with a line-streaming regex decoder and compare index and sample bytes.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
DATA_DIR="$(mkdir -p "${DATA_DIR}" && cd "${DATA_DIR}" && pwd)"
ID="metabolights_mtbls12824_maxis_centroid_mz_f64"
LOG_DIR="${DATA_DIR}/logs/${ID}"
mkdir -p "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/verify.${RUN_TS}.log" "${LOG_DIR}/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=${ID}"
python3 -I "${SCRIPT_DIR}/scripts/mtbls_neg_ms1.py" verify --downloads "${DATA_DIR}/downloads/${ID}" --data-root "${DATA_DIR}" --manifest "${SCRIPT_DIR}/manifest.toml"
echo "[$(date -Is)] verify done"
