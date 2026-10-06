#!/usr/bin/env bash
# Resolve the UK-DALE IAM member table from one 64 KiB tail range of ukdale.zip.
# Documents how members.tsv was produced; download.sh re-runs the same
# resolution and requires an exact match with the pinned members.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ceda_ukdale_iam_appliance_power_u16"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ARCHIVE_URL="https://dap.ceda.ac.uk/edc/efficiency/residential/EnergyConsumption/Domestic/UK-DALE-2017/UK-DALE-FULL-disaggregated/ukdale.zip"
ARCHIVE_BYTES=3585155959
ARCHIVE_ETAG='"59425b9c-d5b12377"'
ARCHIVE_LAST_MODIFIED="Thu, 15 Jun 2017 10:04:12 GMT"
TAIL_BYTES=65536
UA="openzl-public-datasets-ukdale-iam/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

tail_start=$((ARCHIVE_BYTES - TAIL_BYTES))
rm -f "$OUT_DIR/zip_tail.bin.part" "$OUT_DIR/zip_tail.headers.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors --max-time 300 \
  --max-filesize "$((TAIL_BYTES + 1024))" --user-agent "$UA" \
  --range "$tail_start-$((ARCHIVE_BYTES - 1))" \
  --dump-header "$OUT_DIR/zip_tail.headers.part" --output "$OUT_DIR/zip_tail.bin.part" "$ARCHIVE_URL"
mv "$OUT_DIR/zip_tail.headers.part" "$OUT_DIR/zip_tail.headers"
mv "$OUT_DIR/zip_tail.bin.part" "$OUT_DIR/zip_tail.bin"

python3 "$RECIPE_DIR/scripts/ukdale_zip.py" resolve \
  --headers "$OUT_DIR/zip_tail.headers" --tail "$OUT_DIR/zip_tail.bin" \
  --archive-bytes "$ARCHIVE_BYTES" --etag "$ARCHIVE_ETAG" --last-modified "$ARCHIVE_LAST_MODIFIED" \
  --members-out "$OUT_DIR/members.tsv" --metadata-out "$OUT_DIR/metadata"

if cmp -s "$OUT_DIR/members.tsv" "$RECIPE_DIR/members.tsv"; then
  echo "pinned members.tsv is current"
else
  echo "NOTE: $OUT_DIR/members.tsv differs from the pinned $RECIPE_DIR/members.tsv"
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
