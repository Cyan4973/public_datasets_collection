#!/usr/bin/env sh
# Accepted recipe local build step.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd); REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd); DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}; ID="zenodo_marine_dom_positive_ms1_f32"; LOG_ROOT="${DATA_DIR}/logs/${ID}"; mkdir -p "${LOG_ROOT}"; LOG="${LOG_ROOT}/build.$(date -u +%Y%m%dT%H%M%SZ).log"; LATEST="${LOG_ROOT}/build.latest.log"; : > "${LOG}"; trap 's=$?; trap - EXIT; cp "${LOG}" "${LATEST}"; exit $s' EXIT
python3 "${SCRIPT_DIR}/scripts/mzml_ms1.py" extract --downloads "${DATA_DIR}/downloads/${ID}" --data-root "${DATA_DIR}" --samples-root "${DATA_DIR}/samples/${ID}" --index "${DATA_DIR}/index/${ID}/samples.jsonl" --stats "${DATA_DIR}/filtered/${ID}/spectrum_stats.json" >>"${LOG}" 2>&1; cat "${LOG}"
