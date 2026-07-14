#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="statlog_landsat_satellite_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Statlog (Landsat Satellite), UCI ML Repository (dataset 146). Primary source is
# the pinned UCI static zip; the classic ml-databases directory is a stable
# fallback that ships the exact same sat.trn/sat.tst files.
ZIP_URL="${STATLOG_ZIP_URL:-https://archive.ics.uci.edu/static/public/146/statlog+landsat+satellite.zip}"
DIRECT_BASE="${STATLOG_DIRECT_BASE:-https://archive.ics.uci.edu/ml/machine-learning-databases/statlog/satimage}"
ARCHIVE="$DOWNLOAD_DIR/statlog_landsat_satellite.zip"
CANON_TRN="$EXTRACT_DIR/sat.trn"
CANON_TST="$EXTRACT_DIR/sat.tst"
ZIP_EXTRACT="$EXTRACT_DIR/zip"

rm -rf "$ZIP_EXTRACT"
mkdir -p "$ZIP_EXTRACT"

got_from_zip=0
if curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 -o "$ARCHIVE" "$ZIP_URL"; then
  if unzip -o "$ARCHIVE" -d "$ZIP_EXTRACT" >/dev/null 2>&1; then
    got_from_zip=1
  else
    echo "warning: zip downloaded but could not be unzipped; will try direct files"
  fi
else
  echo "warning: static zip fetch failed; will try direct files"
fi

TRN=""
TST=""
if [ "$got_from_zip" = "1" ]; then
  TRN="$(find "$ZIP_EXTRACT" -type f -iname 'sat.trn' | head -n1 || true)"
  TST="$(find "$ZIP_EXTRACT" -type f -iname 'sat.tst' | head -n1 || true)"
  [ -z "$TRN" ] && TRN="$(find "$ZIP_EXTRACT" -type f -iname '*.trn' | head -n1 || true)"
  [ -z "$TST" ] && TST="$(find "$ZIP_EXTRACT" -type f -iname '*.tst' | head -n1 || true)"
fi

if [ -n "$TRN" ] && [ -n "$TST" ]; then
  cp -f "$TRN" "$CANON_TRN"
  cp -f "$TST" "$CANON_TST"
  echo "using training file from zip: $TRN"
  echo "using test file from zip: $TST"
else
  echo "zip did not yield sat.trn/sat.tst; fetching direct UCI ml-databases files"
  curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 -o "$CANON_TRN" "$DIRECT_BASE/sat.trn"
  curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 -o "$CANON_TST" "$DIRECT_BASE/sat.tst"
fi

# Reject semantically invalid payloads (HTML error pages, wrong files, truncation):
# each Statlog line must be 36 spectral attributes in 0..255 plus a 1..7 label.
TRN="$CANON_TRN" TST="$CANON_TST" python3 - <<'PY'
import os
from pathlib import Path

def check(path, name):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise SystemExit(f"missing/empty {name}: {path}")
    n = 0
    with p.open("r", encoding="utf-8", errors="strict") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            toks = line.split()
            if len(toks) != 37:
                raise SystemExit(f"{name}: expected 37 tokens, got {len(toks)}: {line[:60]!r}")
            try:
                vals = [int(t) for t in toks]
            except ValueError:
                raise SystemExit(f"{name}: non-integer token in line: {line[:60]!r}")
            if any(v < 0 or v > 255 for v in vals[:36]):
                raise SystemExit(f"{name}: spectral attribute outside 0..255")
            if not (1 <= vals[36] <= 7):
                raise SystemExit(f"{name}: class label outside 1..7: {vals[36]}")
            n += 1
            if n >= 200:
                break
    if n < 100:
        raise SystemExit(f"{name}: too few rows ({n}) for a valid Statlog file")
    print(f"validated {name}: first {n} rows shape-checked ok")

check(os.environ["TRN"], "sat.trn")
check(os.environ["TST"], "sat.tst")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
