#!/usr/bin/env bash
# Download 30 pinned OpenNeuro ds004584 resting-state EEG recordings (EEGLAB
# .fdt float32 matrices plus their BIDS channels.tsv / eeg.json sidecars).
# Never fetches participants.tsv, participants.json, or EEGLAB .set files.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="openneuro_ds004584_pd_rest_eeg_f32"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
BASE_URL="https://s3.amazonaws.com/openneuro.org/ds004584"
UA="openzl-public-datasets-ds004584-eeg/1.0"
EXPECTED_RECORDINGS=30
EXPECTED_FDT_BYTES=605908800

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_dir=$DATA_DIR"

# 1. License and release identity gate.
description="$DOWNLOAD_DIR/dataset_description.json"
rm -f "$description.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --max-time 120 --max-filesize 100000 --user-agent "$UA" \
  --output "$description.part" "$BASE_URL/dataset_description.json"
mv "$description.part" "$description"
python3 - "$description" <<'PY'
import hashlib
import json
import sys
path = sys.argv[1]
raw = open(path, "rb").read()
meta = json.loads(raw)
if meta.get("License") != "CC0":
    raise SystemExit(f"expected License=CC0, found {meta.get('License')!r}")
if meta.get("DatasetDOI") != "doi:10.18112/openneuro.ds004584.v1.0.0":
    raise SystemExit(f"unexpected DatasetDOI {meta.get('DatasetDOI')!r}")
if meta.get("Name") != "Rest eyes open":
    raise SystemExit(f"unexpected dataset Name {meta.get('Name')!r}")
md5 = hashlib.md5(raw).hexdigest()
note = "" if md5 == "e638be12229b176a735782d36c850dfb" else " (description edited upstream since pinning; license/DOI still valid)"
print(f"license=CC0 doi={meta['DatasetDOI']} description_md5={md5}{note}")
PY

file_ok() {
  local path="$1" size="$2" md5="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(wc -c < "$path" | tr -d ' ')" == "$size" ]] || return 1
  [[ "$(md5sum "$path" | awk '{print $1}')" == "$md5" ]] || return 1
}

fetch_small() {
  local key="$1" target="$2" size="$3" md5="$4" attempt
  if file_ok "$target" "$size" "$md5"; then
    return 0
  fi
  for attempt in 1 2 3; do
    rm -f "$target" "$target.part"
    curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
      --max-time 120 --max-filesize 100000 --user-agent "$UA" \
      --output "$target.part" "$BASE_URL/$key" || true
    if file_ok "$target.part" "$size" "$md5"; then
      mv "$target.part" "$target"
      return 0
    fi
    echo "sidecar attempt $attempt failed validation for $key" >&2
  done
  echo "FATAL: could not fetch a valid $key" >&2
  return 1
}

fetch_large() {
  local key="$1" target="$2" size="$3" md5="$4" attempt part_size
  if file_ok "$target" "$size" "$md5"; then
    echo "validated existing ${target##*/}"
    return 0
  fi
  rm -f "$target"
  for attempt in 1 2 3 4 5; do
    part_size=0
    [[ -f "$target.part" ]] && part_size="$(wc -c < "$target.part" | tr -d ' ')"
    if [[ "$part_size" -gt "$size" ]]; then
      rm -f "$target.part"
      part_size=0
    fi
    if [[ "$part_size" -lt "$size" ]]; then
      echo "fetch $key (resume from $part_size of $size bytes)"
      curl --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
        --max-filesize 60000000 --user-agent "$UA" \
        --output "$target.part" "$BASE_URL/$key" || echo "curl exited non-zero for $key (attempt $attempt)" >&2
    fi
    if file_ok "$target.part" "$size" "$md5"; then
      mv "$target.part" "$target"
      echo "validated ${target##*/} bytes=$size md5=$md5"
      return 0
    fi
    part_size=0
    [[ -f "$target.part" ]] && part_size="$(wc -c < "$target.part" | tr -d ' ')"
    if [[ "$part_size" -ge "$size" ]]; then
      echo "size/MD5 mismatch for $key after attempt $attempt; discarding partial" >&2
      rm -f "$target.part"
    fi
  done
  echo "FATAL: could not fetch a valid $key" >&2
  return 1
}

# 2. Pinned recordings: sidecars first, then the float32 signal matrix.
recordings=0
fdt_bytes=0
while IFS=$'\t' read -r subject f_size f_md5 c_size c_md5 j_size j_md5 points; do
  [[ "$subject" == "subject" || -z "$subject" ]] && continue
  dest="$DOWNLOAD_DIR/$subject"
  mkdir -p "$dest"
  key_base="$subject/eeg/${subject}_task-Rest"
  fetch_small "${key_base}_channels.tsv" "$dest/${subject}_task-Rest_channels.tsv" "$c_size" "$c_md5"
  fetch_small "${key_base}_eeg.json" "$dest/${subject}_task-Rest_eeg.json" "$j_size" "$j_md5"
  fetch_large "${key_base}_eeg.fdt" "$dest/${subject}_task-Rest_eeg.fdt" "$f_size" "$f_md5"
  recordings=$((recordings + 1))
  fdt_bytes=$((fdt_bytes + f_size))
done < "$RECIPE_DIR/selection.tsv"

if [[ "$recordings" -ne "$EXPECTED_RECORDINGS" || "$fdt_bytes" -ne "$EXPECTED_FDT_BYTES" ]]; then
  echo "FATAL: selection realization mismatch recordings=$recordings fdt_bytes=$fdt_bytes" >&2
  exit 1
fi

# 3. Semantic validation: montage, channel count, geometry, finiteness.
python3 "$RECIPE_DIR/scripts/ds004584_eeg.py" check-download \
  --recipe-dir "$RECIPE_DIR" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID recordings=$recordings fdt_bytes=$fdt_bytes"
