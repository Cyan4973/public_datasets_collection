#!/usr/bin/env sh
# Accepted recipe acquisition step; network execution remains user-run.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="nasa_naif_de440s_spk_coefficients_f64"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
URL=${SPK_URL:-"https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp"}
OUT="${DOWNLOAD_ROOT}/de440s.bsp"
FORCE=${FORCE:-0}

RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
mkdir -p "${DOWNLOAD_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() {
  status=$?
  trap - EXIT
  cp "${LOG_FILE}" "${LATEST_LOG}"
  exit "${status}"
}
trap sync_latest_log EXIT
say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

validate() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
size = path.stat().st_size
if size < 1_000_000:
    raise SystemExit(f"kernel is implausibly small: {size} bytes")
if size > 100_000_000:
    raise SystemExit(f"kernel exceeds 100 MB download cap: {size} bytes")
with path.open("rb") as handle:
    record = handle.read(1024)
if len(record) != 1024 or record[:8] != b"DAF/SPK ":
    raise SystemExit(f"not a DAF/SPK kernel: {path}")
binary_format = record[88:96]
if binary_format not in {b"LTL-IEEE", b"BIG-IEEE"}:
    raise SystemExit(f"unsupported DAF binary format {binary_format!r}")
print(f"validated DAF/SPK kernel size={size} binary_format={binary_format.decode()}")
PY
}

say "dataset=${DATASET_ID}"
say "url=${URL}"
say "output=${OUT}"

if [ -f "${OUT}" ] && [ "${FORCE}" != "1" ]; then
  validate "${OUT}" | tee -a "${LOG_FILE}"
  say "using validated cached kernel"
else
  TMP="${OUT}.tmp"
  rm -f "${TMP}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 3 --max-filesize 100000000 -o "${TMP}" "${URL}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${TMP}" "${URL}" >>"${LOG_FILE}" 2>&1
  else
    say "error: curl or wget is required"
    exit 1
  fi
  validate "${TMP}" | tee -a "${LOG_FILE}"
  mv "${TMP}" "${OUT}"
fi

sha256sum "${OUT}" | tee "${DOWNLOAD_ROOT}/checksums.sha256" | tee -a "${LOG_FILE}"
say "download complete"
