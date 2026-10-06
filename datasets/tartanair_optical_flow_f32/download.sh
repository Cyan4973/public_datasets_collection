#!/usr/bin/env bash
# Range-fetch a deterministic bounded subset of TartanAir V1 dense optical-flow
# frames from the 36 pinned flow_flow.zip archives on the Hugging Face hub.
#
# The archives total 676.8 GB, so none is downloaded whole.  Per archive:
#   1. the last 65,536 bytes (ZIP64 EOCD record + locator + classic EOCD)
#   2. the exact central directory byte range
#   3. for each of 3 selected *_flow.npy members, the exact span from its
#      local file header to the next entry's local header (header + DEFLATE
#      data), validated by raw inflate + CRC32 + .npy header checks.
# Every range response must be 206 with the exact Content-Range, and the
# resolver redirect must confirm the pinned revision and the archive's LFS
# sha256 (x-linked-etag).  Pieces are cached; re-runs only fetch what is
# missing or invalid.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tartanair_optical_flow_f32"
REVISION="65e00180ea952475878a748543e11e9ec20beaac"
HF_REPO="theairlabcmu/tartanair"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/tartanair_flow.py"
SOURCES="$RECIPE_DIR/sources.tsv"
LOCK="$RECIPE_DIR/selection.lock.tsv"
TAIL_BYTES=65536
UA="openzl-public-datasets-tartanair-flow/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION"

