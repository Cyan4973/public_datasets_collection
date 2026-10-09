#!/usr/bin/env bash
# Range-fetch the 1H zg30 Bruker FIDs (and every 1D acqus) from the pinned
# nmrXiv P90 project ZIP without downloading the 1.52 GB archive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nmrxiv_p90_bruker_1h_fid_f64"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ZIPPY="$RECIPE_DIR/scripts/nmrxiv_zip.py"

PROJECT_IDENTIFIER="NMRXIV:P90"
API_LIST="https://nmrxiv.org/api/v1/list/projects"
ARCHIVE_URL="https://s3.uni-jena.de/nmrxiv/production/archive/2d828808-0317-48fe-8679-813f91101b2e/nmr-data-of-ethanolic-extract-and-fractions-of-swertia-chirayita.zip"
ARCHIVE_BYTES=1519545194
TAIL_BYTES=65536
CD_OFFSET=1518333203
CD_BYTES=1211969
CD_ENTRIES=10901
CD_SHA256="e89a52ac4a961e505f5d0f21f627abde725378d28776f515d5d10d6f41c44059"
ACQUS_CANDIDATES=255
EXPECTED_FIDS=152
SELECTED_TSV_SHA256="dbb65ac9ba12f46968c59584e5f91c585144bcf67b8830ddf407628dd8627362"
UA="openzl-public-datasets-nmrxiv-p90/1.0"

mkdir -p "$DL/api" "$DL/zip" "$DL/members" "$DL/tmp" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

small_get() {  # url output
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 300 --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

range_get() {  # start end output
  local want=$(( $2 - $1 + 1 ))
  rm -f "$3.part" "$3.hdr"
  curl --fail --silent --show-error --location --retry 8 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
    --range "$1-$2" --dump-header "$3.hdr" --output "$3.part" "$ARCHIVE_URL"
  grep -qiE "^content-range: bytes $1-$2/$ARCHIVE_BYTES" "$3.hdr" || {
    echo "FATAL: server did not honor range $1-$2 of $ARCHIVE_BYTES bytes" >&2
    cat "$3.hdr" >&2
    exit 1
  }
  local got
  got="$(wc -c < "$3.part" | tr -d ' ')"
  [ "$got" = "$want" ] || { echo "FATAL: range $1-$2 returned $got bytes, want $want" >&2; exit 1; }
  mv "$3.part" "$3"
  rm -f "$3.hdr"
}

# 1. License and identity from the nmrXiv public project list (all pages).
page=1
while :; do
  out="$DL/api/projects_page$page.json"
  small_get "$API_LIST?page=$page&per_page=100" "$out"
  last="$(python3 -I - "$out" "$page" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(doc.get("data"), list) or "meta" not in doc:
    raise SystemExit("unexpected nmrXiv API payload")
if int(doc["meta"]["current_page"]) != int(sys.argv[2]):
    raise SystemExit("API returned the wrong page")
print(int(doc["meta"]["last_page"]))
PY
)"
  [ "$page" -ge "$last" ] && break
  page=$((page + 1))
done
python3 -I - "$DL/api" "$PROJECT_IDENTIFIER" "$ARCHIVE_URL" <<'PY'
import glob, json, sys
api_dir, ident, url = sys.argv[1:4]
hits = []
for path in sorted(glob.glob(f"{api_dir}/projects_page*.json")):
    for project in json.load(open(path, encoding="utf-8"))["data"]:
        if project.get("identifier") == ident:
            hits.append(project)
if len(hits) != 1:
    raise SystemExit(f"expected exactly one {ident} project in the API listing, found {len(hits)}")
p = hits[0]
lic = p.get("license") or {}
checks = {
    "is_public": p.get("is_public") is True,
    "is_published": p.get("is_published") is True,
    "license.spdx_id": lic.get("spdx_id") == "CC-BY-4.0",
    "download_url": p.get("download_url") == url,
    "doi": p.get("doi") == "10.57992/nmrxiv.p90",
}
bad = [k for k, ok in checks.items() if not ok]
if bad:
    raise SystemExit(f"{ident} metadata changed: {bad} license={lic.get('spdx_id')!r} url={p.get('download_url')!r}")
