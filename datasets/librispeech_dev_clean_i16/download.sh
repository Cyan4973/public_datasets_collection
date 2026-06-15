#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="librispeech_dev_clean_i16"
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
ARCHIVE="$DOWNLOAD_DIR/dev-clean.tar.gz"
if [[ -n "${LOCAL_ARCHIVE:-}" ]]; then
  cp "$LOCAL_ARCHIVE" "$ARCHIVE"
elif [[ -f "$ARCHIVE" ]]; then
  echo "using existing archive: $ARCHIVE"
else
  curl -fL --retry 3 --retry-delay 5 -o "$ARCHIVE" \
    "https://www.openslr.org/resources/12/dev-clean.tar.gz"
fi

if command -v md5sum >/dev/null 2>&1; then
  echo "42e2234ba48799c1f50f24a7926300a1  $ARCHIVE" | md5sum -c -
else
  echo "md5sum not available; checksum validation skipped"
fi

export ARCHIVE DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

archive = Path(os.environ["ARCHIVE"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
inventory_path = download_dir / "archive_inventory.json"

with tarfile.open(archive, "r:gz") as tf:
    members = [member for member in tf.getmembers() if member.isfile()]
    flacs = [member for member in members if member.name.startswith("LibriSpeech/dev-clean/") and member.name.endswith(".flac")]
    transcripts = [member for member in members if member.name.startswith("LibriSpeech/dev-clean/") and member.name.endswith(".trans.txt")]

if len(flacs) < 2500:
    raise SystemExit(f"too few FLAC utterances in archive: {len(flacs)}")
if len(transcripts) < 50:
    raise SystemExit(f"too few transcript files in archive: {len(transcripts)}")

inventory = {
    "archive": str(archive),
    "archive_size_bytes": archive.stat().st_size,
    "flac_count": len(flacs),
    "transcript_count": len(transcripts),
    "first_flac": flacs[0].name,
    "last_flac": flacs[-1].name,
}
inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok flac_count={len(flacs)} transcript_count={len(transcripts)} archive_bytes={archive.stat().st_size}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"

