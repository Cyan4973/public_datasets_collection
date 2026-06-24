#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="encode_methylation_pct_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# One ENCODE WGBS bedMethyl file (per-CpG methylation). The build extracts percent
# methylation (column 11) for covered CpGs (column 10 > 0), one sample per chromosome.
# @@download 307-redirects to a fast CDN (S3/Azure) that honours HTTP range, so the
# download is resumable.
URL="${ENCODE_METH_URL:-https://www.encodeproject.org/files/ENCFF424XKF/@@download/ENCFF424XKF.bed.gz}"
OUT="$DOWNLOAD_DIR/methylation.bed.gz"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  # liveness: HEAD the ENCODE URL WITHOUT -L; a 3xx redirect means the file exists
  # (the CDN target may reject HEAD, so don't follow here).
  echo "probe url=$URL"
  code="$(curl --globoff -fsS -I -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$URL" || true)"
  case "$code" in
    200|206|301|302|303|307|308) echo "liveness ok (HTTP $code); downloading (resumable)";;
    *) echo "FATAL: liveness check returned HTTP '$code' for $URL (override ENCODE_METH_URL)."; exit 1;;
  esac
  # resumable (-C -, follows redirect with -L) + stall-based abort (no hard total-time cap)
  curl --globoff -fL -C - --retry 10 --retry-delay 5 \
    --speed-limit 1024 --speed-time 120 \
    -A "$UA" -o "$TMP" "$URL"
  mv "$TMP" "$OUT"
fi

# validate: gzip + bedMethyl shape (>= 11 columns; col 11 = percent methylation)
python3 - "$OUT" <<'PY'
import gzip, sys
path = sys.argv[1]
with gzip.open(path, "rt", encoding="ascii", errors="replace") as fh:
    for line in fh:
        if line.startswith(("#", "track", "browser")):
            continue
        cols = line.rstrip("\n").split("\t")
        break
if len(cols) < 11:
    raise SystemExit(f"expected >= 11 bedMethyl columns, got {len(cols)}: {cols}")
try:
    cov = int(cols[9]); pct = int(round(float(cols[10])))
except Exception as e:
    raise SystemExit(f"bad coverage/pctMeth in {cols[9:11]}: {e}")
print(f"bedMethyl ok: cols={len(cols)} chrom={cols[0]} coverage={cov} pctMeth={pct}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
