#!/usr/bin/env bash
# Fetch the 55 pinned single-profile drive-cycle MAT files of the Kollmeyer
# Panasonic 18650PF dataset from the BSEBench Hugging Face mirror at a fixed
# git revision, plus the mirror card, the upstream readme and the mirror tree
# listing used as license/provenance evidence. Every MAT file is checked
# against its pinned size and LFS SHA-256 and then structurally decoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="kollmeyer_panasonic18650pf_drive_cycle_voltage_f64"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVISION="0f3c96601aa8dcc25f697ef32f3ac918d24433b9"
HF_REPO="bsebench-org/panasonic-kollmeyer-2018-raw"
RESOLVE="https://huggingface.co/datasets/$HF_REPO/resolve/$REVISION"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILES_DIR="$DOWNLOAD_DIR/files"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SELECTION="$RECIPE_DIR/selection.tsv"
EXCLUDED="$RECIPE_DIR/excluded.tsv"
mkdir -p "$FILES_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

python3 "$RECIPE_DIR/scripts/kollmeyer_mat.py" selftest

encode_path() {
  local path="$1"
  if [[ ! "$path" =~ ^[A-Za-z0-9\ ._/-]+$ ]]; then
    echo "unexpected characters in repo path: $path" >&2
    exit 1
  fi
  printf '%s' "${path// /%20}"
}

# Small metadata/evidence files: bounded single requests.
fetch_small() {
  local target="$1" url="$2"
  local part="$target.part"
  rm -f "$part"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 5 --connect-timeout 30 \
    --max-time 300 --max-filesize 5000000 \
    --user-agent "openzl-public-datasets/1.0" --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

check_identity() {
  local path="$1" size="$2" sha="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" == "$size" ]] || return 1
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$sha" ]] || return 1
}

# MAT payloads: resumable, stall-bounded rather than time-bounded.
fetch_large() {
  local target="$1" url="$2" size="$3" sha="$4"
  if check_identity "$target" "$size" "$sha"; then
    echo "reuse $(basename "$target") bytes=$size"
    return
  fi
  rm -f "$target"
  local part="$target.part" attempt have
  for attempt in 1 2 3 4 5 6 7 8; do
    have=0
    [[ -f "$part" ]] && have="$(stat -c %s "$part")"
    if (( have > size )); then
      echo "partial file larger than expected; restarting $(basename "$target")"
      rm -f "$part"
      have=0
    fi
    if (( have < size )); then
      curl --globoff --fail --silent --show-error --location -C - \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
        --user-agent "openzl-public-datasets/1.0" --output "$part" "$url" || {
          echo "curl attempt $attempt failed for $(basename "$target") (have $(stat -c %s "$part" 2>/dev/null || echo 0) of $size bytes)"
          sleep $((attempt * 5))
          continue
        }
    fi
    if check_identity "$part" "$size" "$sha"; then
      mv "$part" "$target"
      echo "fetched $(basename "$target") bytes=$size sha256=$sha"
      return
    fi
    echo "identity mismatch after attempt $attempt for $(basename "$target"); restarting from zero"
    rm -f "$part"
  done
  echo "failed to fetch a valid copy of $url" >&2
  exit 1
}

fetch_small "$DOWNLOAD_DIR/hf_tree_$REVISION.json" \
  "https://huggingface.co/api/datasets/$HF_REPO/tree/$REVISION?recursive=true"
fetch_small "$DOWNLOAD_DIR/mirror_README.md" "$RESOLVE/README.md"
check_identity "$DOWNLOAD_DIR/mirror_README.md" 2190 \
  f33e6b30bfb127851de3165c797d7c5f8625e9f4f60bcf45bf0b55f91d4050c0 \
  || { echo "mirror README.md identity mismatch" >&2; exit 1; }
fetch_small "$DOWNLOAD_DIR/upstream_readme_desc_of_tests.txt" \
  "$RESOLVE/$(encode_path "Panasonic 18650PF Data/Readme file - desc of tests performed.txt")"
check_identity "$DOWNLOAD_DIR/upstream_readme_desc_of_tests.txt" 6426 \
  ed236fbbc93b3ac6fba2d0a98c55d5572fbe31b1053dc1ce46c8e268a1c23aab \
  || { echo "upstream readme identity mismatch" >&2; exit 1; }

total=0
count=0
while IFS=$'\t' read -r seq sample_id ambient profile start repo_path size sha; do
  url="$RESOLVE/$(encode_path "$repo_path")"
  fetch_large "$FILES_DIR/$sample_id.mat" "$url" "$size" "$sha"
  total=$((total + size))
  count=$((count + 1))
done < <(tail -n +2 "$SELECTION")
[[ "$count" == "55" ]] || { echo "selection row count changed: $count" >&2; exit 1; }
[[ "$total" == "113217590" ]] || { echo "source byte total changed: $total" >&2; exit 1; }

python3 "$RECIPE_DIR/scripts/kollmeyer_mat.py" preflight \
  --selection "$SELECTION" --excluded "$EXCLUDED" --downloads "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$total"
