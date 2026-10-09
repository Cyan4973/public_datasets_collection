#!/usr/bin/env bash
# Re-derive sims.tsv from the Zenodo "sxs" community listing (metadata only).
# Not part of the acquisition path: download.sh uses the committed sims.tsv.
# Writes listing pages and the re-derived table under
# $DATA_DIR/downloads/<id>/discover/ and diffs it against the pinned table.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="sxs_bbh_extrapolated_strain_modes_f64"
OUT="$DATA_ROOT/downloads/$DATASET_ID/discover"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$OUT" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start"

page=1
while :; do
  f="$OUT/page_$(printf %03d "$page").json"
  if [ ! -s "$f" ]; then
    curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
      --max-time 120 --get "https://zenodo.org/api/records" \
      --data-urlencode "communities=sxs" --data-urlencode 'q="SXS:BBH"' \
      --data-urlencode "size=25" --data-urlencode "page=$page" --data-urlencode "sort=oldest" \
      --output "$f.part" < /dev/null
    mv "$f.part" "$f"
    sleep 0.6
  fi
  hits="$(python3 -I -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["hits"]["hits"]))' "$f")"
  [ "$hits" -gt 0 ] || { rm -f "$f"; break; }
  page=$((page + 1))
done
python3 -I "$RECIPE_DIR/scripts/select_sims.py" "$OUT" "$OUT/sims.rederived.tsv"
if diff -q "$OUT/sims.rederived.tsv" "$RECIPE_DIR/sims.tsv" > /dev/null; then
  echo "sims.tsv matches the live listing"
else
  echo "WARNING: live listing differs from pinned sims.tsv:"
  diff "$OUT/sims.rederived.tsv" "$RECIPE_DIR/sims.tsv" || true
fi
echo "[$(date -Is)] discover done"
