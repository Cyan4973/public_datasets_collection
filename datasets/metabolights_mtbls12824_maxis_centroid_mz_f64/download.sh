#!/usr/bin/env bash
# Fetch 20 pinned negative-ion HILIC tissue mzML runs from MetaboLights MTBLS12824.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
ID="metabolights_mtbls12824_maxis_centroid_mz_f64"
BASE="https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824"
ROOT="${DATA_DIR}/downloads/${ID}"
LOG_DIR="${DATA_DIR}/logs/${ID}"
RUNS="${SCRIPT_DIR}/scripts/runs.tsv"
PY="${SCRIPT_DIR}/scripts/mtbls_neg_ms1.py"
UA="openzl-public-datasets-collection/1.0"

mkdir -p "${ROOT}" "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/download.${RUN_TS}.log" "${LOG_DIR}/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=${ID}"

small_get() {  # url out maxbytes
  rm -f "$2.part"
  curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors --max-time 180 \
    --max-filesize "$3" -A "${UA}" -o "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. Study metadata and license (re-fetched every run; the license line is the gate).
small_get "${BASE}/i_Investigation.txt" "${ROOT}/i_Investigation.txt" 2000000
python3 -I - "${ROOT}/i_Investigation.txt" <<'PY'
import sys
t = open(sys.argv[1], encoding="utf-8").read().splitlines()
lic = [l.split("\t", 1)[1].strip().strip('"') for l in t if l.startswith("Comment[License]\t")]
if lic != ["CC0 1.0 Universal"]:
    raise SystemExit(f"FATAL: expected 'Comment[License]\tCC0 1.0 Universal', got {lic!r}")
ident = [l.split("\t", 1)[1].strip().strip('"') for l in t if l.startswith("Study Identifier\t")]
if ident != ["MTBLS12824"]:
    raise SystemExit(f"FATAL: unexpected Study Identifier {ident!r}")
print("license ok: CC0 1.0 Universal; study MTBLS12824")
PY
sha256sum "${ROOT}/i_Investigation.txt"

# 2. Upstream SHA-256 manifest must agree with the hashes pinned in scripts/runs.tsv.
small_get "${BASE}/HASHES/data_sha256.json" "${ROOT}/data_sha256.json" 5000000
python3 -I - "${ROOT}/data_sha256.json" "${RUNS}" <<'PY'
import json, sys
h = json.load(open(sys.argv[1]))
bad = 0
for line in open(sys.argv[2]):
    if line.startswith("#") or not line.strip():
        continue
    name, sha, size, group = line.rstrip("\n").split("\t")
    up = h.get("FILES/" + name)
    if up != sha:
        print(f"FATAL: upstream sha256 for {name} is {up!r}, pinned {sha}")
        bad += 1
if bad:
    raise SystemExit(1)
print("upstream data_sha256.json agrees with pinned runs")
PY

# 3. Liveness check (one-byte range GET).
first="$(awk -F'\t' '!/^#/ && NF {print $1; exit}' "${RUNS}")"
curl -fsSL --max-time 60 -r 0-0 -A "${UA}" -o /dev/null "${BASE}/FILES/${first}"
echo "liveness ok: ${first}"

# 4. Resumable fetch, size + SHA-256 + full mzML semantic validation per run.
n=0
while IFS=$'\t' read -r name sha size group; do
  case "${name}" in ''|'#'*) continue ;; esac
  out="${ROOT}/${name}"
  if [ -f "${out}" ] && [ "$(stat -c %s "${out}")" = "${size}" ] \
     && printf '%s  %s\n' "${sha}" "${out}" | sha256sum --check --status; then
    echo "present ${name}"
    n=$((n + 1))
    continue
  fi
  rm -f "${out}"
  part="${out}.part"
  if [ -f "${part}" ] && [ "$(stat -c %s "${part}")" -gt "${size}" ]; then rm -f "${part}"; fi
  echo "[$(date -Is)] fetch ${name} (${size} bytes, ${group})"
  curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 -A "${UA}" -sS \
    -o "${part}" "${BASE}/FILES/${name}"
  got="$(stat -c %s "${part}")"
  if [ "${got}" != "${size}" ]; then
    echo "FATAL: ${name} size ${got} != ${size}"; exit 1
  fi
  if ! printf '%s  %s\n' "${sha}" "${part}" | sha256sum --check --status; then
    echo "FATAL: ${name} sha256 mismatch; removing partial"; rm -f "${part}"; exit 1
  fi
  python3 -I "${PY}" validate "${part}"
  mv "${part}" "${out}"
  n=$((n + 1))
done < "${RUNS}"

[ "${n}" -eq 20 ] || { echo "FATAL: expected 20 runs, have ${n}"; exit 1; }
( cd "${ROOT}" && sha256sum ./*.mzML > checksums.sha256 )
echo "[$(date -Is)] download done runs=${n} bytes=$(cat "${ROOT}"/*.mzML | wc -c)"
