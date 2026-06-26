#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="pfam_seed_alignments_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${PFAM_SEED_URL:-https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.seed.gz}"
OUT="$DOWNLOAD_DIR/Pfam-A.seed.gz"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  echo "probe url=$URL"
  code="$(curl --globoff -fsSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$URL" || true)"
  if [ "$code" != "200" ] && [ "$code" != "206" ]; then
    echo "FATAL: liveness check returned HTTP '$code' for $URL (override PFAM_SEED_URL)." >&2
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

import gzip
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.stat().st_size < 1_000_000:
    raise SystemExit(f"download is unexpectedly small: {path.stat().st_size} bytes")

blocks = 0
rows = 0
with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
    first = fh.readline().strip()
    if first != "# STOCKHOLM 1.0":
        raise SystemExit(f"unexpected first line: {first!r}")
    in_block = True
    for line in fh:
        stripped = line.strip()
        if stripped == "# STOCKHOLM 1.0":
            in_block = True
        elif stripped == "//":
            if in_block:
                blocks += 1
            in_block = False
        elif in_block and stripped and not stripped.startswith("#"):
            parts = stripped.split()
            if len(parts) >= 2:
                rows += 1
        if blocks >= 50 and rows >= 100:
            break
if blocks < 10 or rows < 50:
    raise SystemExit(f"semantic validation found too little Stockholm content: blocks={blocks} rows={rows}")
sha = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"gzip ok: sampled_blocks={blocks} sampled_rows={rows} sha256={sha}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
