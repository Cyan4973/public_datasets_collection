#!/usr/bin/env bash
# Download the exact CC BY 4.0 honeybee accelerometer PCM16 source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_accelerometer_pcm16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_JSON="$DOWNLOAD_DIR/zenodo_record_7018660.json"
curl --fail --silent --show-error --location --retry 5 --max-time 120 \
  --output "$RECORD_JSON.part" "https://zenodo.org/api/records/7018660"
python3 - "$RECORD_JSON.part" <<'PY'
import html
import json
import re
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
metadata = record.get("metadata", {})
if int(record.get("id", 0)) != 7018660 or metadata.get("title") != "Audio D18":
    raise SystemExit("unexpected Zenodo record identity or title")
license_obj = metadata.get("license", {})
if not isinstance(license_obj, dict) or license_obj.get("id") != "cc-by-4.0":
    raise SystemExit(f"record no longer declares CC BY 4.0: {license_obj}")
description = html.unescape(re.sub(r"<[^>]+>", " ", str(metadata.get("description", ""))))
description = re.sub(r"\s+", " ", description).strip().lower()
required = (
    "accelerometer data",
    "honeybee vibrations",
    "60 points",
    "one point on the df space plot = one second accelerometer data",
)
if any(text not in description for text in required):
    raise SystemExit("record description no longer documents the expected accelerometer segmentation")
PY
mv "$RECORD_JSON.part" "$RECORD_JSON"

NAME="D 18.wav"
SIZE="5760044"
MD5="118ac1ee5a3ff3bc491b3103b06119b9"
URL="https://zenodo.org/api/records/7018660/files/D%2018.wav/content"
TARGET="$DOWNLOAD_DIR/$NAME"
if [[ -f "$TARGET" ]] && [[ "$(stat -c %s "$TARGET")" == "$SIZE" ]] && \
    [[ "$(md5sum "$TARGET" | awk '{print $1}')" == "$MD5" ]]; then
  echo "verified cached $NAME"
else
  rm -f "$TARGET.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 \
    --output "$TARGET.part" "$URL"
  ACTUAL_SIZE="$(stat -c %s "$TARGET.part")"
  ACTUAL_MD5="$(md5sum "$TARGET.part" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$SIZE" ]] || {
    echo "size mismatch: $ACTUAL_SIZE != $SIZE" >&2
    exit 1
  }
  [[ "$ACTUAL_MD5" == "$MD5" ]] || {
    echo "MD5 mismatch: $ACTUAL_MD5 != $MD5" >&2
    exit 1
  }
  mv "$TARGET.part" "$TARGET"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
