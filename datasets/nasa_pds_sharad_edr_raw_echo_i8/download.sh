#!/usr/bin/env bash
# Fetch SCIENCE8BIT.FMT, 24 pinned SHARAD EDR SS19 labels and their *_S.DAT
# science telemetry tables (948,446,004 bytes) from PDS Geosciences
# (MROSH_0001), check sizes and the volume-published MD5s, then semantically
# validate every label and every table row.
#   FORCE_DOWNLOAD=1  refetch even when a complete file is present
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_sharad_edr_raw_echo_i8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

echo "cbea3799951cdb8bf8063d07cf49b588b24565a6148f81669add0d773497aaeb  $RECIPE_DIR/sources.tsv" | sha256sum -c -
python3 -I "$RECIPE_DIR/scripts/sharad.py" plan --sources "$RECIPE_DIR/sources.tsv" --out "$PLAN"

md5_of() { md5sum "$1" | awk '{print $1}'; }

# Liveness: one-byte range GET on the first science table.
first_url="$(awk -F'\t' '$1=="sdat" {print $3; exit}' "$PLAN")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 --output /dev/null "$first_url"

while IFS=$'\t' read -r kind local_filename url nbytes md5; do
  [[ "$kind" == "kind" ]] && continue
  target="$DOWNLOAD_DIR/$local_filename"
  part="$target.part"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]] && \
     { [[ "$nbytes" == "-" ]] || [[ "$(stat -c %s "$target")" == "$nbytes" ]]; } && \
     [[ "$(md5_of "$target")" == "$md5" ]]; then
    echo "cache_hit $local_filename"
    continue
  fi
  rm -f "$target"
  if [[ "$nbytes" == "-" ]]; then
    # Small text file (label / format): plain fetch.
    curl --fail --location --silent --show-error --retry 10 --retry-delay 5 --max-time 300 \
      --max-filesize 1000000 --output "$part" "$url"
  else
    if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$nbytes" ]]; then rm -f "$part"; fi
    attempt=0
    while [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$nbytes" ]]; do
      attempt=$((attempt + 1))
      if (( attempt > 10 )); then echo "giving up on $local_filename" >&2; exit 1; fi
      echo "fetch $local_filename bytes=$nbytes attempt=$attempt"
      curl --fail --location --silent --show-error -C - --retry 10 --retry-delay 5 \
        --speed-limit 1024 --speed-time 120 --max-filesize 100000000 \
        --output "$part" "$url" || sleep 5
    done
    [[ "$(stat -c %s "$part")" == "$nbytes" ]] || { echo "size mismatch: $local_filename" >&2; rm -f "$part"; exit 1; }
  fi
  if [[ "$(md5_of "$part")" != "$md5" ]]; then
    echo "MD5 mismatch vs MROSH_0001 volume MD5 list: $local_filename (removed)" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  echo "ok $local_filename"
done < "$PLAN"

# Semantic validation: SCIENCE8BIT.FMT layout (3600 x 8-bit MSB_INTEGER at
# byte 187); every label is SS19 / presum 04 / 08-bit / PRI 1428 / STATIC /
# DQ 0 / RECORD_BYTES 3786 with the pinned row count; every table row has
# OPERATIVE_MODE 51, the label gain, science data type and no FPGA error/test
# flag; payload not degenerate.
python3 -I "$RECIPE_DIR/scripts/sharad.py" validate --sources "$RECIPE_DIR/sources.tsv" --download-dir "$DOWNLOAD_DIR"

du -sb "$DOWNLOAD_DIR" | awk '{print "download_dir_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
