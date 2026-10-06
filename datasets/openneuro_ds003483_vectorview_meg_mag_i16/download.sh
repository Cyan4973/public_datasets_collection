#!/usr/bin/env bash
# Acquire the CC0 dataset description and six pinned whole Vectorview FIFF
# raw files (2,855,273,946 B) from OpenNeuro ds003483. FIFF data buffers are
# time-major (all 320 channels interleaved per sample), so per-channel byte
# ranges do not exist and whole files are required. Every file is checked
# for size, MD5 (= single-part S3 ETag) and full FIFF structure before it is
# accepted.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="openneuro_ds003483_vectorview_meg_mag_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://s3.amazonaws.com/openneuro.org"
TOOL="$RECIPE_DIR/scripts/fif_meg.py"
SELECTION="$RECIPE_DIR/selection.tsv"
UA="openzl-public-datasets-ds003483-meg/1.0"
DESCRIPTION_KEY="ds003483/dataset_description.json"
DESCRIPTION_VERSION="5n.o11Crl3Nvg7AKgzfAfroeS016CLTf"
DESCRIPTION_MD5="2672ea7a59f7aff3183edb230044d904"
EXPECTED_RUNS=6

mkdir -p "$DOWNLOAD_DIR/fif" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

CURL_SMALL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 5
  --retry-all-errors --max-time 120 --user-agent "$UA")
# curl's own --retry truncates back to where that invocation started, so keep
# it small; the outer attempt loop below always resumes from the current
# .part size with -C -.
CURL_BULK=(curl --fail --silent --show-error --location --retry 3 --retry-delay 5
  --retry-all-errors --speed-limit 1024 --speed-time 120 --user-agent "$UA")

md5_of() { md5sum "$1" | awk '{print $1}'; }
size_of() { stat -c %s "$1"; }

python3 "$TOOL" selftest

# 1. License evidence: the pinned dataset_description.json object version.
description="$DOWNLOAD_DIR/dataset_description.json"
if [[ ! -f "$description" || "$(md5_of "$description")" != "$DESCRIPTION_MD5" ]]; then
  "${CURL_SMALL[@]}" --max-filesize 100000 --output "$description.part" \
    "$BASE_URL/$DESCRIPTION_KEY?versionId=$DESCRIPTION_VERSION"
  if [[ "$(md5_of "$description.part")" != "$DESCRIPTION_MD5" ]]; then
    echo "dataset_description.json MD5 mismatch" >&2
    rm -f "$description.part"
    exit 1
  fi
  mv "$description.part" "$description"
fi
python3 "$TOOL" check-description --path "$description"

# 2. Whole FIF files at pinned object versions, resumable.
runs=0
while IFS=$'\t' read -r subject session task run key version size md5 dir_pointer n_buffers skip; do
  [[ "$subject" == "subject" || -z "$subject" ]] && continue
  runs=$((runs + 1))
  target="$DOWNLOAD_DIR/fif/${key##*/}"
  url="$BASE_URL/$key?versionId=$version"

  if [[ -f "$target" ]]; then
    if [[ "$(size_of "$target")" == "$size" && "$(md5_of "$target")" == "$md5" ]]; then
      python3 "$TOOL" check-fif --selection "$SELECTION" --subject "$subject" --path "$target" < /dev/null
      echo "fif ok (cached) $subject"
      continue
    fi
    echo "cached $target fails size/MD5; refetching" >&2
    rm -f "$target"
  fi

  # A complete or oversized leftover .part cannot be resumed (HTTP 416).
  if [[ -f "$target.part" ]]; then
    part_size="$(size_of "$target.part")"
    if [[ "$part_size" -gt "$size" ]] || { [[ "$part_size" -eq "$size" ]] && [[ "$(md5_of "$target.part")" != "$md5" ]]; }; then
      echo "discarding unusable partial $target.part ($part_size B)" >&2
      rm -f "$target.part"
    fi
  fi

  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    have=0
    [[ -f "$target.part" ]] && have="$(size_of "$target.part")"
    [[ "$have" -eq "$size" ]] && break
    echo "[$(date -Is)] fetching $subject from byte $have of $size (attempt $attempt)"
    "${CURL_BULK[@]}" -C - --max-filesize "$size" --output "$target.part" "$url" < /dev/null \
      || echo "curl exited $? for $subject (attempt $attempt)" >&2
    if [[ -f "$target.part" && "$(size_of "$target.part")" -gt "$size" ]]; then
      echo "partial file grew beyond pinned size; restarting $subject" >&2
      rm -f "$target.part"
    fi
    [[ -f "$target.part" && "$(size_of "$target.part")" -eq "$size" ]] && break
    sleep $((attempt * 15))
  done

  if [[ ! -f "$target.part" || "$(size_of "$target.part")" != "$size" ]]; then
    echo "could not fetch $subject to the pinned size $size" >&2
    exit 1
  fi
  if [[ "$(md5_of "$target.part")" != "$md5" ]]; then
    echo "MD5 mismatch for $subject; removing partial file" >&2
    rm -f "$target.part"
    exit 1
  fi
  # Semantic check: tag chain vs FIFF_DIR, measurement info, 102 coil-3024
  # magnetometers, two MaxFilter 2.2.10 tSSS records, DAU_PACK16 buffers,
  # pinned buffer count and leading skip, no inner skips.
  python3 "$TOOL" check-fif --selection "$SELECTION" --subject "$subject" --path "$target.part" < /dev/null
  mv "$target.part" "$target"
  echo "[$(date -Is)] fif fetched $subject bytes=$size"
done < "$SELECTION"

if [[ "$runs" -ne "$EXPECTED_RUNS" ]]; then
  echo "expected $EXPECTED_RUNS runs in selection.tsv, found $runs" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID runs=$runs"
