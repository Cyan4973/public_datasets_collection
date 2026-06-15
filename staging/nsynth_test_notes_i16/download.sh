#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nsynth_test_notes_i16"
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
ARCHIVE="$DOWNLOAD_DIR/nsynth-test.jsonwav.tar.gz"
if [[ -n "${LOCAL_ARCHIVE:-}" ]]; then
  cp "$LOCAL_ARCHIVE" "$ARCHIVE"
elif [[ -f "$ARCHIVE" ]]; then
  echo "using existing archive: $ARCHIVE"
else
  curl -fL --retry 3 --retry-delay 5 -o "$ARCHIVE" \
    "http://download.magenta.tensorflow.org/datasets/nsynth/nsynth-test.jsonwav.tar.gz"
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
with tarfile.open(archive, "r:gz") as tf:
    members = [member for member in tf.getmembers() if member.isfile()]
    wavs = [member for member in members if member.name.endswith(".wav") and "/audio/" in member.name]
    metadata = [member for member in members if member.name.endswith("examples.json")]
if len(wavs) < 4000:
    raise SystemExit(f"too few NSynth WAV files: {len(wavs)}")
if not metadata:
    raise SystemExit("missing NSynth examples.json metadata")
inventory = {
    "archive": str(archive),
    "archive_size_bytes": archive.stat().st_size,
    "wav_count": len(wavs),
    "metadata_count": len(metadata),
    "first_wav": wavs[0].name,
    "last_wav": wavs[-1].name,
}
(download_dir / "archive_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok wav_count={len(wavs)} archive_bytes={archive.stat().st_size}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
