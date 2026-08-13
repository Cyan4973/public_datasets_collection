#!/usr/bin/env bash
# Acquire or locally reuse and validate the exact CC0 PolarFront EK60 recording.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_polarfront_ek60_angles_i8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
REUSE_DIR="$REPO_ROOT/$DATA_DIR/downloads/zenodo_polarfront_ek60_power_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
NAME="PolarFront0522-D20220524-T060111.raw"
SIZE=45896704
MD5="944f3af1aea3a51cfa7ef7912dde10ba"
URL="https://zenodo.org/api/records/7473204/files/$NAME/content"
TARGET="$DOWNLOAD_DIR/$NAME"
RECORD="$DOWNLOAD_DIR/record_7473204.json"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

valid_source() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" == "$SIZE" ]] || return 1
  [[ "$(md5sum "$path" | awk '{print $1}')" == "$MD5" ]]
}

validate_record() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
title = "Split-beam echosounder data from keel-mounted EK60 during PolarFront 2022-05 cruise"
metadata = record.get("metadata", {})
if int(record.get("id", 0)) != 7473204 or metadata.get("title") != title:
    raise SystemExit("unexpected Zenodo record identity")
if metadata.get("license", {}).get("id") not in ("cc-zero", "cc0-1.0"):
    raise SystemExit("Zenodo record no longer declares CC0")
description = str(metadata.get("description", "")).lower()
if "simrad ek60" not in description or "18, 38, and 120 khz" not in description:
    raise SystemExit("record no longer documents the selected EK60 acquisition")
matches = [item for item in record.get("files", []) if item.get("key") == "PolarFront0522-D20220524-T060111.raw"]
if len(matches) != 1:
    raise SystemExit("pinned EK60 file is absent or ambiguous")
item = matches[0]
if int(item.get("size", 0)) != 45896704 or item.get("checksum") != "md5:944f3af1aea3a51cfa7ef7912dde10ba":
    raise SystemExit("pinned EK60 file identity changed")
PY
}

if [[ -f "$REUSE_DIR/record_7473204.json" ]]; then
  validate_record "$REUSE_DIR/record_7473204.json"
  cp --reflink=auto "$REUSE_DIR/record_7473204.json" "$RECORD"
  echo "reused validated accepted-cache metadata"
else
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 180 \
    --output "$RECORD.part" "https://zenodo.org/api/records/7473204"
  validate_record "$RECORD.part"
  mv "$RECORD.part" "$RECORD"
fi

if valid_source "$TARGET"; then
  echo "validated existing $NAME"
elif valid_source "$REUSE_DIR/$NAME"; then
  rm -f "$TARGET" "$TARGET.part"
  ln "$REUSE_DIR/$NAME" "$TARGET" 2>/dev/null || cp --reflink=auto "$REUSE_DIR/$NAME" "$TARGET"
  echo "reused validated accepted-cache source $REUSE_DIR/$NAME"
else
  rm -f "$TARGET" "$TARGET.part"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 1800 --max-filesize 45896705 \
    --output "$TARGET.part" "$URL"
  valid_source "$TARGET.part" || { echo "source size or MD5 mismatch" >&2; exit 1; }
  mv "$TARGET.part" "$TARGET"
fi

validate_record "$RECORD"
valid_source "$TARGET" || { echo "source validation failed" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID"
