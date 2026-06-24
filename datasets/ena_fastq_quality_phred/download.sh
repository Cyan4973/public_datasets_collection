#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ena_fastq_quality_phred"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# One ENA FASTQ run; the build extracts per-sequencing-cycle Phred quality scores (uint8).
# Default = SRR2584863 _1 (E. coli, Illumina 150bp, Phred+33). gzip keeps the download
# lean relative to the decompressed quality volume.
URL="${ENA_FASTQ_URL:-https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR258/003/SRR2584863/SRR2584863_1.fastq.gz}"
OUT="$DOWNLOAD_DIR/reads.fastq.gz"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  echo "probe url=$URL"
  code="$(curl --globoff -fsS -I -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$URL" || true)"
  if [ "$code" != "200" ] && [ "$code" != "206" ]; then
    echo "FATAL: liveness check returned HTTP '$code' for $URL (override ENA_FASTQ_URL)."; exit 1
  fi
  echo "liveness ok (HTTP $code); downloading"
  rm -f "$TMP"
  curl --globoff -fL --retry 4 --retry-delay 5 --max-time 3600 -A "$UA" -o "$TMP" "$URL"
  mv "$TMP" "$OUT"
fi

# validate: gzip + first record is a 4-line FASTQ with matching seq/qual lengths
python3 - "$OUT" <<'PY'
import gzip, sys
path = sys.argv[1]
with gzip.open(path, "rt", encoding="ascii", errors="replace") as fh:
    rec = [fh.readline().rstrip("\n") for _ in range(4)]
if not rec[0].startswith("@"):
    raise SystemExit(f"first line is not a FASTQ header: {rec[0][:40]!r}")
if rec[2][:1] != "+":
    raise SystemExit(f"third line is not '+': {rec[2][:40]!r}")
if len(rec[1]) != len(rec[3]) or len(rec[3]) < 1:
    raise SystemExit(f"seq/qual length mismatch: {len(rec[1])} vs {len(rec[3])}")
qmin = min(ord(c) for c in rec[3])
print(f"fastq ok: read_len={len(rec[3])} qual_min_ord={qmin} (>=33 expected for Phred+33)")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
