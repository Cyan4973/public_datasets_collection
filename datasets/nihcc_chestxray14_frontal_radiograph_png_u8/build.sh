#!/usr/bin/env bash
# Build one raw uint8 1024x1024 sample per whole 8-bit grayscale ChestX-ray14
# PNG found in the local tarball prefixes (no network access).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nihcc_chestxray14_frontal_radiograph_png_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

if [ ! -s "$DOWNLOAD_DIR/FAQ_CHESTXRAY.pdf" ]; then
  echo "FATAL: missing $DOWNLOAD_DIR/FAQ_CHESTXRAY.pdf; run download.sh first" >&2
  exit 1
fi
for n in 001 002 003 004 005 006 007 008 009 010 011 012; do
  if ! ls "$DOWNLOAD_DIR"/images_${n}.prefix*.tar.gz >/dev/null 2>&1; then
    echo "FATAL: missing prefix of images_${n}.tar.gz; run download.sh first" >&2
    exit 1
  fi
done

python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/faq_check.py" "$DOWNLOAD_DIR/FAQ_CHESTXRAY.pdf"
python3 "$RECIPE_DIR/scripts/nih_decode.py" build "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
