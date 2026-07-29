#!/usr/bin/env sh
# Accepted recipe acquisition step; network execution remains user-run.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}; ID="nasa_pds_gravity_harmonics_f64"
ROOT="${DATA_DIR}/downloads/${ID}"; LOG_ROOT="${DATA_DIR}/logs/${ID}"
PAGE=${GRAVITY_PRODUCT_PAGE:-"https://pgda.gsfc.nasa.gov/products/50"}
PINNED_URL=${PINNED_GRAVITY_URL:-"http://pds-geosciences.wustl.edu/grail/grail-l-lgrs-5-rdr-v1/grail_1001/shadr/gggrx_1200a_bouguer_sha.tab"}
MAX_BYTES=${MAX_FILE_BYTES:-300000000}; FORCE=${FORCE:-0}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ"); LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"; LATEST="${LOG_ROOT}/download.latest.log"
mkdir -p "${ROOT}" "${LOG_ROOT}"; : > "${LOG_FILE}"
sync_log() { status=$?; trap - EXIT; cp "${LOG_FILE}" "${LATEST}"; exit "${status}"; }; trap sync_log EXIT
say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }
OUT="${ROOT}/gravity_product"

if [ -f "${OUT}" ] && [ "${FORCE}" != "1" ]; then
  python3 "${SCRIPT_DIR}/scripts/gravity_extract.py" inspect --input "${OUT}" >>"${LOG_FILE}" 2>&1
  say "using validated cached gravity product"
else
  CANDIDATES="${ROOT}/candidate_urls.txt"; : > "${CANDIDATES}"
  if [ -n "${GRAVITY_URL:-}" ]; then
    printf '%s\n' "${GRAVITY_URL}" > "${CANDIDATES}"
  elif [ -n "${PINNED_URL}" ]; then
    printf '%s\n' "${PINNED_URL}" > "${CANDIDATES}"
  else
    HTML="${ROOT}/product_page.html"
    curl -fL --retry 3 --retry-delay 2 -o "${HTML}.tmp" "${PAGE}" >>"${LOG_FILE}" 2>&1
    mv "${HTML}.tmp" "${HTML}"
    python3 - "${HTML}" "${PAGE}" "${CANDIDATES}" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
import sys
class Links(HTMLParser):
    def __init__(self): super().__init__(); self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            href=dict(attrs).get('href')
            if href: self.urls.append(href)
p=Links(); p.feed(Path(sys.argv[1]).read_text(encoding='utf-8',errors='replace'))
base=sys.argv[2]; scored=[]
for href in p.urls:
    url=urljoin(base,href); low=url.lower()
    score=(10 if 'grgm1200' in low else 0)+(4 if any(x in low for x in ['.gfc','.sha','.tab']) else 0)+(2 if any(x in low for x in ['gravity','harmonic','coef']) else 0)
    if score: scored.append((-score,url))
urls=[]
for _,url in sorted(scored):
    if url not in urls: urls.append(url)
Path(sys.argv[3]).write_text(''.join(u+'\n' for u in urls[:20]))
PY
  fi
  [ -s "${CANDIDATES}" ] || { say "no payload URL discovered; set GRAVITY_URL"; exit 1; }
  success=0
  while IFS= read -r url; do
    [ -n "${url}" ] || continue
    tmp="${OUT}.tmp"; rm -f "${tmp}"
    say "trying ${url}"
    if curl -fL --retry 2 --retry-delay 2 --max-filesize "${MAX_BYTES}" -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1 && \
       python3 "${SCRIPT_DIR}/scripts/gravity_extract.py" inspect --input "${tmp}" >>"${LOG_FILE}" 2>&1; then
      mv "${tmp}" "${OUT}"; printf '%s\n' "${url}" > "${ROOT}/selected_url.txt"; success=1; break
    fi
  done < "${CANDIDATES}"
  [ "${success}" -eq 1 ] || { say "no candidate decoded as a high-degree coefficient model"; exit 1; }
fi
sha256sum "${OUT}" > "${ROOT}/checksums.sha256"
say "validated gravity product bytes=$(wc -c < "${OUT}")"
