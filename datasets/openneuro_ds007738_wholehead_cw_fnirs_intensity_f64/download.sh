#!/usr/bin/env bash
# Fetch only what the recipe needs from the 24 resting-state SNIRF files of
# OpenNeuro ds007738 1.0.0: license/snapshot metadata, the paginated S3
# listing, HDF5 metadata blocks, and the exact /nirs/data1/dataTimeSeries
# byte range of each file. Aux (eye tracking), stim, probe geometry and
# metaDataTags payloads are never fetched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="openneuro_ds007738_wholehead_cw_fnirs_intensity_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BUCKET="https://s3.amazonaws.com/openneuro.org"
MAX_META_ROUNDS=60
MAX_LISTING_PAGES=20

mkdir -p "$DOWNLOAD_DIR/metadata" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# shellcheck source=scripts/range_lib.sh
source "$RECIPE_DIR/scripts/range_lib.sh"
export PYTHONDONTWRITEBYTECODE=1
TOOL=(python3 -I -B "$RECIPE_DIR/scripts/snirf_fnirs.py")

python3 -I -B "$RECIPE_DIR/scripts/selftest.py"

# 1. License, snapshot and dataset description (live bucket, small files).
for name in dataset_description.json README.txt CHANGES participants.tsv; do
  fetch_small "$BUCKET/ds007738/$name" "$DOWNLOAD_DIR/metadata/$name" 1000000
done

# 2. Full S3 listing of ds007738/ (more than 1000 keys: paginate with the
#    continuation token) to confirm the resting run set, sizes and ETags.
rm -f "$DOWNLOAD_DIR"/metadata/listing_*.xml
cont=""
page=0
while :; do
  url="$BUCKET?list-type=2&prefix=ds007738/&max-keys=1000"
  [ -z "$cont" ] || url="$url&continuation-token=$cont"
  out="$DOWNLOAD_DIR/metadata/listing_$(printf '%03d' "$page").xml"
  fetch_small "$url" "$out" 5000000
  cont="$("${TOOL[@]}" listing-next "$out")"
  page=$((page + 1))
  [ -n "$cont" ] || break
  [ "$page" -lt "$MAX_LISTING_PAGES" ] || die "S3 listing exceeded $MAX_LISTING_PAGES pages"
done
"${TOOL[@]}" check-metadata --download-dir "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"

# 3. HDF5 metadata: superblock -> /nirs/data1 -> dataTimeSeries header and all
#    1134 measurementList groups -> /nirs/probe/wavelengths, read over 1 MiB
#    aligned blocks. Each round fetches the next missing block of every run.
complete=0
for round in $(seq 1 "$MAX_META_ROUNDS"); do
  set +e
  "${TOOL[@]}" meta-plan --download-dir "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"
  status=$?
  set -e
  if [ "$status" = 0 ]; then
    complete=1
    break
  fi
  [ "$status" = 3 ] || exit "$status"
  echo "metadata round=$round"
  while IFS=$'\t' read -r subject block start end url total etag; do
    [ "$subject" != "subject" ] || continue
    fetch_range "$url" "$start" "$end" \
      "$DOWNLOAD_DIR/runs/$subject/meta/blk_$(printf '%06d' "$block").bin" "$total" "$etag"
  done < "$DOWNLOAD_DIR/block_requests.tsv"
done
[ "$complete" = 1 ] || die "HDF5 metadata did not resolve within $MAX_META_ROUNDS rounds"

# 4. Exact dataTimeSeries byte range of each run (resumable, stall-bounded).
while IFS=$'\t' read -r subject start end url total etag local_path; do
  [ "$subject" != "subject" ] || continue
  fetch_range "$url" "$start" "$end" "$DOWNLOAD_DIR/$local_path" "$total" "$etag"
done < "$DOWNLOAD_DIR/data_requests.tsv"

# 5. Semantic validation of every range and SHA-256 inventory.
"${TOOL[@]}" inventory --download-dir "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
