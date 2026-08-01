#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/openneuro_ds000030_t1w_mri_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openneuro_ds000030_t1w_mri_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
VOLUME_DIR="$DOWNLOAD_DIR/volumes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
BASE_URL="https://s3.amazonaws.com/openneuro.org"
REUSE_DIR="$REPO_ROOT/$DATA_DIR/downloads/openneuro_ds000030_t1w_mri_i16"

mkdir -p "$VOLUME_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

DESCRIPTION="$DOWNLOAD_DIR/dataset_description.json"
if [[ -f "$REUSE_DIR/dataset_description.json" ]]; then
  cp --reflink=auto "$REUSE_DIR/dataset_description.json" "$DESCRIPTION"
else
  curl --fail --location --retry 3 --retry-delay 2 \
    --user-agent "openzl-public-datasets/1.0" \
    --output "$DESCRIPTION.part" "$BASE_URL/ds000030/dataset_description.json"
  mv "$DESCRIPTION.part" "$DESCRIPTION"
fi
python3 - "$DESCRIPTION" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
obj = json.loads(path.read_text(encoding="utf-8"))
if obj.get("License") != "CC0":
    raise SystemExit(f"expected explicit CC0 license, found {obj.get('License')!r}")
if obj.get("DatasetDOI") != "10.18112/openneuro.ds000030.v1.0.0":
    raise SystemExit(f"unexpected dataset DOI: {obj.get('DatasetDOI')!r}")
print(f"license={obj['License']} doi={obj['DatasetDOI']}")
PY

downloaded=0
downloaded_bytes=0
while IFS=$'\t' read -r key expected_size expected_md5; do
  [[ "$key" == "key" ]] && continue
  [[ -n "$key" ]] || continue
  name="${key##*/}"
  target="$VOLUME_DIR/$name"
  valid=false
  if [[ -f "$target" ]] \
    && [[ "$(wc -c < "$target" | tr -d ' ')" == "$expected_size" ]] \
    && [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]]; then
    valid=true
    echo "validated existing $name"
  fi
  if [[ "$valid" != true ]]; then
    rm -f "$target" "$target.part"
    reuse="$REUSE_DIR/volumes/$name"
    if [[ -f "$reuse" ]] \
      && [[ "$(wc -c < "$reuse" | tr -d ' ')" == "$expected_size" ]] \
      && [[ "$(md5sum "$reuse" | awk '{print $1}')" == "$expected_md5" ]]; then
      echo "reuse validated prior-attempt source $reuse"
      ln "$reuse" "$target" 2>/dev/null || cp --reflink=auto "$reuse" "$target"
    else
      echo "fetch $key"
      curl --fail --location --retry 3 --retry-delay 2 \
        --user-agent "openzl-public-datasets/1.0" \
        --max-filesize 50000000 --output "$target.part" "$BASE_URL/$key"
      mv "$target.part" "$target"
    fi
    actual_size="$(wc -c < "$target" | tr -d ' ')"
    actual_md5="$(md5sum "$target" | awk '{print $1}')"
    if [[ "$actual_size" != "$expected_size" || "$actual_md5" != "$expected_md5" ]]; then
      echo "validation failed for $name size=$actual_size md5=$actual_md5" >&2
      exit 1
    fi
  fi
  downloaded=$((downloaded + 1))
  downloaded_bytes=$((downloaded_bytes + expected_size))
done < "$RECIPE_DIR/selection.tsv"

if [[ "$downloaded" -ne 20 || "$downloaded_bytes" -ne 241392401 ]]; then
  echo "selection realization mismatch files=$downloaded bytes=$downloaded_bytes" >&2
  exit 1
fi
echo "[$(date -Is)] download done files=$downloaded bytes=$downloaded_bytes"
