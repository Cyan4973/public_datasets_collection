#!/usr/bin/env bash
# Download and validate the exact CC BY 4.0 Xsens C3D archive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_xsens_cymbal_landmarks_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD="$DOWNLOAD_DIR/record_21710617.json"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 180 \
  --output "$RECORD.part" "https://zenodo.org/api/records/21710617"
python3 - "$RECORD.part" <<'PY'
import json
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text())
title = "Cymbal percussion: multimodal motion capture, audio and video (2011)"
metadata = record.get("metadata", {})
if int(record.get("id", 0)) != 21710617 or metadata.get("title") != title:
    raise SystemExit("unexpected Zenodo record identity")
if metadata.get("license", {}).get("id") != "cc-by-4.0":
    raise SystemExit("Zenodo record no longer declares CC BY 4.0")
description = str(metadata.get("description", "")).lower()
if "xsens mvn inertial suit" not in description or "c3d exports" not in description:
    raise SystemExit("record no longer documents Xsens C3D motion capture")
matching = [item for item in record.get("files", []) if item.get("key") == "XsensC3D.zip"]
if len(matching) != 1:
    raise SystemExit("pinned archive is absent or ambiguous")
item = matching[0]
if int(item.get("size", 0)) != 14540671 or item.get("checksum") != "md5:472a8466aa7cbe42e1536412a232ba41":
    raise SystemExit("pinned archive identity changed")
PY
mv "$RECORD.part" "$RECORD"

NAME="XsensC3D.zip"
SIZE="14540671"
MD5="472a8466aa7cbe42e1536412a232ba41"
URL="https://zenodo.org/api/records/21710617/files/XsensC3D.zip/content"
TARGET="$DOWNLOAD_DIR/$NAME"
if [[ -f "$TARGET" ]] && [[ "$(stat -c %s "$TARGET")" == "$SIZE" ]] && [[ "$(md5sum "$TARGET" | awk '{print $1}')" == "$MD5" ]]; then
  echo "verified cached $NAME"
else
  rm -f "$TARGET.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 --max-filesize 14540672 \
    --output "$TARGET.part" "$URL"
  ACTUAL_SIZE="$(stat -c %s "$TARGET.part")"
  ACTUAL_MD5="$(md5sum "$TARGET.part" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$SIZE" ]] || { echo "size mismatch: $ACTUAL_SIZE != $SIZE" >&2; exit 1; }
  [[ "$ACTUAL_MD5" == "$MD5" ]] || { echo "MD5 mismatch: $ACTUAL_MD5 != $MD5" >&2; exit 1; }
  mv "$TARGET.part" "$TARGET"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
