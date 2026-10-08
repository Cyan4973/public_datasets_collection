#!/usr/bin/env bash
# Download the pinned NCLT 2013-01-10 Velodyne tarball and validate it.
#
# The whole 2,926,183,916-byte archive is fetched: its velodyne_sync/ members
# (the per-revolution files this recipe keeps) are stored after the
# 2,771,041,792-byte velodyne_hits.bin member, so no byte range can reach them
# without the preceding gzip stream. Steps:
#   1. self-test the validation tool on synthetic archives
#   2. one-byte range GET: 206, Content-Range total, ETag, Last-Modified
#   3. resumable curl (-C -, stall-based --speed-limit/--speed-time) into .part
#   4. exact size + recomputed S3 multipart ETag (349 parts of 8 MiB) + SHA-256
#   5. stream gzip + tar to EOF in Python (gzip CRC32/ISIZE, tar framing,
#      velodyne_hits.bin size and packet magic, every velodyne_sync member's
#      8-byte record framing and laser_id 0..31) and write members.tsv
#   6. rename .part to the final name only after all checks pass
# Nothing is extracted to disk.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="umich_nclt_velodyne_hdl32e_xyz_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/nclt_tar.py"

ARCHIVE_URL="https://s3.us-east-2.amazonaws.com/nclt.perl.engin.umich.edu/velodyne_data/2013-01-10_vel.tar.gz"
ARCHIVE_BYTES=2926183916
ARCHIVE_ETAG='"3c9d1400e8ccec9c40bdd757221ad172-349"'
ARCHIVE_LAST_MODIFIED="Tue, 27 Sep 2022 11:37:44 GMT"
PART_BYTES=8388608
HITS_BYTES=2771041792
MIN_SYNC_MEMBERS=4000
ARCHIVE="$DOWNLOAD_DIR/2013-01-10_vel.tar.gz"
PART="$ARCHIVE.part"
RECEIPT="$DOWNLOAD_DIR/archive_receipt.json"
MEMBERS="$DOWNLOAD_DIR/members.tsv"
SCAN_REPORT="$DOWNLOAD_DIR/archive_scan.json"
UA="openzl-public-datasets-nclt-velodyne/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$TOOL" self-test

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$ARCHIVE" "$PART" "$RECEIPT" "$MEMBERS" "$SCAN_REPORT"
fi

# Liveness, size and identity: one-byte range GET.
live_headers="$DOWNLOAD_DIR/liveness.headers"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
  --max-time 120 --range 0-0 --user-agent "$UA" --dump-header "$live_headers" \
  --output /dev/null "$ARCHIVE_URL"
python3 "$TOOL" check-headers --headers "$live_headers" --size "$ARCHIVE_BYTES" \
  --etag "$ARCHIVE_ETAG" --last-modified "$ARCHIVE_LAST_MODIFIED"

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

if [ -s "$ARCHIVE" ] && [ -s "$RECEIPT" ] && [ -s "$MEMBERS" ] && [ -s "$SCAN_REPORT" ]; then
  echo "cache_hit archive=$ARCHIVE bytes=$(file_size "$ARCHIVE")"
  python3 "$TOOL" etag --archive "$ARCHIVE" --part-bytes "$PART_BYTES" --size "$ARCHIVE_BYTES" \
    --expected-etag "$ARCHIVE_ETAG" --receipt "$RECEIPT"
else
  if [ -s "$ARCHIVE" ] && [ ! -s "$PART" ]; then
    mv "$ARCHIVE" "$PART"  # incomplete validation from an earlier run: re-check it
  fi
  have="$(file_size "$PART")"
  if [ "$have" -gt "$ARCHIVE_BYTES" ]; then
    echo "partial file larger than the pinned size ($have > $ARCHIVE_BYTES); restarting"
    rm -f "$PART"
    have=0
  fi
  # curl's own --retry truncates the output back to where that curl run
  # started ("Throwing away N bytes"), so a stall late in the transfer would
  # discard gigabytes. Keep curl's internal retries for connection-level
  # failures and let this loop resume from the current .part size instead.
  attempt=0
  while [ "$have" -lt "$ARCHIVE_BYTES" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 12 ]; then
      echo "FATAL: download incomplete after $((attempt - 1)) curl runs ($have of $ARCHIVE_BYTES bytes)" >&2
      exit 1
    fi
    [ "$attempt" -eq 1 ] || sleep 10
    echo "[$(date -Is)] fetch attempt=$attempt resume_from=$have of $ARCHIVE_BYTES"
    curl --fail --location --silent --show-error --continue-at - \
      --retry 3 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$PART" "$ARCHIVE_URL" || echo "curl exited with status $?"
    have="$(file_size "$PART")"
    if [ "$have" -gt "$ARCHIVE_BYTES" ]; then
      echo "FATAL: partial file grew beyond the pinned size ($have > $ARCHIVE_BYTES)" >&2
      exit 1
    fi
  done
  echo "[$(date -Is)] fetched bytes=$have"
  python3 "$TOOL" etag --archive "$PART" --part-bytes "$PART_BYTES" --size "$ARCHIVE_BYTES" \
    --expected-etag "$ARCHIVE_ETAG" --receipt "$RECEIPT"
  echo "[$(date -Is)] streaming gzip/tar validation"
  python3 "$TOOL" scan --archive "$PART" --hits-bytes "$HITS_BYTES" --min-sync "$MIN_SYNC_MEMBERS" \
    --members "$MEMBERS" --report "$SCAN_REPORT"
  mv "$PART" "$ARCHIVE"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID archive=$ARCHIVE bytes=$(file_size "$ARCHIVE")"
