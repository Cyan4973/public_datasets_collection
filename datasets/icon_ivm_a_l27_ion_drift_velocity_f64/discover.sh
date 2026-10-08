#!/usr/bin/env bash
# Authoring-time helper (metadata only): list the HelioCloud IVM-A L2-7 prefix
# with paginated S3 ListObjectsV2 requests and regenerate sources.tsv with the
# deterministic day selection. download.sh does NOT run this; it uses the
# committed sources.tsv. Usage: bash discover.sh [OUTPUT_TSV]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icon_ivm_a_l27_ion_drift_velocity_f64"
OUT="${1:-$RECIPE_DIR/sources.tsv}"
WORK="$DATA_ROOT/logs/$DATASET_ID/discover"
BUCKET="https://gov-nasa-hdrl-data1.s3.amazonaws.com/"
PREFIX="spdf/cdaweb/data/icon/l2-7_ivm-a/"
COUNT=120
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$WORK"
rm -f "$WORK"/page_*.xml
next_page=""
page=0
while :; do
  page=$((page + 1))
  args=(--data-urlencode "list-type=2" --data-urlencode "prefix=$PREFIX")
  [ -n "$next_page" ] && args+=(--data-urlencode "continuation-token=$next_page")
  curl --fail --silent --show-error --max-time 120 --retry 5 -G "${args[@]}" \
    -o "$WORK/page_$(printf '%03d' "$page").xml" "$BUCKET"
  next_page="$(python3 "$RECIPE_DIR/scripts/discover.py" next-token "$WORK/page_$(printf '%03d' "$page").xml")"
  [ -n "$next_page" ] || break
  [ "$page" -lt 50 ] || { echo "ERROR: too many listing pages" >&2; exit 1; }
done
python3 "$RECIPE_DIR/scripts/discover.py" select --pages "$WORK"/page_*.xml --count "$COUNT" --out "$OUT"
sha256sum "$OUT"