json.dump(p, open(f"{api_dir}/P90_project.json", "w", encoding="utf-8"), indent=1, sort_keys=True)
print(f"license_validation=ok project={ident} spdx={lic['spdx_id']} doi={p['doi']} title={p['name']!r}")
PY

# 2. Archive identity: tail (EOCD) and pinned central directory.
tail_file="$DL/zip/tail.bin"
range_get $((ARCHIVE_BYTES - TAIL_BYTES)) $((ARCHIVE_BYTES - 1)) "$tail_file"
read -r cd_off cd_len cd_n < <(python3 -I "$ZIPPY" eocd --tail "$tail_file" --archive-size "$ARCHIVE_BYTES")
if [ "$cd_off $cd_len $cd_n" != "$CD_OFFSET $CD_BYTES $CD_ENTRIES" ]; then
  echo "FATAL: EOCD changed: cd_offset=$cd_off cd_bytes=$cd_len entries=$cd_n" >&2
  exit 1
fi
cd_file="$DL/zip/central_directory.bin"
if ! { [ -s "$cd_file" ] && printf '%s  %s\n' "$CD_SHA256" "$cd_file" | sha256sum --check --status; }; then
  range_get "$CD_OFFSET" $((CD_OFFSET + CD_BYTES - 1)) "$cd_file"
fi
printf '%s  %s\n' "$CD_SHA256" "$cd_file" | sha256sum --check --status || {
  echo "FATAL: central directory SHA-256 mismatch (archive changed)" >&2
  exit 1
}
echo "archive_validation=ok bytes=$ARCHIVE_BYTES cd_entries=$CD_ENTRIES cd_sha256=$CD_SHA256"
python3 -I "$ZIPPY" plan --cd "$cd_file" --cd-offset "$CD_OFFSET" --entries "$CD_ENTRIES" \
  --all-out "$DL/zip/all_members.tsv" --acqus-out "$DL/zip/acqus_candidates.tsv"
n_acqus="$(($(wc -l < "$DL/zip/acqus_candidates.tsv") - 1))"
[ "$n_acqus" = "$ACQUS_CANDIDATES" ] || { echo "FATAL: $n_acqus acqus candidates, want $ACQUS_CANDIDATES" >&2; exit 1; }

# 3. Fetch one member per planned row: range = local header .. next local header - 1.
fetch_members() {  # plan.tsv
  local plan="$1" name flags method crc csize usize off start end rel dest fetched=0 cached=0
  while IFS=$'\t' read -r name flags method crc csize usize off start end; do
    [ "$name" = "name" ] && continue
    rel="${name#*//}"
    case "$rel" in *..*|/*) echo "FATAL: unsafe member path $name" >&2; exit 1 ;; esac
    dest="$DL/members/$rel"
    if [ -s "$dest" ] && [ "$(wc -c < "$dest" | tr -d ' ')" = "$usize" ] \
      && python3 -I -c 'import sys,zlib; sys.exit(0 if zlib.crc32(open(sys.argv[1],"rb").read()) == int(sys.argv[2],16) else 1)' "$dest" "$crc"; then
      cached=$((cached + 1))
      continue
    fi
    mkdir -p "$(dirname "$dest")"
    range_get "$start" "$end" "$DL/tmp/member.range"
    python3 -I "$ZIPPY" extract --plan "$plan" --name "$name" --range-file "$DL/tmp/member.range" --out "$dest"
    rm -f "$DL/tmp/member.range"
    fetched=$((fetched + 1))
  done < "$plan"
  echo "members plan=$(basename "$plan") fetched=$fetched cached=$cached (each CRC32-checked against the CD)"
}

fetch_members "$DL/zip/acqus_candidates.tsv"
python3 -I "$ZIPPY" select --members-dir "$DL/members" --acqus-plan "$DL/zip/acqus_candidates.tsv" \
  --all-plan "$DL/zip/all_members.tsv" --out "$DL/zip/selected_fids.tsv" --expect "$EXPECTED_FIDS"
printf '%s  %s\n' "$SELECTED_TSV_SHA256" "$DL/zip/selected_fids.tsv" | sha256sum --check --status || {
  echo "FATAL: selected FID list differs from the pinned selection" >&2
  exit 1
}
fetch_members "$DL/zip/selected_fids.tsv"
rmdir "$DL/tmp" 2>/dev/null || true

du -sb "$DL" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
