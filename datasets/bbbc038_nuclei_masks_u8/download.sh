#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bbbc038_nuclei_masks_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URLS_TSV="$DOWNLOAD_DIR/source_urls.tsv"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
printf 'source_id\turl\treason\n' > "$FAILURES"
if [ -n "${BBBC038_URLS_FILE:-}" ]; then
  cp "$BBBC038_URLS_FILE" "$URLS_TSV"
else
  cat > "$URLS_TSV" <<'EOF'
source_id	url
stage1_train	https://data.broadinstitute.org/bbbc/BBBC038/stage1_train.zip
EOF
fi

failure_count=0
while IFS=$'\t' read -r source_id url; do
  [ -n "$source_id" ] || continue
  out="$DOWNLOAD_DIR/${source_id}.zip"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "zip cache_hit source=$source_id bytes=$(wc -c < "$out" | tr -d ' ')"
  else
    echo "fetch_zip source=$source_id url=$url"
    if ! curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors --connect-timeout 20 --max-time 600 --speed-limit 1024 --speed-time 120 -o "$out.tmp" "$url"; then
      rm -f "$out.tmp"
      printf '%s\t%s\t%s\n' "$source_id" "$url" "curl_failed" >> "$FAILURES"
      failure_count=$((failure_count + 1))
      continue
    fi
    mv "$out.tmp" "$out"
  fi
  python3 - "$out" <<'PY'
from __future__ import annotations
import sys
import zipfile
from pathlib import Path
path = Path(sys.argv[1])
with zipfile.ZipFile(path) as zf:
    names = zf.namelist()
    mask_pngs = [name for name in names if "/masks/" in name.lower() and name.lower().endswith(".png")]
    if not mask_pngs:
        raise SystemExit(f"{path}: ZIP contains no masks/*.png files")
PY
done < <(tail -n +2 "$URLS_TSV")

if [ "$failure_count" -ne 0 ]; then
  echo "[$(date -Is)] download failed dataset=$DATASET_ID failures=$failure_count"
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
