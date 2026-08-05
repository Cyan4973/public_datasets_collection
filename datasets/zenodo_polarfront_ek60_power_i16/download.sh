#!/usr/bin/env bash
# Download and validate the exact CC0 PolarFront EK60 recording.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_polarfront_ek60_power_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD="$DOWNLOAD_DIR/record_7473204.json"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 180 \
  --output "$RECORD.part" "https://zenodo.org/api/records/7473204"
python3 - "$RECORD.part" <<'PY'
import json
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text())
title = "Split-beam echosounder data from keel-mounted EK60 during PolarFront 2022-05 cruise"
metadata = record.get("metadata", {})
if int(record.get("id", 0)) != 7473204 or metadata.get("title") != title:
    raise SystemExit("unexpected Zenodo record identity")
if metadata.get("license", {}).get("id") not in ("cc-zero", "cc0-1.0"):
    raise SystemExit("Zenodo record no longer declares CC0")
description = str(metadata.get("description", "")).lower()
if "simrad ek60" not in description or "18, 38, and 120 khz" not in description:
    raise SystemExit("record no longer documents the selected EK60 acquisition")
name = "PolarFront0522-D20220524-T060111.raw"
matching = [item for item in record.get("files", []) if item.get("key") == name]
if len(matching) != 1:
    raise SystemExit("pinned EK60 file is absent or ambiguous")
item = matching[0]
if int(item.get("size", 0)) != 45896704 or item.get("checksum") != "md5:944f3af1aea3a51cfa7ef7912dde10ba":
    raise SystemExit("pinned EK60 file identity changed")
PY
mv "$RECORD.part" "$RECORD"

NAME="PolarFront0522-D20220524-T060111.raw"
SIZE="45896704"
MD5="944f3af1aea3a51cfa7ef7912dde10ba"
URL="https://zenodo.org/api/records/7473204/files/PolarFront0522-D20220524-T060111.raw/content"
TARGET="$DOWNLOAD_DIR/$NAME"
if [[ -f "$TARGET" ]] && [[ "$(stat -c %s "$TARGET")" == "$SIZE" ]] && [[ "$(md5sum "$TARGET" | awk '{print $1}')" == "$MD5" ]]; then
  echo "verified cached $NAME"
else
  rm -f "$TARGET.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 --max-filesize 45896705 \
    --output "$TARGET.part" "$URL"
  ACTUAL_SIZE="$(stat -c %s "$TARGET.part")"
  ACTUAL_MD5="$(md5sum "$TARGET.part" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$SIZE" ]] || { echo "size mismatch: $ACTUAL_SIZE != $SIZE" >&2; exit 1; }
  [[ "$ACTUAL_MD5" == "$MD5" ]] || { echo "MD5 mismatch: $ACTUAL_MD5 != $MD5" >&2; exit 1; }
  mv "$TARGET.part" "$TARGET"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID"
