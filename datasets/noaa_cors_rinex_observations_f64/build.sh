#!/usr/bin/env sh
# Accepted recipe local build step.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
ID="noaa_cors_rinex_observations_f64"
LOG_ROOT="${DATA_DIR}/logs/${ID}"; RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/build.${RUN_TS}.log"; LATEST="${LOG_ROOT}/build.latest.log"
mkdir -p "${LOG_ROOT}"; : > "${LOG_FILE}"
sync_log() { status=$?; trap - EXIT; cp "${LOG_FILE}" "${LATEST}"; exit "${status}"; }
trap sync_log EXIT
python3 "${SCRIPT_DIR}/scripts/rinex_extract.py" extract \
  --downloads "${DATA_DIR}/downloads/${ID}" --data-root "${DATA_DIR}" \
  --samples-root "${DATA_DIR}/samples/${ID}" \
  --index "${DATA_DIR}/index/${ID}/samples.jsonl" \
  --stats "${DATA_DIR}/filtered/${ID}/observation_stats.json" >>"${LOG_FILE}" 2>&1
cat "${LOG_FILE}"
