#!/usr/bin/env bash
# Documents how sources.tsv was resolved. Not part of the download/build path:
# it re-lists the OSF project (small JSON API pages only) and regenerates a
# candidate sources.tsv under $DATA_DIR/discovery/<id>/ for comparison.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="goldencheetah_opendata_cycling_cadence_u8"
DISC_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
PAGES_DIR="$DISC_DIR/pages"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
API="https://api.osf.io/v2/nodes/6hfpz/files/osfstorage/"

mkdir -p "$PAGES_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

# Node metadata + license (expects CC0 1.0 Universal).
curl -sS --fail --max-time 60 "https://api.osf.io/v2/nodes/6hfpz/" -o "$DISC_DIR/node.json"
curl -sS --fail --max-time 60 "https://api.osf.io/v2/licenses/563c1cf88c5e4a3877f9e96c/" -o "$DISC_DIR/license.json"
grep -q '"name":"CC0 1.0 Universal"' "$DISC_DIR/license.json" || { echo "license changed" >&2; exit 1; }

# Name-sorted paging is stable (unsorted offset paging drifts: duplicates and
# misses were observed). 100 entries per page; the INDEX folder is ignored.
rm -f "$PAGES_DIR"/page_*.json
page=1
while :; do
  out="$PAGES_DIR/page_$(printf %03d "$page").json"
  curl -sS --globoff --fail --retry 5 --retry-delay 3 --retry-all-errors --max-time 120 \
    "$API?page=$page&page[size]=100&sort=name" -o "$out"
  if ! grep -q '"next":"https' "$out"; then
    break
  fi
  page=$((page + 1))
done
echo "pages=$page"

python3 -I "$RECIPE_DIR/scripts/select_sources.py" --pages "$PAGES_DIR" --out "$DISC_DIR/sources.tsv"
if cmp -s "$DISC_DIR/sources.tsv" "$RECIPE_DIR/sources.tsv"; then
  echo "rediscovered selection is identical to pinned sources.tsv"
else
  echo "WARNING: rediscovered selection differs from pinned sources.tsv (see $DISC_DIR/sources.tsv)"
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
