#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="argo_gdac_ctd_profiles_f32"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PLAN="$RECIPE_DIR/download_plan.tsv"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
total=0
while IFS=$'\t' read -r wmo expected sha256 url; do
  [[ "$wmo" != "wmo" ]] || continue
  target="$DOWNLOAD_DIR/${wmo}_prof.nc"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit path=$target"
  else
    curl --fail --location --retry 4 --retry-delay 3 --max-time 1800 \
      --max-filesize 250000000 --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
  actual="$(wc -c < "$target")"
  if (( actual != expected )); then
    echo "source size mismatch wmo=$wmo expected=$expected actual=$actual" >&2
    exit 1
  fi
  total=$((total + actual))
done < "$PLAN"
if (( total != 239866364 )); then
  echo "aggregate source size mismatch expected=239866364 actual=$total" >&2
  exit 1
fi

python3 "$RECIPE_DIR/scripts/argo_netcdf.py" validate-download \
  --download-dir "$DOWNLOAD_DIR" --plan "$PLAN"
echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$total"
