#!/usr/bin/env bash
# Fetch the 30 Empatica E4 ACC.csv session files of PhysioNet
# wearable-exam-stress 1.0.0 (10 subjects x midterm_1, midterm_2, Final), the
# release SHA256SUMS.txt and LICENSE.txt, and the project page as license
# evidence. Every data file is pinned by size and SHA-256 (scripts/e4acc_pins.py)
# and cross-checked against SHA256SUMS.txt; BVP, EDA, TEMP, HR, IBI and tags
# files are never fetched.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1  # keep the recipe directory free of __pycache__

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="physionet_wearable_exam_stress_e4_acc_i8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://physionet-open.s3.amazonaws.com/wearable-exam-stress/1.0.0"
PROJECT_PAGE_URL="https://physionet.org/content/wearable-exam-stress/1.0.0/"

mkdir -p "$DOWNLOAD_DIR/acc" "$DOWNLOAD_DIR/license" "$LOG_DIR"
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

# Pinned file: resumable curl into .part, stall-bounded (no --max-time),
# promoted only when size and SHA-256 both match.
fetch_pinned() {
  local target="$1" size="$2" sha="$3" url="$4"
  local part="$target.part"
  if [[ -f "$target" ]]; then
    if [[ "$(file_size "$target")" == "$size" && "$(file_sha256 "$target")" == "$sha" ]]; then
      echo "cache_hit file=${target#"$DOWNLOAD_DIR"/}"
      return 0
    fi
    echo "stale file=${target#"$DOWNLOAD_DIR"/}; refetching"
    rm -f "$target"
  fi
  local attempt current
  for attempt in 1 2 3 4 5; do
    current=0
    [[ -f "$part" ]] && current="$(file_size "$part")"
    if (( current > size )); then
      echo "oversized partial file=${target#"$DOWNLOAD_DIR"/} size=$current; restarting"
      rm -f "$part"
      current=0
    fi
    if (( current < size )); then
      echo "fetch file=${target#"$DOWNLOAD_DIR"/} attempt=$attempt resume_from=$current expected=$size"
      if ! curl -fL -C - --retry 10 --retry-delay 5 --connect-timeout 30 \
          --speed-limit 1024 --speed-time 120 -sS -o "$part" "$url"; then
        echo "curl failed (attempt $attempt); will resume"
        sleep 5
        continue
      fi
      current="$(file_size "$part")"
    fi
    if (( current == size )); then
      if [[ "$(file_sha256 "$part")" == "$sha" ]]; then
        mv "$part" "$target"
        echo "ok file=${target#"$DOWNLOAD_DIR"/} bytes=$size"
        return 0
      fi
      echo "SHA-256 mismatch for complete partial ${target#"$DOWNLOAD_DIR"/}; deleting and refetching"
      rm -f "$part"
    fi
  done
  echo "failed to fetch $url after 5 attempts" >&2
  exit 1
}

PINS_TSV="$(python3 - "$RECIPE_DIR/scripts" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import e4acc_pins as p
print(f"SHA256SUMS.txt\tSHA256SUMS.txt\t{p.SHA256SUMS_BYTES}\t{p.SHA256SUMS_SHA256}")
print(f"LICENSE.txt\tLICENSE.txt\t{p.LICENSE_BYTES}\t{p.LICENSE_SHA256}")
for subject, exam, path, size, sha in p.ACC_FILES:
    print(f"acc/{p.local_name(subject, exam)}\t{path}\t{size}\t{sha}")
PY
)"
[[ "$(grep -c . <<<"$PINS_TSV")" == "32" ]] || { echo "pin table must list 32 files" >&2; exit 1; }

while IFS=$'\t' read -r -u 3 local_rel remote size sha; do
  [[ "$local_rel" =~ ^(SHA256SUMS\.txt|LICENSE\.txt|acc/S[0-9]{1,2}_(midterm_1|midterm_2|Final)_ACC\.csv)$ ]] || {
    echo "unsafe local name: $local_rel" >&2; exit 1; }
  [[ "$remote" =~ ^(SHA256SUMS\.txt|LICENSE\.txt|data/S[0-9]{1,2}/(midterm_1|midterm_2|Final)/ACC\.csv)$ ]] || {
    echo "unexpected remote path: $remote" >&2; exit 1; }
  fetch_pinned "$DOWNLOAD_DIR/$local_rel" "$size" "$sha" "$BASE_URL/$remote"
done 3<<<"$PINS_TSV"

# License evidence: the project page is dynamic (view counter), so it is not
# hash-pinned; it must carry the access policy, license name and DOI.
target="$DOWNLOAD_DIR/license/wearable_exam_stress_1.0.0_project_page.html"
echo "fetch license evidence url=$PROJECT_PAGE_URL"
curl -fsSL --retry 10 --retry-delay 5 --connect-timeout 30 --max-time 300 \
  --max-filesize 5000000 -o "$target.part" "$PROJECT_PAGE_URL"
for needle in \
    "Anyone can access the files, as long as they conform to the terms of the specified license." \
    "Open Data Commons Attribution License v1.0" \
    "10.13026/kvkb-aj90" \
    "Empatica E4"; do
  grep -qF "$needle" "$target.part" || {
    echo "project page lacks expected text: $needle" >&2
    rm -f "$target.part"
    exit 1
  }
done
mv "$target.part" "$target"
grep -qF "ODC Attribution License (ODC-By)" "$DOWNLOAD_DIR/LICENSE.txt" || {
  echo "LICENSE.txt is not the ODC-By text" >&2; exit 1; }

python3 "$RECIPE_DIR/scripts/e4acc_download_check.py" --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
