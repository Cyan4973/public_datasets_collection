#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="modelnet10_off_mesh_vertices_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

TARGET="$DOWNLOAD_DIR/ModelNet10.zip"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${MODELNET10_MAX_FILE_BYTES:-800000000}"
HARD_MAX_FILE_BYTES=1000000000
MIN_OFF_FILES="${MODELNET10_MIN_OFF_FILES:-4000}"
MIN_CLASSES="${MODELNET10_MIN_CLASSES:-10}"
if [[ -n "${MODELNET10_URL:-}" ]]; then
  URLS=("$MODELNET10_URL")
else
  URLS=(
    "http://3dvision.princeton.edu/projects/2014/3DShapeNets/ModelNet10.zip"
    "https://3dvision.princeton.edu/projects/2014/3DShapeNets/ModelNet10.zip"
    "https://modelnet.cs.princeton.edu/ModelNet10.zip"
  )
fi

if (( MAX_FILE_BYTES > HARD_MAX_FILE_BYTES )); then
  echo "requested max file size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_FILE_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_FILE_BYTES"
fi

{
  printf 'resource_id\turl\tfile\n'
  for url in "${URLS[@]}"; do
    printf 'modelnet10_zip\t%s\t%s\n' "$url" "$(basename "$TARGET")"
  done
} > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
  SELECTED_URL="${URLS[0]}"
else
  rm -f "$TARGET.tmp"
  SELECTED_URL=""
  for url in "${URLS[@]}"; do
    echo "fetch url=$url"
    if curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
      -o "$TARGET.tmp" "$url"; then
      mv "$TARGET.tmp" "$TARGET"
      SELECTED_URL="$url"
      break
    fi
    rm -f "$TARGET.tmp"
    echo "fetch_failed url=$url"
  done
  if [[ -z "$SELECTED_URL" ]]; then
    echo "all ModelNet10 URLs failed"
    exit 1
  fi
fi

export TARGET DOWNLOAD_DIR MAX_FILE_BYTES MIN_OFF_FILES MIN_CLASSES
export URL="$SELECTED_URL"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
min_off_files = int(os.environ["MIN_OFF_FILES"])
min_classes = int(os.environ["MIN_CLASSES"])

if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size} > {max_file_bytes}")
head = target.read_bytes()[:256].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not ZIP: {target}")

with zipfile.ZipFile(target) as zf:
    infos = [
        info for info in zf.infolist()
        if info.filename.lower().endswith(".off")
        and "__macosx/" not in info.filename.lower()
        and not Path(info.filename).name.startswith("._")
    ]
    classes = set()
    splits = set()
    total_uncompressed = 0
    for info in infos:
        parts = Path(info.filename).parts
        if len(parts) >= 4:
            classes.add(parts[-3])
            splits.add(parts[-2])
        total_uncompressed += info.file_size
    if len(infos) < min_off_files:
        raise SystemExit(f"too few OFF meshes: {len(infos)} < {min_off_files}")
    if len(classes) < min_classes:
        raise SystemExit(f"too few ModelNet classes: {len(classes)} < {min_classes}")
    if not {"train", "test"} <= splits:
        raise SystemExit(f"missing train/test split directories: {sorted(splits)}")

inventory = {
    "dataset_id": "modelnet10_off_mesh_vertices_f32",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": size,
    "max_file_bytes": max_file_bytes,
    "off_files": len(infos),
    "classes": sorted(classes),
    "splits": sorted(splits),
    "off_uncompressed_bytes": total_uncompressed,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok off_files={len(infos)} classes={len(classes)} "
    f"splits={','.join(sorted(splits))} archive_bytes={size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
