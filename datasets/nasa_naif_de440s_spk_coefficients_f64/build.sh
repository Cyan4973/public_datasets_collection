#!/usr/bin/env sh
# Accepted recipe local build step.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="nasa_naif_de440s_spk_coefficients_f64"
INPUT="${DATA_DIR}/downloads/${DATASET_ID}/de440s.bsp"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"

RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/build.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/build.latest.log"
mkdir -p "${FILTERED_ROOT}" "${INDEX_ROOT}" "${SAMPLES_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() {
  status=$?
  trap - EXIT
  cp "${LOG_FILE}" "${LATEST_LOG}"
  exit "${status}"
}
trap sync_latest_log EXIT

python3 "${SCRIPT_DIR}/scripts/spk_extract.py" extract \
  --input "${INPUT}" \
  --data-root "${DATA_DIR}" \
  --samples-root "${SAMPLES_ROOT}" \
  --index-path "${INDEX_ROOT}/samples.jsonl" \
  --stats-path "${FILTERED_ROOT}/segment_stats.json" \
  >>"${LOG_FILE}" 2>&1

cat "${LOG_FILE}"
