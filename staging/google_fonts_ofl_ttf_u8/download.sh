#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_fonts_ofl_ttf_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/fonts-main.zip"
if [[ -n "${LOCAL_ARCHIVE:-}" ]]; then
  cp "$LOCAL_ARCHIVE" "$ARCHIVE"
elif [[ -f "$ARCHIVE" ]]; then
  echo "using existing archive: $ARCHIVE"
else
  curl -fL --retry 3 --retry-delay 5 -o "$ARCHIVE" \
    "https://github.com/google/fonts/archive/refs/heads/main.zip"
fi

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
fonts_dir = download_dir / "fonts"
fonts_dir.mkdir(parents=True, exist_ok=True)
selection_path = download_dir / "selection.jsonl"
archive_path = download_dir / "fonts-main.zip"
families_limit = 60
max_files = 180

with zipfile.ZipFile(archive_path) as zf:
    members = [info for info in zf.infolist() if not info.is_dir()]
    ofl_fonts = []
    for info in members:
        parts = Path(info.filename).parts
        if len(parts) >= 4 and parts[1] == "ofl" and info.filename.lower().endswith((".ttf", ".otf")):
            family = parts[2]
            if family:
                ofl_fonts.append((family, info))
    families = sorted({family for family, _ in ofl_fonts})[:families_limit]
    selected = []
    for family in families:
        for _, info in sorted((item for item in ofl_fonts if item[0] == family), key=lambda row: row[1].filename):
            name = Path(info.filename).name
            rel = f"ofl/{family}/{name}"
            out = fonts_dir / family / name
            out.parent.mkdir(parents=True, exist_ok=True)
            payload = zf.read(info)
            if len(payload) < 1024:
                raise SystemExit(f"font is too small: {rel} {len(payload)} bytes")
            out.write_bytes(payload)
            selected.append({"family": family, "name": name, "path": rel, "archive_member": info.filename, "local_path": str(out.relative_to(download_dir))})
            if len(selected) >= max_files:
                break
        if len(selected) >= max_files:
            break

if len(selected) < 40:
    raise SystemExit(f"too few OFL font files selected: {len(selected)}")

with selection_path.open("w", encoding="utf-8") as fh:
    for row in selected:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(f"semantic_validation=ok selected_fonts={len(selected)} families={len(set(row['family'] for row in selected))}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
