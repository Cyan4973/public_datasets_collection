#!/usr/bin/env sh
# Accepted recipe independent verification step.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd); REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}; ID="nasa_pds_gravity_harmonics_f64"; LOG_ROOT="${DATA_DIR}/logs/${ID}"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ"); LOG="${LOG_ROOT}/verify.${RUN_TS}.log"; LATEST="${LOG_ROOT}/verify.latest.log"
mkdir -p "${LOG_ROOT}"; : > "${LOG}"; sync_log(){ status=$?; trap - EXIT; cp "${LOG}" "${LATEST}"; exit "${status}"; }; trap sync_log EXIT
python3 "${SCRIPT_DIR}/scripts/gravity_extract.py" verify --input "${DATA_DIR}/downloads/${ID}/gravity_product" --data-root "${DATA_DIR}" --samples-root "${DATA_DIR}/samples/${ID}" --index "${DATA_DIR}/index/${ID}/samples.jsonl" --stats "${DATA_DIR}/filtered/${ID}/model_stats.json" >>"${LOG}" 2>&1
cat "${LOG}"
