#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="maestro_midi_notes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# MAESTRO v3 piano performances (MIDI only). The build parses note-on events into two
# native 8-bit families (pitch, velocity), one sample per performance.
URL="${MAESTRO_URL:-https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0-midi.zip}"
OUT="$DOWNLOAD_DIR/maestro-v3.0.0-midi.zip"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  # fail-fast liveness check (one-byte range GET, follows redirects) before the ~85 MB pull
  echo "probe url=$URL"
  code="$(curl --globoff -fsSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$URL" || true)"
  if [ "$code" != "200" ] && [ "$code" != "206" ]; then
    echo "FATAL: liveness check returned HTTP $code for $URL (override MAESTRO_URL)."; exit 1
  fi
  echo "liveness ok (HTTP $code); downloading (resumable)"
  # resumable + stall-based abort (no hard total-time cap that would restart a slow server)
  curl --globoff -fL -C - --retry 10 --retry-delay 5 \
    --speed-limit 1024 --speed-time 120 \
    -A "$UA" -o "$TMP" "$URL"
  mv "$TMP" "$OUT"
fi

# validate it is a zip containing MIDI files
python3 - "$OUT" <<'PY'
import sys, zipfile
path = sys.argv[1]
if not zipfile.is_zipfile(path):
    raise SystemExit(f"not a zip: {path}")
with zipfile.ZipFile(path) as z:
    midis = [n for n in z.namelist() if n.lower().endswith((".midi", ".mid"))]
if len(midis) < 5:
    raise SystemExit(f"too few MIDI members: {len(midis)}")
print(f"zip ok: {len(midis)} MIDI files")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
