#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="cifar10_pixels_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# CIFAR-10 binary distribution; the build extracts per-image RGB pixel intensities (uint8).
URL="${CIFAR10_URL:-https://www.cs.toronto.edu/~kriz/cifar-10-binary.tar.gz}"
OUT="$DOWNLOAD_DIR/cifar-10-binary.tar.gz"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  echo "probe url=$URL"
  # one-byte range GET, following redirects (-L); HEAD is sometimes rejected post-redirect
  code="$(curl --globoff -fsSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$URL" || true)"
  if [ "$code" != "200" ] && [ "$code" != "206" ]; then
    echo "FATAL: liveness check returned HTTP '$code' for $URL (override CIFAR10_URL)."; exit 1
  fi
  echo "liveness ok (HTTP $code); downloading (resumable)"
  # Resumable + stall-based abort: -C - continues the partial $TMP across retries AND
  # across re-runs of this script (we never rm it). Abort a try only if it stalls
  # (< 1 KB/s for 120 s), NOT on total elapsed time -- a slow server must not trigger a
  # restart-from-scratch loop. Re-run the script to keep resuming if it ever exits early.
  curl --globoff -fL -C - --retry 10 --retry-delay 5 \
    --speed-limit 1024 --speed-time 120 \
    -A "$UA" -o "$TMP" "$URL"
  mv "$TMP" "$OUT"
fi

# validate: gzipped tar containing the *_batch.bin record files
python3 - "$OUT" <<'PY'
import sys, tarfile
path = sys.argv[1]
if not tarfile.is_tarfile(path):
    raise SystemExit(f"not a tar: {path}")
with tarfile.open(path, "r:gz") as t:
    bins = [m.name for m in t
            if m.name.rsplit("/", 1)[-1].endswith(".bin")
            and ("data_batch" in m.name or "test_batch" in m.name)]
if len(bins) < 1:
    raise SystemExit(f"no data_batch/test_batch .bin members found")
print(f"tar ok: {len(bins)} batch files ({', '.join(sorted(b.split('/')[-1] for b in bins))})")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
