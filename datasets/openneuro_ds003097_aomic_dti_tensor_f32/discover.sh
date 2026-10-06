#!/usr/bin/env bash
# Metadata-only preflight: reproduces selection.tsv from anonymous S3 listings
# plus one 4 KiB gzip header range per picked object. It downloads no tensor
# payloads. Compare its output with the pinned selection.tsv in this recipe.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="openneuro_ds003097_aomic_dti_tensor_f32"
OUT_DIR="${DISCOVERY_OUT_DIR:-$DATA_ROOT/discovery/$DATASET_ID}"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TARGET="${TARGET_PARTICIPANTS:-32}"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID target=$TARGET out=$OUT_DIR"

python3 "$RECIPE_DIR/scripts/discover_selection.py" \
  --target "$TARGET" \
  --out "$OUT_DIR/selection.tsv" \
  --summary "$OUT_DIR/summary.json"

if [[ -f "$RECIPE_DIR/selection.tsv" ]]; then
  if cmp -s "$OUT_DIR/selection.tsv" "$RECIPE_DIR/selection.tsv"; then
    echo "discovered selection matches pinned selection.tsv"
  else
    echo "WARNING: discovered selection differs from pinned selection.tsv" >&2
    diff "$RECIPE_DIR/selection.tsv" "$OUT_DIR/selection.tsv" | head -20 >&2 || true
  fi
fi
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
