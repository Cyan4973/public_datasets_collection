#!/usr/bin/env bash
# Provenance tool, not part of download/build/verify: reproduce the session
# selection pinned in sessions.tsv from the published DANDI:000409 asset list.
# Reads /general/lab of each subject's first processed asset (139 subjects)
# and the stored spike count of each lab's first asset through small 16 KiB
# range requests (~10-20 MB in total), then applies the rule documented in
# scripts/discover_sessions.py and writes subject_labs.tsv and selection.tsv
# under $DATA_DIR/discovery/<id>/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="dandi_ibl_bwm_spike_amplitudes_f64"
WORK="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
API="https://api.dandiarchive.org/api/dandisets/000409/versions/0.260309.1324"

mkdir -p "$WORK/blocks" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

# shellcheck source=scripts/range_lib.sh
source "$RECIPE_DIR/scripts/range_lib.sh"
export PYTHONDONTWRITEBYTECODE=1
TOOL=(python3 "$RECIPE_DIR/scripts/discover_sessions.py")

fetch_small "$API/assets/?glob=*desc-processed_behavior%2Becephys.nwb&order=path&page_size=1000" \
  "$WORK/processed_assets.json" 5000000

complete=0
for round in $(seq 1 60); do
  set +e
  "${TOOL[@]}" plan --listing "$WORK/processed_assets.json" --work "$WORK/blocks"
  status=$?
  set -e
  if [ "$status" = 0 ]; then
    complete=1
    break
  fi
  [ "$status" = 3 ] || exit "$status"
  while IFS=$'\t' read -r asset_id block start end url total; do
    [ "$asset_id" != "asset_id" ] || continue
    fetch_range "$url" "$start" "$end" "$WORK/blocks/$asset_id/blk_$(printf '%06d' "$block").bin" "$total" "-" \
      > /dev/null
  done < "$WORK/blocks/block_requests.tsv"
  echo "discover round=$round"
done
[ "$complete" = 1 ] || die "discovery did not converge"

"${TOOL[@]}" select --listing "$WORK/processed_assets.json" --work "$WORK/blocks" \
  --out-dir "$WORK" --recipe-dir "$RECIPE_DIR"
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
