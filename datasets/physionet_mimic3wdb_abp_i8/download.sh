#!/usr/bin/env bash
# Fetch the pinned MIMIC-III Waveform Database 1.0 segments (header + format-80
# .dat for each of the segments listed in scripts/mimic_pins.py), RECORDS-adults,
# the release LICENSE.txt and the project landing page (license evidence).
# Every file is pinned by size and SHA-256 (SHA-256 values come from the
# release SHA256SUMS.txt); .dat files are fetched resumably (.part + curl -C -,
# stall-bounded, no --max-time) and promoted only on an exact match.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1  # keep the recipe directory free of __pycache__

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="physionet_mimic3wdb_abp_i8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://physionet.org/files/mimic3wdb/1.0"
LANDING_URL="https://physionet.org/content/mimic3wdb/1.0/"

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
  local rel="$1" size="$2" sha="$3"
  local target="$DOWNLOAD_DIR/$rel"
  if [[ -f "$target" && "$(file_size "$target")" == "$size" && "$(file_sha256 "$target")" == "$sha" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$target")"
  rm -f "$target" "$target.part"
  echo "fetch file=$rel"
  curl -fsSL --retry 10 --retry-delay 5 --connect-timeout 30 --max-time 300 \
    --max-filesize 2000000 -o "$target.part" "$BASE_URL/$rel"
  if [[ "$(file_size "$target.part")" != "$size" || "$(file_sha256 "$target.part")" != "$sha" ]]; then
    echo "size/SHA-256 mismatch for $rel" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Large pinned file: resumable curl into .part, stall-bounded (no --max-time),
# promoted only when size and SHA-256 both match.
fetch_large() {
  local rel="$1" size="$2" sha="$3"
  local target="$DOWNLOAD_DIR/$rel"
  local part="$target.part"
  mkdir -p "$(dirname "$target")"
  if [[ -f "$target" ]]; then
    if [[ "$(file_size "$target")" == "$size" ]]; then
      return 0  # SHA-256 re-checked by mimic_download_check.py
    fi
    echo "stale file=$rel size=$(file_size "$target") expected=$size; refetching"
    rm -f "$target"
  fi
  local attempt current
  for attempt in 1 2 3 4 5; do
    current=0
    [[ -f "$part" ]] && current="$(file_size "$part")"
    if (( current > size )); then
      echo "oversized partial file=$rel size=$current; restarting"
      rm -f "$part"
      current=0
    fi
    if (( current < size )); then
      echo "fetch file=$rel attempt=$attempt resume_from=$current expected=$size"
      if ! curl -fL -C - --retry 10 --retry-delay 5 --connect-timeout 30 \
          --speed-limit 1024 --speed-time 120 -sS -o "$part" "$BASE_URL/$rel"; then
        echo "curl failed for $rel (attempt $attempt); will resume"
        sleep 5
        continue
      fi
      current="$(file_size "$part")"
    fi
    if (( current == size )); then
      if [[ "$(file_sha256 "$part")" == "$sha" ]]; then
        mv "$part" "$target"
        return 0
      fi
      echo "SHA-256 mismatch for complete partial $rel; deleting and refetching"
      rm -f "$part"
    fi
  done
  echo "failed to fetch $rel after 5 attempts" >&2
  exit 1
}

PINS_TSV="$(python3 - "$RECIPE_DIR/scripts" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import mimic_pins as p
print(f"small\tRECORDS-adults\t{p.RECORDS_ADULTS_BYTES}\t{p.RECORDS_ADULTS_SHA256}")
print(f"small\tLICENSE.txt\t{p.LICENSE_TXT_BYTES}\t{p.LICENSE_TXT_SHA256}")
for r in p.segment_rows():
    print(f"small\t{r['record_dir']}{r['segment']}.hea\t{r['hea_bytes']}\t{r['hea_sha256']}")
for r in p.segment_rows():
    print(f"large\t{r['record_dir']}{r['segment']}.dat\t{r['dat_bytes']}\t{r['dat_sha256']}")
PY
)"

n_files="$(grep -c . <<<"$PINS_TSV")"
echo "pinned files: $n_files"
done_count=0
while IFS=$'\t' read -r -u 3 kind rel size sha; do
  [[ "$rel" =~ ^(RECORDS-adults|LICENSE\.txt|3[0-9]/3[0-9]{6}/3[0-9]{6}_[0-9]{4}\.(hea|dat))$ ]] || {
    echo "unsafe pinned path: $rel" >&2
    exit 1
  }
  [[ "$sha" =~ ^[0-9a-f]{64}$ && "$size" =~ ^[0-9]+$ ]] || { echo "bad pin for $rel" >&2; exit 1; }
  case "$kind" in
    small) fetch_small "$rel" "$size" "$sha" ;;
    large) fetch_large "$rel" "$size" "$sha" ;;
    *) echo "bad kind $kind" >&2; exit 1 ;;
  esac
  done_count=$((done_count + 1))
  if (( done_count % 20 == 0 )); then echo "progress $done_count/$n_files"; fi
done 3<<<"$PINS_TSV"

# License evidence: the landing page (site-rendered, not hash-pinned) must carry
# the access policy, license name and DOI. LICENSE.txt itself is hash-pinned.
LANDING="$DOWNLOAD_DIR/license/mimic3wdb_1.0_landing.html"
curl -fsSL --retry 10 --retry-delay 5 --connect-timeout 30 --max-time 300 \
  --max-filesize 5000000 -o "$LANDING.part" "$LANDING_URL"
for needle in \
  "Anyone can access the files, as long as they conform to the terms of the specified license." \
  "Open Data Commons Open Database License v1.0" \
  "10.13026/c2607m"; do
  grep -qF "$needle" "$LANDING.part" || { echo "landing page lacks: $needle" >&2; rm -f "$LANDING.part"; exit 1; }
done
mv "$LANDING.part" "$LANDING"
grep -qF "ODC Open Database License (ODbL)" "$DOWNLOAD_DIR/LICENSE.txt" || { echo "LICENSE.txt is not ODbL" >&2; exit 1; }

python3 "$RECIPE_DIR/scripts/mimic_download_check.py" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
