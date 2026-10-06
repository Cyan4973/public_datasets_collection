#!/usr/bin/env bash
# Download the two pinned Cyprus-transmission PMU steady-state archives
# (GridGnosis Zenodo 20308780 and its GridEye sibling Zenodo 17648863).
#
# Only the "Steady state data.zip" file of each record is fetched; the event
# zips and line-parameter zips are a different regime and are never requested.
# Each archive is fetched whole (its CSV members cover all but ~2 KB of it),
# resumably with curl -C -, then pinned by size and Zenodo MD5, and finally
# checked member-by-member against members.tsv (names, sizes, CRC32, CSV
# header) before it is accepted.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_gridgnosis_pmu_voltage_magnitude_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-pmu-voltage/1.0"

# record_id|archive_key|zenodo file key|size bytes|md5|local file name
ARCHIVES=(
  "20308780|gridgnosis_20308780|Steady state data.zip|894457235|24df9e74aa521ee21cf1fb03d42dceaa|gridgnosis_20308780_steady_state_data.zip"
  "17648863|grideye_17648863|Steady state data.zip|201941844|edf820db5b5d3dfd362df38c7cd32c8e|grideye_17648863_steady_state_data.zip"
)

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

md5_ok() {
  printf '%s  %s\n' "$2" "$1" | md5sum --check --status
}

for spec in "${ARCHIVES[@]}"; do
  IFS='|' read -r record_id archive_key file_key size_bytes md5 local_name <<< "$spec"
  api_url="https://zenodo.org/api/records/$record_id"
  file_url="https://zenodo.org/api/records/$record_id/files/${file_key// /%20}/content"
  record_json="$DOWNLOAD_DIR/record_$record_id.json"
  target="$DOWNLOAD_DIR/$local_name"

  # 1. Live record metadata: identity, CC BY 4.0 license, pinned size + MD5.
  rm -f "$record_json.part"
  curl --fail --silent --show-error --location \
    --retry 8 --retry-delay 5 --retry-all-errors \
    --max-time 180 --max-filesize 20000000 \
    --user-agent "$UA" --header "Accept: application/json" \
    --output "$record_json.part" "$api_url"
  mv "$record_json.part" "$record_json"
  python3 "$RECIPE_DIR/scripts/validate_download.py" record \
    --record-json "$record_json" --record-id "$record_id" \
    --file-key "$file_key" --size "$size_bytes" --md5 "$md5"

  # 2. Archive bytes: resumable, stall-bounded (no hard --max-time).
  if [ -s "$target" ] && [ "$(file_size "$target")" = "$size_bytes" ] \
    && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && md5_ok "$target" "$md5"; then
    echo "cache_hit archive=$archive_key bytes=$size_bytes md5=$md5"
  else
    if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
      rm -f "$target" "$target.part"
    fi
    rm -f "$target"
    attempt=0
    while [ "$(file_size "$target.part")" -lt "$size_bytes" ]; do
      attempt=$((attempt + 1))
      if [ "$attempt" -gt 8 ]; then
        echo "FATAL: archive=$archive_key still incomplete after $((attempt - 1)) curl runs" >&2
        exit 1
      fi
      echo "fetch archive=$archive_key attempt=$attempt have=$(file_size "$target.part") want=$size_bytes"
      curl --fail --silent --show-error --location \
        --continue-at - --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$target.part" "$file_url" || {
          echo "curl exited $? for archive=$archive_key; retrying from $(file_size "$target.part") bytes"
          sleep 10
        }
    done
    actual="$(file_size "$target.part")"
    if [ "$actual" != "$size_bytes" ]; then
      echo "FATAL: archive=$archive_key size $actual != $size_bytes; removing partial file" >&2
      rm -f "$target.part"
      exit 1
    fi
    if ! md5_ok "$target.part" "$md5"; then
      echo "FATAL: archive=$archive_key MD5 mismatch (HTML error body or corrupt resume); removing partial file" >&2
      rm -f "$target.part"
      exit 1
    fi
    mv "$target.part" "$target"
    echo "fetched archive=$archive_key bytes=$size_bytes md5=$md5"
  fi

  # 3. Semantic ZIP check against the pinned member table.
  python3 "$RECIPE_DIR/scripts/validate_download.py" archive \
    --archive "$target" --archive-key "$archive_key" \
    --members "$RECIPE_DIR/members.tsv"
done

echo "[$(date -Is)] download done dataset=$DATASET_ID"
