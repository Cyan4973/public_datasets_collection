#!/usr/bin/env bash
# Fetch PhysioNet CHARIS database 1.0.0: SHA256SUMS.txt, RECORDS, all 13 WFDB
# headers, the .dat files of the 9 kept records (charis8, 9, 10 and 12 are
# excluded as majority non-ICP; see scripts/charis_pins.py), and the license
# evidence pages. Large .dat files are resumable (.part + curl -C -); every
# file is checked against the pinned SHA-256/size table and SHA256SUMS.txt.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1  # keep the recipe directory free of __pycache__

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="physionet_charis_icp_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://physionet-open.s3.amazonaws.com/charisdb/1.0.0"
LICENSE_PAGE_URL="https://physionet.org/content/charisdb/1.0.0/"

mkdir -p "$DOWNLOAD_DIR/license" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

file_size() { wc -c <"$1" | tr -d '[:space:]'; }
file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# Small pinned file: fetch whole, check size and SHA-256, then promote.
fetch_small() {
  local name="$1" size="$2" sha="$3" url="$4"
  local target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "$(file_size "$target")" == "$size" && "$(file_sha256 "$target")" == "$sha" ]]; then
    echo "cache_hit file=$name"
    return 0
  fi
  rm -f "$target" "$target.part"
  echo "fetch file=$name"
  curl -fsSL --retry 10 --retry-delay 5 --connect-timeout 30 --max-time 300 \
    --max-filesize 1000000 -o "$target.part" "$url"
  if [[ "$(file_size "$target.part")" != "$size" ]]; then
    echo "size mismatch for $name: $(file_size "$target.part") != $size" >&2
    rm -f "$target.part"
    exit 1
  fi
  if [[ "$(file_sha256 "$target.part")" != "$sha" ]]; then
    echo "SHA-256 mismatch for $name" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Large pinned file: resumable curl into .part, stall-bounded (no --max-time),
# promoted only when size and SHA-256 both match.
fetch_large() {
  local name="$1" size="$2" sha="$3" url="$4"
  local target="$DOWNLOAD_DIR/$name"
  local part="$target.part"
  if [[ -f "$target" ]]; then
    if [[ "$(file_size "$target")" == "$size" ]]; then
      echo "cache_hit file=$name (SHA-256 re-checked in final validation)"
      return 0
    fi
    echo "stale file=$name size=$(file_size "$target") expected=$size; refetching"
    rm -f "$target"
  fi
  local attempt current
  for attempt in 1 2 3 4 5; do
    current=0
    [[ -f "$part" ]] && current="$(file_size "$part")"
    if (( current > size )); then
      echo "oversized partial file=$name size=$current; restarting"
      rm -f "$part"
      current=0
    fi
    if (( current < size )); then
      echo "fetch file=$name attempt=$attempt resume_from=$current expected=$size"
      if ! curl -fL -C - --retry 10 --retry-delay 5 --connect-timeout 30 \
          --speed-limit 1024 --speed-time 120 -sS -o "$part" "$url"; then
        echo "curl failed for $name (attempt $attempt); will resume"
        sleep 5
        continue
      fi
      current="$(file_size "$part")"
    fi
    if (( current == size )); then
      if [[ "$(file_sha256 "$part")" == "$sha" ]]; then
        mv "$part" "$target"
        echo "ok file=$name bytes=$size"
        return 0
      fi
      echo "SHA-256 mismatch for complete partial $name; deleting and refetching"
      rm -f "$part"
    fi
  done
  echo "failed to fetch $name after 5 attempts" >&2
  exit 1
}

PINS_TSV="$(python3 - "$RECIPE_DIR/scripts" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import charis_pins as p
print(f"SHA256SUMS.txt\t{p.SHA256SUMS_BYTES}\t{p.SHA256SUMS_SHA256}")
print(f"RECORDS\t{p.RECORDS_BYTES}\t{p.RECORDS_SHA256}")
for r in p.record_rows():
    print(f"{r['record_id']}.hea\t{r['hea_bytes']}\t{r['hea_sha256']}")
for r in p.kept_record_rows():
    print(f"{r['record_id']}.dat\t{r['dat_bytes']}\t{r['dat_sha256']}")
PY
)"

[[ "$(grep -c . <<<"$PINS_TSV")" == "24" ]] || { echo "pin table must list 24 files" >&2; exit 1; }

while IFS=$'\t' read -r -u 3 name size sha; do
  [[ "$name" =~ ^(SHA256SUMS\.txt|RECORDS|charis[0-9]{1,2}\.(hea|dat))$ ]] || {
    echo "unsafe pinned file name: $name" >&2
    exit 1
  }
  case "$name" in
    *.dat) fetch_large "$name" "$size" "$sha" "$BASE_URL/$name" ;;
    *) fetch_small "$name" "$size" "$sha" "$BASE_URL/$name" ;;
  esac
done 3<<<"$PINS_TSV"

# License evidence (the release ships no LICENSE file). The project page is
# dynamic (view counter) and the license view is site-rendered HTML, so they
# are not hash-pinned; each must carry the expected license statements.
fetch_evidence() {
  local name="$1" url="$2"
  shift 2
  local target="$DOWNLOAD_DIR/license/$name"
  echo "fetch license evidence file=license/$name url=$url"
  curl -fsSL --retry 10 --retry-delay 5 --connect-timeout 30 --max-time 300 \
    --max-filesize 5000000 -o "$target.part" "$url"
  local needle
  for needle in "$@"; do
    grep -qF "$needle" "$target.part" || {
      echo "license evidence $name lacks expected text: $needle" >&2
      rm -f "$target.part"
      exit 1
    }
  done
  mv "$target.part" "$target"
}
fetch_evidence "charisdb_1.0.0_project_page.html" "$LICENSE_PAGE_URL" \
  "Open Data Commons Attribution License v1.0" \
  "Anyone can access the files, as long as they conform to the terms of the specified license." \
  "10.13026/C24G6F"
fetch_evidence "charisdb_1.0.0_view_license.html" "${LICENSE_PAGE_URL%1.0.0/}view-license/1.0.0/" \
  "License for CHARIS database v1.0.0" \
  "Open Data Commons Attribution License (ODC-By) v1.0" \
  "intended to allow users to freely share, modify, and use this Database"

python3 "$RECIPE_DIR/scripts/charis_download_check.py" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