CURL_COMMON=(--fail --silent --show-error --location --globoff
  --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

fetch_small() { # url output
  rm -f "$2.part"
  curl "${CURL_COMMON[@]}" --max-time 300 --max-filesize 20000000 --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# --- 1. repository identity, card license, pinned archive list -------------
fetch_small "https://huggingface.co/api/datasets/$HF_REPO/revision/$REVISION" "$DOWNLOAD_DIR/repo_revision.json"
fetch_small "https://huggingface.co/api/datasets/$HF_REPO/tree/$REVISION?recursive=true" "$DOWNLOAD_DIR/repo_tree.json"
python3 "$PY" check-repo --repo-json "$DOWNLOAD_DIR/repo_revision.json" \
  --tree-json "$DOWNLOAD_DIR/repo_tree.json" --sources "$SOURCES"
# Project-site license notice (CC BY 4.0).  Logged, not fatal: the site is a
# general lab page whose layout changes; the HF card license above is fatal.
if fetch_small "https://theairlab.org/tartanair-dataset/" "$DOWNLOAD_DIR/tartanair_dataset_page.html"; then
  python3 "$PY" check-license-page --page "$DOWNLOAD_DIR/tartanair_dataset_page.html"
else
  echo "WARNING license_page: could not fetch https://theairlab.org/tartanair-dataset/"
fi

# --- 2. per-archive range fetches --------------------------------------------
fetch_range() { # url start end output size etag
  local url="$1" start="$2" end="$3" out="$4" size="$5" etag="$6"
  rm -f "$out.part" "$out.headers"
  curl "${CURL_COMMON[@]}" --range "$start-$end" \
    --dump-header "$out.headers" --output "$out.part" "$url"
  python3 "$PY" check-headers --headers "$out.headers" --body "$out.part" \
    --size "$size" --etag "$etag" --start "$start" --end "$end"
  rm -f "$out.headers"
}

selection_tmp="$DOWNLOAD_DIR/selection.tsv.part"
printf 'zip_path\tmember\ttrajectory\tspan_start\tspan_end\tcompressed_size\tuncompressed_size\tcrc32\n' > "$selection_tmp"
archives=0
members=0
fetched_requests=0
while IFS=$'\t' read -r -u 3 zip_path env difficulty size_bytes lfs_sha256 xet_hash; do
  [[ "$zip_path" != "zip_path" ]] || continue
  url="https://huggingface.co/datasets/$HF_REPO/resolve/$REVISION/$zip_path"
  zdir="$DOWNLOAD_DIR/zips/$env/$difficulty"
  mkdir -p "$zdir/members"
  echo "archive $zip_path size=$size_bytes lfs_sha256=$lfs_sha256"

  tail_file="$zdir/tail.bin"
  tail_start=$((size_bytes - TAIL_BYTES))
  if [[ ! -s "$tail_file" ]] || [[ "$(stat -c %s "$tail_file")" != "$TAIL_BYTES" ]] \
    || ! cd_info="$(python3 "$PY" tail-info --tail "$tail_file" --zip-size "$size_bytes" 2>/dev/null)"; then
    fetch_range "$url" "$tail_start" "$((size_bytes - 1))" "$tail_file" "$size_bytes" "$lfs_sha256"
    mv "$tail_file.part" "$tail_file"
    fetched_requests=$((fetched_requests + 1))
    cd_info="$(python3 "$PY" tail-info --tail "$tail_file" --zip-size "$size_bytes")"
  fi
  read -r cd_offset cd_size cd_entries <<< "$cd_info"
  echo "  central_directory offset=$cd_offset size=$cd_size entries=$cd_entries"

  cd_file="$zdir/cd.bin"
  sel_file="$zdir/selection.tsv"
  if [[ ! -s "$cd_file" ]] || [[ "$(stat -c %s "$cd_file")" != "$cd_size" ]] \
    || ! python3 "$PY" select --sources "$SOURCES" --zip-path "$zip_path" \
      --tail "$tail_file" --cd "$cd_file" > "$sel_file" 2>/dev/null; then
    fetch_range "$url" "$cd_offset" "$((cd_offset + cd_size - 1))" "$cd_file" "$size_bytes" "$lfs_sha256"
    mv "$cd_file.part" "$cd_file"
    fetched_requests=$((fetched_requests + 1))
    python3 "$PY" select --sources "$SOURCES" --zip-path "$zip_path" \
      --tail "$tail_file" --cd "$cd_file" > "$sel_file"
  fi

  while IFS=$'\t' read -r -u 4 _zip member trajectory span_start span_end csize usize crc32; do
    entry_file="$zdir/members/${trajectory}__${member##*/}.zipentry"
    expected_bytes=$((span_end - span_start + 1))
    if [[ -s "$entry_file" ]] && [[ "$(stat -c %s "$entry_file")" = "$expected_bytes" ]] \
      && python3 "$PY" check-member --entry "$entry_file" --name "$member" \
        --csize "$csize" --usize "$usize" --crc32 "$crc32" > /dev/null 2>&1; then
      echo "  cache_hit $member"
    else
      [[ ! -e "$entry_file" ]] || echo "  cache_invalid $member (refetching)"
      rm -f "$entry_file"
      echo "  fetch $member span=$span_start-$span_end bytes=$expected_bytes crc32=$crc32"
      fetch_range "$url" "$span_start" "$span_end" "$entry_file" "$size_bytes" "$lfs_sha256"
      python3 "$PY" check-member --entry "$entry_file.part" --name "$member" \
        --csize "$csize" --usize "$usize" --crc32 "$crc32"
      mv "$entry_file.part" "$entry_file"
      fetched_requests=$((fetched_requests + 1))
    fi
    members=$((members + 1))
  done 4< "$sel_file"
  cat "$sel_file" >> "$selection_tmp"
  archives=$((archives + 1))
done 3< "$SOURCES"

mv "$selection_tmp" "$DOWNLOAD_DIR/selection.tsv"
if [[ -f "$LOCK" ]]; then
  if cmp -s "$LOCK" "$DOWNLOAD_DIR/selection.tsv"; then
    echo "selection matches $LOCK"
  else
    echo "FATAL: realized selection differs from the recipe lock $LOCK" >&2
    diff "$LOCK" "$DOWNLOAD_DIR/selection.tsv" | head -20 >&2 || true
    exit 1
  fi
fi
expected_archives=$(($(wc -l < "$SOURCES") - 1))
[[ "$archives" = "$expected_archives" && "$members" = "$((3 * expected_archives))" ]] || {
  echo "FATAL: expected $expected_archives archives / $((3 * expected_archives)) members, got $archives / $members" >&2
  exit 1
}
echo "download_summary archives=$archives members=$members range_requests_this_run=$fetched_requests" \
  "download_dir_bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
