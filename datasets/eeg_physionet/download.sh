#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eeg_physionet"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="https://physionet.org/files/eegmmidb/1.0.0"
SUBJECTS=$(seq -f '%03g' 1 10)
RUNS="01 02 04"

failure_count=0
printf 'subject\trun\turl\n' > "$FAILURES"

for subj in $SUBJECTS; do
  subj_dir="$DOWNLOAD_DIR/S${subj}"
  mkdir -p "$subj_dir"
  for run in $RUNS; do
    fname="S${subj}R${run}.edf"
    out="$subj_dir/$fname"
    url="${BASE_URL}/S${subj}/${fname}"
    if [ -f "$out" ]; then
      echo "cache_hit subject=S${subj} run=${run}"
      continue
    fi
    echo "fetch subject=S${subj} run=${run} url=$url"
    if ! curl -fL --retry 3 --retry-delay 5 -o "$out" "$url"; then
      rm -f "$out"
      printf 'S%s\t%s\t%s\n' "$subj" "$run" "$url" >> "$FAILURES"
      failure_count=$((failure_count + 1))
    fi
  done
done

edf_count=$(find "$DOWNLOAD_DIR" -type f -name '*.edf' | wc -l | tr -d ' ')
printf 'edf_count\n%s\n' "$edf_count" > "$FILTER_DIR/download_inventory.tsv"
echo "edf_count=$edf_count failure_count=$failure_count"

if [ "$failure_count" -ne 0 ]; then
  echo "[$(date -Is)] download failed dataset=$DATASET_ID"
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
