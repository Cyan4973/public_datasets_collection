#!/usr/bin/env bash
# Range-fetch only units/spike_amplitudes_uV (+ its VectorIndex) and the HDF5
# metadata needed to locate them, from the two pinned DANDI:000409 sessions.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="dandi_ibl_bwm_spike_amplitudes_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
API="https://api.dandiarchive.org/api/dandisets/000409/versions/0.260309.1324"
MAX_META_ROUNDS=80

mkdir -p "$DOWNLOAD_DIR/metadata" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# shellcheck source=scripts/range_lib.sh
source "$RECIPE_DIR/scripts/range_lib.sh"
export PYTHONDONTWRITEBYTECODE=1
TOOL=(python3 "$RECIPE_DIR/scripts/ibl_amplitudes.py")

python3 "$RECIPE_DIR/scripts/selftest.py"

# 1. Live license and asset identity (published, immutable version).
fetch_small "$API/" "$DOWNLOAD_DIR/metadata/dandiset_version.json" 2000000
for asset_id in $(tail -n +2 "$RECIPE_DIR/sessions.tsv" | cut -f7); do
  fetch_small "$API/assets/$asset_id/" "$DOWNLOAD_DIR/metadata/asset_$asset_id.json" 1000000
done
"${TOOL[@]}" check-metadata --download-dir "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"

# 2. HDF5 metadata: walk superblock -> root group -> /general, /units ->
#    dataset headers -> chunk B-trees over 64 KiB blocks, fetching each block
#    the parser reports missing, until every needed structure resolves.
complete=0
for round in $(seq 1 "$MAX_META_ROUNDS"); do
  set +e
  "${TOOL[@]}" meta-plan --download-dir "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"
  status=$?
  set -e
  if [ "$status" = 0 ]; then
    complete=1
    break
  fi
  [ "$status" = 3 ] || exit "$status"
  echo "metadata round=$round"
  while IFS=$'\t' read -r asset_id block start end url total etag; do
    [ "$asset_id" != "asset_id" ] || continue
    fetch_range "$url" "$start" "$end" \
      "$DOWNLOAD_DIR/sessions/$asset_id/meta/blk_$(printf '%06d' "$block").bin" "$total" "$etag"
  done < "$DOWNLOAD_DIR/block_requests.tsv"
done
[ "$complete" = 1 ] || die "HDF5 metadata did not resolve within $MAX_META_ROUNDS rounds"

# 3. Exact compressed chunk ranges of spike_amplitudes_uV and its index.
while IFS=$'\t' read -r asset_id _kind _element_offset start end _length url total etag local_path; do
  [ "$asset_id" != "asset_id" ] || continue
  fetch_range "$url" "$start" "$end" "$DOWNLOAD_DIR/$local_path" "$total" "$etag"
done < "$DOWNLOAD_DIR/data_ranges.tsv"

# 4. Semantic validation: inflate every chunk, check grid/size/index/pins,
#    and record the SHA-256 of every fetched range.
"${TOOL[@]}" inventory --download-dir "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
