#!/usr/bin/env bash
# Range-fetch pinned density snapshots from The Well post_neutron_star_merger
# HDF5 files on Hugging Face. The 14.1 GB source files are never downloaded:
# only two small metadata ranges per file plus nine 6,488,064-byte density
# snapshots per file (exact HTTP 206 ranges, resumable at byte granularity).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="the_well_post_neutron_star_merger_density_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
REPO="polymathic-ai/post_neutron_star_merger"
REVISION="721253cd3220d158d3088c0cce4558dd444d1353"
FILE_SIZE=14109638656
HEAD_START=0
HEAD_END=65535
DIMS_START=11538432
DIMS_END=11541093
SNAPSHOT_BYTES=6488064
DUMPS="20 40 60 80 100 120 140 160 180"
EXPECTED_SNAPSHOTS=72
UA="openzl-public-datasets-the-well-pnsm-density/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

wd() { python3 "$RECIPE_DIR/scripts/well_density.py" "$@"; }

fetch_small() {
  local url="$1" dest="$2" max_bytes="$3"
  rm -f "$dest.part"
  curl --fail --silent --show-error --location --globoff \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 180 \
    --max-filesize "$max_bytes" --user-agent "$UA" \
    --output "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

# fetch_range URL START END DEST LFS_SHA256 XET_HASH
# Appends only bytes from validated 206 responses whose Content-Range starts
# exactly at the resume offset, so an interrupted run resumes where it stopped.
fetch_range() {
  local url="$1" start="$2" end="$3" dest="$4" lfs="$5" xet="$6"
  local want=$((end - start + 1))
  local part="$dest.part" chunk="$dest.chunk" hdr="$dest.headers"
  local attempt have from rc got
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" = "$want" ]]; then
    echo "cache_hit bytes=$want file=${dest#"$DOWNLOAD_DIR"/}"
    return 0
  fi
  rm -f "$dest"
  for attempt in 1 2 3 4 5 6 7 8; do
    have=0
    [[ -f "$part" ]] && have="$(stat -c %s "$part")"
    if (( have > want )); then
      rm -f "$part"
      have=0
    fi
    (( have == want )) && break
    from=$((start + have))
    rm -f "$chunk" "$hdr"
    rc=0
    curl --fail --silent --show-error --location --globoff \
      --retry 5 --retry-delay 5 --retry-all-errors \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --max-filesize $((want - have + 4096)) \
      --range "$from-$end" --user-agent "$UA" \
      --dump-header "$hdr" --output "$chunk" "$url" || rc=$?
    got=0
    [[ -f "$chunk" ]] && got="$(stat -c %s "$chunk")"
    if (( got > 0 && got <= want - have )) \
      && wd check-headers --headers "$hdr" --start "$from" --end "$end" \
           --total "$FILE_SIZE" --identity "$lfs" --identity "$xet"; then
      cat "$chunk" >> "$part"
    else
      echo "attempt=$attempt rc=$rc discarded response bytes=$got range=$from-$end" >&2
    fi
    rm -f "$chunk"
    (( rc == 0 )) || sleep $((attempt * 10))
  done
  have=0
  [[ -f "$part" ]] && have="$(stat -c %s "$part")"
  if [[ "$have" != "$want" ]]; then
    echo "FATAL: range $start-$end incomplete after retries (have $have of $want bytes)" >&2
    exit 1
  fi
  mv "$part" "$dest"
  echo "fetched bytes=$want range=$start-$end file=${dest#"$DOWNLOAD_DIR"/}"
}

# 1. Live identity and license of the pinned revision.
META_DIR="$DOWNLOAD_DIR/meta"
mkdir -p "$META_DIR"
fetch_small "https://huggingface.co/api/datasets/$REPO/revision/$REVISION" "$META_DIR/revision.json" 2000000
fetch_small "https://huggingface.co/api/datasets/$REPO/tree/$REVISION/data?recursive=true" "$META_DIR/tree_data.json" 2000000
fetch_small "https://huggingface.co/datasets/$REPO/resolve/$REVISION/README.md" "$META_DIR/README.md" 2000000
wd check-meta --revision-json "$META_DIR/revision.json" --tree-json "$META_DIR/tree_data.json" \
  --readme "$META_DIR/README.md" --sources "$RECIPE_DIR/sources.tsv"

# 2. Per file: metadata ranges, layout validation, then the selected dumps.
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'scenario\tdump\tsource_byte_offset\tbytes\tsha256\tlocal_path\n' > "$PLAN.part"
snapshots=0
snapshot_bytes=0
while IFS=$'\t' read -r scenario split repo_path size_bytes lfs_sha256 xet_hash <&3; do
  [[ "$scenario" != "scenario" ]] || continue
  [[ "$size_bytes" = "$FILE_SIZE" ]] || { echo "FATAL: unexpected size for $repo_path" >&2; exit 1; }
  url="https://huggingface.co/datasets/$REPO/resolve/$REVISION/$repo_path"
  sdir="$DOWNLOAD_DIR/scenario_$scenario"
  mkdir -p "$sdir"
  echo "[$(date -Is)] scenario=$scenario split=$split file=$repo_path"
  fetch_range "$url" "$HEAD_START" "$HEAD_END" "$sdir/head.bin" "$lfs_sha256" "$xet_hash"
  fetch_range "$url" "$DIMS_START" "$DIMS_END" "$sdir/dims.bin" "$lfs_sha256" "$xet_hash"
  wd inspect-head --head "$sdir/head.bin" --dims "$sdir/dims.bin" --out "$sdir/layout.json"
  for dump in $DUMPS; do
    offset="$(wd snapshot-offset --layout "$sdir/layout.json" --dump "$dump")"
    dest="$sdir/density_dump$(printf '%03d' "$dump").f32le"
    fetch_range "$url" "$offset" $((offset + SNAPSHOT_BYTES - 1)) "$dest" "$lfs_sha256" "$xet_hash"
    if ! wd check-snapshot --file "$dest"; then
      mv "$dest" "$dest.invalid"
      echo "FATAL: semantically invalid density snapshot scenario=$scenario dump=$dump" >&2
      exit 1
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$scenario" "$dump" "$offset" "$SNAPSHOT_BYTES" \
      "$(sha256sum "$dest" | awk '{print $1}')" "${dest#"$DATA_ROOT"/}" >> "$PLAN.part"
    snapshots=$((snapshots + 1))
    snapshot_bytes=$((snapshot_bytes + SNAPSHOT_BYTES))
  done
done 3< "$RECIPE_DIR/sources.tsv"
mv "$PLAN.part" "$PLAN"

if [[ "$snapshots" != "$EXPECTED_SNAPSHOTS" ]]; then
  echo "FATAL: fetched $snapshots snapshots, expected $EXPECTED_SNAPSHOTS" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID snapshots=$snapshots snapshot_bytes=$snapshot_bytes"
