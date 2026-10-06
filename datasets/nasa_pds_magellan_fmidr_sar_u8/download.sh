#!/usr/bin/env bash
# Fetch the 685 pinned files of six Magellan F-MIDRs (336 framelet images,
# their detached PDS3 labels, per-MIDR HIST.TAB/HIST.LBL, and the F-MIDR
# data-set description label) from the anonymous asc-pds-magellan bucket.
# Every file is checked against the pinned byte size and S3 single-part
# ETag (= MD5); labels and VICAR headers are then schema-validated.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_magellan_fmidr_sar_u8"
BASE_URL="${MAGELLAN_BASE_URL:-https://asc-pds-magellan.s3.us-west-2.amazonaws.com}"
SOURCES="$RECIPE_DIR/sources.tsv"
EXPECTED_SOURCES_SHA256="9b8fb2e78c08e043774348d9141ba76762f6aa8ef16770de65ec85c89f00d6a0"
EXPECTED_FILES=685
EXPECTED_BYTES=354780608
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-magellan-fmidr/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID base=$BASE_URL"

printf '%s  %s\n' "$EXPECTED_SOURCES_SHA256" "$SOURCES" | sha256sum --check --status || {
  echo "FATAL: sources.tsv identity changed" >&2
  exit 1
}
read -r plan_files plan_bytes < <(awk -F'\t' 'NR > 1 { n++; s += $5 } END { print n, s }' "$SOURCES")
if [[ "$plan_files" != "$EXPECTED_FILES" || "$plan_bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL: source plan has files=$plan_files bytes=$plan_bytes" >&2
  exit 1
fi
echo "source_plan=ok files=$plan_files bytes=$plan_bytes"

# Liveness: one-byte range GET on the first pinned framelet.
first_url="$BASE_URL/$(awk -F'\t' 'NR == 2 { print $1 "/" $2 "/" $3 }' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url" || {
  echo "FATAL: liveness probe failed for $first_url" >&2
  exit 1
}

file_ok() {
  local path="$1" size="$2" md5="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" == "$size" ]] || return 1
  [[ "$(md5sum "$path" | cut -d' ' -f1)" == "$md5" ]]
}

count=0
fetched=0
while IFS=$'\t' read -r volume directory file kind size md5; do
  [[ "$volume" == "volume" ]] && continue
  count=$((count + 1))
  target="$DOWNLOAD_DIR/$volume/$directory/$file"
  if file_ok "$target" "$size" "$md5"; then
    continue
  fi
  mkdir -p "$(dirname "$target")"
  rm -f "$target"
  part="$target.part"
  if [[ -f "$part" && "$(stat -c %s "$part")" -ge "$size" ]]; then
    file_ok "$part" "$size" "$md5" || rm -f "$part"
  fi
  if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
    curl --fail --location --silent --show-error --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$BASE_URL/$volume/$directory/$file"
  fi
  if ! file_ok "$part" "$size" "$md5"; then
    echo "FATAL: $volume/$directory/$file failed size/MD5 check (expected $size bytes, md5 $md5)" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  fetched=$((fetched + 1))
  if (( fetched % 50 == 0 )); then
    echo "progress fetched=$fetched checked=$count/$EXPECTED_FILES"
  fi
done < "$SOURCES"
echo "transfer_done checked=$count fetched_this_run=$fetched"

python3 "$RECIPE_DIR/scripts/magellan_fmidr.py" validate-downloads \
  --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
