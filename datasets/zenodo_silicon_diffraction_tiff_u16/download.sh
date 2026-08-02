#!/usr/bin/env bash
# Download and validate the exact CC BY 4.0 silicon EBSD pattern.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_silicon_diffraction_tiff_u16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_JSON="$DOWNLOAD_DIR/zenodo_record_1450892.json"
curl --fail --silent --show-error --location --retry 5 --max-time 120 \
  --output "$RECORD_JSON.part" "https://zenodo.org/api/records/1450892"
python3 - "$RECORD_JSON.part" <<'PY'
import json
import sys
from pathlib import Path

obj = json.loads(Path(sys.argv[1]).read_text())
if int(obj.get("id", 0)) != 1450892:
    raise SystemExit("unexpected Zenodo record id")
metadata = obj.get("metadata", {})
if metadata.get("title") != "Silicon Single Crystal Diffraction Pattern":
    raise SystemExit("unexpected Zenodo record title")
license_obj = metadata.get("license", {})
if not isinstance(license_obj, dict) or license_obj.get("id") != "cc-by-4.0":
    raise SystemExit(f"record no longer declares CC BY 4.0: {license_obj}")
PY
mv "$RECORD_JSON.part" "$RECORD_JSON"

NAME="Si_pattern1.tif"
SIZE="3715496"
MD5="fb93782184b1b324eed85c1e377cc505"
URL="https://zenodo.org/api/records/1450892/files/Si_pattern1.tif/content"
TARGET="$DOWNLOAD_DIR/$NAME"
if [[ -f "$TARGET" ]] && [[ "$(stat -c %s "$TARGET")" == "$SIZE" ]] && [[ "$(md5sum "$TARGET" | awk '{print $1}')" == "$MD5" ]]; then
  echo "verified cached $NAME"
else
  rm -f "$TARGET.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 \
    --output "$TARGET.part" "$URL"
  ACTUAL_SIZE="$(stat -c %s "$TARGET.part")"
  ACTUAL_MD5="$(md5sum "$TARGET.part" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$SIZE" ]] || { echo "size mismatch: $ACTUAL_SIZE != $SIZE" >&2; exit 1; }
  [[ "$ACTUAL_MD5" == "$MD5" ]] || { echo "MD5 mismatch: $ACTUAL_MD5 != $MD5" >&2; exit 1; }
  mv "$TARGET.part" "$TARGET"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
