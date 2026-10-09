#!/usr/bin/env bash
# Fetch the pinned TUM-VIE left-camera event windows with exact HTTP byte ranges.
#
# Never downloads whole event files (1.2-17.9 GB each, 168.7 GB in total).
# For each of the 21 non-calibration sequences pinned in sequences.tsv:
#   1. walk the HDF5 metadata (superblock, groups, events/x + events/y object
#      headers, chunk B-tree nodes) with 4 KiB range GETs, driven by the
#      pure-Python planner in scripts/tumvie_events.py (Python never uses the
#      network; it only says which range it needs next);
#   2. require the re-derived window (event count, window start chunk, chunk
#      address/size table SHA-256 for x and y) to equal the pinned row;
#   3. fetch the window's Blosc chunks as 2-4 coalesced byte spans;
#   4. decode every chunk (Blosc1 + zstd CLI + byte unshuffle) and reject the
#      sequence unless all x <= 1279, all y <= 719 and the window is not degenerate.
# Every range request carries If-Match with the pinned ETag and must return 206
# with the exact Content-Range. Expected transfer: ~167 MB.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="tumvie_prophesee_gen4_events_xy_u16"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://tumevent-vi.vision.in.tum.de"
PAGE_URL="https://cvg.cit.tum.de/data/datasets/visual-inertial-event-dataset"
UA="openzl-public-datasets-tumvie-download/1.0"
HELPER=(python3 -I "$RECIPE_DIR/scripts/tumvie_events.py" --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT")

mkdir -p "$DL" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

command -v zstd >/dev/null || { echo "FATAL: zstd CLI is required to validate Blosc/ZSTD chunks" >&2; exit 1; }
python3 -I "$RECIPE_DIR/scripts/selftest.py"

CURL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

# --- 1. license evidence: official dataset page -------------------------------------------
page="$DL/tumvie_dataset_page.html"
"${CURL[@]}" --max-time 300 --max-filesize 5000000 --output "$page.part" "$PAGE_URL"
mv "$page.part" "$page"
"${HELPER[@]}" check-license --page "$page"

# --- helper: one exact, ETag-guarded byte range ---------------------------------------------
fetch_range() {
  local url="$1" start="$2" len="$3" size="$4" etag="$5" out="$6"
  local end=$((start + len - 1))
  if [ -s "$out" ] && [ "$(stat -c %s "$out")" = "$len" ]; then
    return 0
  fi
  rm -f "$out.part" "$out.hdr"
  "${CURL[@]}" --range "$start-$end" -H "If-Match: \"$etag\"" --max-filesize $((len + 1024)) \
    --dump-header "$out.hdr" --output "$out.part" "$url"
  local actual
  actual="$(stat -c %s "$out.part")"
  if [ "$actual" != "$len" ]; then
    echo "FATAL: $url range $start-$end returned $actual bytes, expected $len" >&2
    rm -f "$out.part" "$out.hdr"
    exit 1
  fi
  "${HELPER[@]}" check-headers --header-file "$out.hdr" --start "$start" --end "$end" --size "$size" --etag "$etag" \
    || { rm -f "$out.part" "$out.hdr"; exit 1; }
  rm -f "$out.hdr"
  mv "$out.part" "$out"
}

# --- 2. per-sequence metadata walk, window check, chunk spans, decode check -----------------
seq_count=0
while IFS=$'\t' read -r -u 3 seq size etag _lastmod _rest; do
  [ "$seq" = "sequence" ] && continue
  url="$BASE_URL/$seq/$seq-events_left.h5"
  meta="$DL/$seq/meta"
  data="$DL/$seq/data"
  mkdir -p "$meta" "$data"
  steps=0
  while :; do
    step="$("${HELPER[@]}" plan --seq "$seq")"
    [ "$step" = "DONE" ] && break
    read -r tag off len <<<"$step"
    [[ "$tag" = NEED && "$off" =~ ^[0-9]+$ && "$len" =~ ^[0-9]+$ && "$len" -ge 1 && "$len" -le 65536 ]] \
      || { echo "FATAL: bad planner output '$step' for $seq" >&2; exit 1; }
    steps=$((steps + 1))
    [ "$steps" -le 80 ] || { echo "FATAL: metadata walk for $seq did not converge" >&2; exit 1; }
    fetch_range "$url" "$off" "$len" "$size" "$etag" "$meta/$off-$len.bin"
  done
  "${HELPER[@]}" check-plan --seq "$seq"
  nspans=0
  while read -r off len; do
    [[ "$off" =~ ^[0-9]+$ && "$len" =~ ^[0-9]+$ && "$len" -le 33554432 ]] \
      || { echo "FATAL: bad span '$off $len' for $seq" >&2; exit 1; }
    fetch_range "$url" "$off" "$len" "$size" "$etag" "$data/$off-$len.bin"
    nspans=$((nspans + 1))
  done < <("${HELPER[@]}" spans --seq "$seq")
  if ! "${HELPER[@]}" check-seq --seq "$seq"; then
    rm -f "$data"/*.bin
    echo "FATAL: $seq failed semantic validation; chunk spans removed" >&2
    exit 1
  fi
  seq_count=$((seq_count + 1))
  echo "[$(date -Is)] fetched $seq metadata_ranges=$(find "$meta" -name '*.bin' | wc -l) spans=$nspans"
done 3< "$RECIPE_DIR/sequences.tsv"
[ "$seq_count" = 21 ] || { echo "FATAL: expected 21 sequences, got $seq_count" >&2; exit 1; }

total_bytes="$(du -sb "$DL" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID sequences=$seq_count download_dir_bytes=$total_bytes"
