#!/usr/bin/env sh
# Accepted recipe acquisition step; network execution remains user-run.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="noaa_cors_rinex_observations_f64"
ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
BASE_URL=${CORS_BASE_URL:-"https://noaa-cors-pds.s3.amazonaws.com"}
PREFIX=${CORS_PREFIX:-"rinex/2024/001/"}
MAX_FILES=${CORS_MAX_FILES:-12}
MAX_FILE_BYTES=${MAX_FILE_BYTES:-50000000}
MAX_TOTAL_BYTES=${MAX_TOTAL_BYTES:-250000000}
FORCE=${FORCE:-0}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
PLAN="${ROOT}/download_plan.tsv"

mkdir -p "${ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_log() {
  status=$?
  trap - EXIT
  cp "${LOG_FILE}" "${LATEST_LOG}"
  if [ "${status}" -ne 0 ]; then tail -n 40 "${LOG_FILE}" >&2; fi
  exit "${status}"
}
trap sync_log EXIT
say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }
say "dataset=${DATASET_ID} prefix=${PREFIX} max_files=${MAX_FILES}"

if [ -n "${RINEX_URLS_FILE:-}" ]; then
  python3 - "${RINEX_URLS_FILE}" "${PLAN}" "${MAX_FILES}" <<'PY'
from pathlib import Path
from urllib.parse import urlparse
import sys
src, out, limit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
urls=[line.strip() for line in src.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
with out.open('w') as h:
    for url in urls[:limit]:
        h.write(f"{Path(urlparse(url).path).name}\t{url}\n")
PY
else
  LISTING="${ROOT}/listing.xml"
  curl -fL --retry 3 --retry-delay 2 -o "${LISTING}.tmp" \
    "${BASE_URL}/?list-type=2&prefix=${PREFIX}&max-keys=1000" >>"${LOG_FILE}" 2>&1
  mv "${LISTING}.tmp" "${LISTING}"
  python3 - "${LISTING}" "${PLAN}" "${BASE_URL}" "${MAX_FILES}" <<'PY'
from pathlib import Path
from urllib.parse import quote
import sys, xml.etree.ElementTree as ET
listing, out, base, limit = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].rstrip('/'), int(sys.argv[4])
root=ET.parse(listing).getroot()
keys=[]
for elem in root.iter():
    if elem.tag.rsplit('}',1)[-1]=='Key' and elem.text:
        key=elem.text.strip()
        low=key.lower()
        if low.endswith('o.gz'):
            keys.append(key)
keys=sorted(dict.fromkeys(keys))[:limit]
if not keys:
    raise SystemExit('no RINEX observation objects found; provide RINEX_URLS_FILE')
with out.open('w') as h:
    for key in keys:
        h.write(f"{Path(key).name}\t{base}/{quote(key, safe='/')}\n")
PY
fi

validate() {
  python3 - "$1" <<'PY'
from pathlib import Path
import gzip, sys
p=Path(sys.argv[1])
if p.stat().st_size <= 0: raise SystemExit(f'empty file: {p}')
try:
    with gzip.open(p, 'rt', encoding='ascii', errors='replace') as h:
        first=h.readline()
except OSError as e: raise SystemExit(f'invalid gzip RINEX file {p}: {e}')
if 'RINEX VERSION / TYPE' not in first or len(first) < 21 or first[20].upper() != 'O':
    raise SystemExit(f'not a RINEX observation file: {p}')
print(f'validated {p.name} bytes={p.stat().st_size} version={first[:9].strip()}')
PY
}

total=0
TAB=$(printf '\t')
while IFS="${TAB}" read -r name url; do
  [ -n "${name}" ] || continue
  out="${ROOT}/${name}"
  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    validate "${out}" | tee -a "${LOG_FILE}"
  else
    tmp="${out}.tmp"; rm -f "${tmp}"
    curl -fL --retry 3 --retry-delay 2 --max-filesize "${MAX_FILE_BYTES}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
    validate "${tmp}" | tee -a "${LOG_FILE}"
    mv "${tmp}" "${out}"
  fi
  size=$(wc -c < "${out}"); total=$((total + size))
  if [ "${total}" -gt "${MAX_TOTAL_BYTES}" ]; then say "total download cap exceeded"; exit 1; fi
done < "${PLAN}"

find "${ROOT}" -maxdepth 1 -type f \( -name '*o.gz' -o -name '*O.gz' \) -print0 | sort -z | xargs -0 sha256sum > "${ROOT}/checksums.sha256"
count=$(wc -l < "${ROOT}/checksums.sha256")
[ "${count}" -ge 2 ] || { say "fewer than two validated RINEX files"; exit 1; }
say "downloaded_files=${count} total_bytes=${total} plan=${PLAN}"
