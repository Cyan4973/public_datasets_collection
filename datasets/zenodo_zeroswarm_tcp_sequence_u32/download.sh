#!/usr/bin/env bash
# Reuse verified local cache files or download the exact Zero-SWARM sources.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_zeroswarm_tcp_sequence_u32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
CACHE_DIR="$REPO_ROOT/$DATA_DIR/downloads/zenodo_zeroswarm_modbus_registers_u16"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

matches_identity() {
  local path="$1" size="$2" md5="$3"
  [[ -f "$path" ]] \
    && [[ "$(stat -c %s "$path")" == "$size" ]] \
    && [[ "$(md5sum "$path" | awk '{print $1}')" == "$md5" ]]
}

reuse_or_fetch() {
  local target="$1" cached="$2" size="$3" md5="$4" max_bytes="$5" url="$6"
  if matches_identity "$target" "$size" "$md5" && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "verified existing $(basename "$target")"
    return
  fi
  local part="$target.part"
  rm -f "$target" "$part"
  if [[ "${FORCE_DOWNLOAD:-0}" != "1" ]] && matches_identity "$cached" "$size" "$md5"; then
    if ! ln "$cached" "$part" 2>/dev/null; then
      cp --reflink=auto "$cached" "$part"
    fi
    echo "reused verified local cache $(basename "$cached")"
  else
    curl --globoff --fail-with-body --silent --show-error --location \
      --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
      --max-time 7200 --max-filesize "$max_bytes" \
      --user-agent "openzl-public-datasets-zeroswarm-tcp-u32/1.0" \
      --output "$part" "$url"
  fi
  matches_identity "$part" "$size" "$md5" || {
    echo "identity mismatch for $(basename "$target")" >&2
    exit 1
  }
  mv "$part" "$target"
}

reuse_or_fetch \
  "$DOWNLOAD_DIR/zenodo_record_15082260.json" \
  "$CACHE_DIR/zenodo_record_15082260.json" \
  5364 a673cc13a98493c7b3dd62b1b8497f4e 1000000 \
  "https://zenodo.org/api/records/15082260"

while IFS=$'\t' read -r capture_id filename size_bytes md5 source_sha256 url; do
  [[ -z "$capture_id" ]] && continue
  [[ "$capture_id" == "capture_id" ]] && continue
  reuse_or_fetch "$DOWNLOAD_DIR/$filename" "$CACHE_DIR/$filename" \
    "$size_bytes" "$md5" 260000000 "$url"
done < "$RECIPE_DIR/selection.tsv"

python3 "$RECIPE_DIR/scripts/tcp32.py" preflight \
  --selection "$RECIPE_DIR/selection.tsv" --profiles "$RECIPE_DIR/profiles.tsv" \
  --record "$DOWNLOAD_DIR/zenodo_record_15082260.json" \
  --download-dir "$DOWNLOAD_DIR" \
  --profile "$DISCOVERY_DIR/source_profile.json"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
