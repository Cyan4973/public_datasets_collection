#!/usr/bin/env bash
# Documents (and can reproduce) how sources.tsv was resolved.  NOT part of the
# download/build/verify path and never run by the autocollect driver.
#
#   1. one unauthenticated GitHub API call: the recursive tree of the pinned
#      commit (git blob SHA-1 and size of every file);
#   2. a 2 KB range GET of every selected .h5 file on raw.githubusercontent.com
#      to read the dataset shape and container dtype from its HDF5 header;
#   3. regenerate the TSV and diff it against the committed sources.tsv.
#
# The GitHub API allows 60 unauthenticated requests per hour per IP; this
# script makes exactly one.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="bosch_cnc_milling_ciss_vibration_i16"
DISC_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
COMMIT="d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1"
RAW_BASE="https://raw.githubusercontent.com/boschresearch/CNC_Machining/$COMMIT"
mkdir -p "$DISC_DIR/heads" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

if [[ ! -s "$DISC_DIR/tree.json" ]]; then
  curl --fail --silent --show-error --location --max-time 120 \
    -H "Accept: application/vnd.github+json" \
    --output "$DISC_DIR/tree.json.part" \
    "https://api.github.com/repos/boschresearch/CNC_Machining/git/trees/$COMMIT?recursive=1"
  mv "$DISC_DIR/tree.json.part" "$DISC_DIR/tree.json"
fi

export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/discover.py" paths "$DISC_DIR/tree.json" > "$DISC_DIR/paths.txt"
while read -r path; do
  target="$DISC_DIR/heads/$path"
  [[ -s "$target" ]] && continue
  mkdir -p "$(dirname "$target")"
  curl --globoff --fail --silent --show-error --location --retry 5 --max-time 60 \
    --range 0-2047 --output "$target" "$RAW_BASE/$path"
done < "$DISC_DIR/paths.txt"

python3 "$RECIPE_DIR/scripts/discover.py" tsv "$DISC_DIR/tree.json" "$DISC_DIR/heads" "$DISC_DIR/sources.discovered.tsv"
if cmp -s "$DISC_DIR/sources.discovered.tsv" "$RECIPE_DIR/sources.tsv"; then
  echo "sources.tsv reproduced exactly"
else
  echo "sources.tsv differs from the rediscovered listing:" >&2
  diff "$RECIPE_DIR/sources.tsv" "$DISC_DIR/sources.discovered.tsv" | head -20 >&2
  exit 1
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
