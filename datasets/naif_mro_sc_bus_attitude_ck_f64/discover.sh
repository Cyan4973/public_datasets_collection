#!/usr/bin/env bash
# Metadata-only discovery that produced sources.tsv. Not part of the
# acceptance path: download.sh uses the committed sources.tsv pins.
# Transfers: one ~2.2 MB PDS directory listing plus a few KB of DAF file and
# summary records and PDS labels per selected file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
DATASET_ID="naif_mro_sc_bus_attitude_ck_f64"
OUT_DIR="${DATA_DIR}/discovery/${DATASET_ID}"
LOG_DIR="${DATA_DIR}/logs/${DATASET_ID}"
LISTING_URL="https://naif.jpl.nasa.gov/pub/naif/pds/data/mro-m-spice-6-v1.0/mrosp_1000/data/ck/"

mkdir -p "${OUT_DIR}" "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/discover.${RUN_TS}.log" "${LOG_DIR}/discover.latest.log") 2>&1
echo "[$(date -u -Is)] discovery start dataset=${DATASET_ID}"

curl -sS -f -L --retry 5 --retry-delay 3 --max-time 300 --max-filesize 20000000 \
  -o "${OUT_DIR}/pds_ck_listing.html.part" "${LISTING_URL}"
mv "${OUT_DIR}/pds_ck_listing.html.part" "${OUT_DIR}/pds_ck_listing.html"

python3 "${SCRIPT_DIR}/scripts/discover.py" \
  --listing "${OUT_DIR}/pds_ck_listing.html" \
  --out "${OUT_DIR}/sources.tsv"

echo "discovered selection: ${OUT_DIR}/sources.tsv (compare with ${SCRIPT_DIR}/sources.tsv)"
