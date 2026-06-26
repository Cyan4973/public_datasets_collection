#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="coco_panoptic_val2017_labels_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${COCO_PANOPTIC_URL:-http://images.cocodataset.org/annotations/panoptic_annotations_trainval2017.zip}"
OUT="$DOWNLOAD_DIR/panoptic_annotations_trainval2017.zip"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  echo "probe url=$URL"
  code="$(curl --globoff -fsSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$URL" || true)"
  if [ "$code" != "200" ] && [ "$code" != "206" ]; then
    echo "FATAL: liveness check returned HTTP '$code' for $URL (override COCO_PANOPTIC_URL)." >&2
    exit 1
  fi
  echo "liveness ok (HTTP $code); downloading (resumable)"
  curl --globoff -fL -C - --retry 10 --retry-delay 5 \
    --speed-limit 1024 --speed-time 180 \
    -A "$UA" -o "$TMP" "$URL"
  mv "$TMP" "$OUT"
fi

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import io
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
if not zipfile.is_zipfile(path):
    raise SystemExit(f"not a zip archive: {path}")

with zipfile.ZipFile(path) as zf:
    names = set(zf.namelist())
    json_name = "annotations/panoptic_val2017.json"
    nested_name = "annotations/panoptic_val2017.zip"
    if json_name not in names:
        raise SystemExit(f"missing {json_name}")
    if nested_name not in names:
        raise SystemExit(f"missing {nested_name}")
    with zf.open(json_name) as fh:
        meta = json.load(fh)
    if not meta.get("annotations") or not meta.get("categories"):
        raise SystemExit("panoptic_val2017.json lacks annotations/categories")
    with zipfile.ZipFile(io.BytesIO(zf.read(nested_name))) as val_zf:
        val_names = set(val_zf.namelist())
        pngs = [n for n in val_names if n.startswith("panoptic_val2017/") and n.endswith(".png")]
        if len(pngs) < 100:
            raise SystemExit(f"too few panoptic validation PNGs: {len(pngs)}")
        ann_files = {a.get("file_name") for a in meta["annotations"] if a.get("file_name")}
        missing = [f"panoptic_val2017/{fn}" for fn in sorted(ann_files)[:20]
                   if f"panoptic_val2017/{fn}" not in val_names]
        if missing:
            raise SystemExit(f"missing annotation PNG members, first examples: {missing[:3]}")
    print(f"zip ok: annotations={len(meta['annotations'])} categories={len(meta['categories'])} pngs={len(pngs)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
