#!/usr/bin/env sh
# Accepted recipe acquisition step; network execution remains user-run.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd); REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd); DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}; ID="zenodo_marine_dom_positive_ms1_f32"
ROOT="${DATA_DIR}/downloads/${ID}"; LOG_ROOT="${DATA_DIR}/logs/${ID}"; META="${ROOT}/zenodo_record.json"; PLAN="${ROOT}/download_plan.tsv"; FORCE=${FORCE:-0}
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ"); LOG="${LOG_ROOT}/download.${RUN_TS}.log"; LATEST="${LOG_ROOT}/download.latest.log"; mkdir -p "${ROOT}" "${LOG_ROOT}"; : > "${LOG}"
sync_log(){ status=$?; trap - EXIT; cp "${LOG}" "${LATEST}"; if [ "${status}" -ne 0 ]; then tail -n 40 "${LOG}" >&2; fi; exit "${status}"; }; trap sync_log EXIT
say(){ printf '%s\n' "$*" | tee -a "${LOG}"; }; say "dataset=${ID} record=10054333"
curl -fL --retry 3 --retry-delay 2 -o "${META}.tmp" "https://zenodo.org/api/records/10054333" >>"${LOG}" 2>&1; mv "${META}.tmp" "${META}"
python3 - "${META}" "${PLAN}" >>"${LOG}" 2>&1 <<'PY'
from pathlib import Path
import json,sys
obj=json.loads(Path(sys.argv[1]).read_text()); lic=obj.get('metadata',{}).get('license',{}); lid=(lic.get('id','') if isinstance(lic,dict) else str(lic)).lower()
if lid!='cc-by-4.0': raise SystemExit(f'expected cc-by-4.0, got {lid!r}')
wanted=['2D_Frac_10-12a.mzML','2D_Frac_10-12b.mzML']; by={f.get('key'):f for f in obj.get('files',[])}
with Path(sys.argv[2]).open('w') as h:
 for key in wanted:
  f=by.get(key)
  if not f: raise SystemExit(f'missing exact Zenodo file {key}')
  links=f.get('links') or {}; url=links.get('content') or links.get('self')
  if not url: raise SystemExit(f'missing content URL for {key}')
  h.write('\t'.join([key,str(f['size']),str(f['checksum']),url])+'\n')
PY
validate(){ python3 - "$1" <<'PY'
import sys,xml.etree.ElementTree as ET
p=sys.argv[1]
for _,e in ET.iterparse(p,events=('start',)):
 if e.tag.rsplit('}',1)[-1] not in {'mzML','indexedmzML'}: raise SystemExit('not mzML')
 break
PY
}
TAB=$(printf '\t')
while IFS="${TAB}" read -r key size checksum url; do out="${ROOT}/${key}"; if [ -f "${out}" ] && [ "${FORCE}" != 1 ]; then validate "${out}"; else tmp="${out}.tmp"; rm -f "${tmp}"; curl -fL --retry 3 --retry-delay 2 --max-filesize 200000000 -o "${tmp}" "${url}" >>"${LOG}" 2>&1; validate "${tmp}"; mv "${tmp}" "${out}"; fi; [ "$(wc -c < "${out}")" -eq "${size}" ] || exit 1; expected=${checksum#md5:}; [ "$(md5sum "${out}"|awk '{print $1}')" = "${expected}" ] || exit 1; done < "${PLAN}"
find "${ROOT}" -maxdepth 1 -name '*.mzML' -print0 | sort -z | xargs -0 sha256sum > "${ROOT}/checksums.sha256"; say "validated_files=2"
