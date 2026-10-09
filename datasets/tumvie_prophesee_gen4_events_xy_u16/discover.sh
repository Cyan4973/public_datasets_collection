#!/usr/bin/env bash
# Re-derive sequences.tsv (the pinned per-sequence window table) from the live server.
#
# For each of the 21 non-calibration TUM-VIE sequences it reads size / ETag /
# Last-Modified of <seq>-events_left.h5 from a one-byte range GET, then walks the
# HDF5 metadata (superblock, groups, events/x and events/y object headers and
# chunk B-tree nodes) with small 4 KiB range GETs until the pinned 128-chunk
# window is resolved, and prints one sequences.tsv row.  Only metadata is
# fetched (~40 KB per sequence); no event chunks.
#
# Usage: DATA_DIR=/tmp/somewhere bash discover.sh > sequences.tsv.new
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="tumvie_prophesee_gen4_events_xy_u16"
BASE_URL="https://tumevent-vi.vision.in.tum.de"
HELPER=(python3 -I "$RECIPE_DIR/scripts/tumvie_events.py" --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT")
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --connect-timeout 30 --max-time 120)
SEQUENCES=(mocap-1d-trans mocap-3d-trans mocap-6dof mocap-desk mocap-desk2 mocap-shake mocap-shake2
  office-maze running-easy running-hard skate-easy skate-hard loop-floor0 loop-floor1 loop-floor2
  loop-floor3 floor2-dark bike-easy bike-hard bike-night slide)

printf 'sequence\tfile_size\tetag\tlast_modified\tn_events\twindow_start_chunk\tx_stored_bytes\ty_stored_bytes\tx_table_sha256\ty_table_sha256\n'
for seq in "${SEQUENCES[@]}"; do
  url="$BASE_URL/$seq/$seq-events_left.h5"
  meta="$DATA_ROOT/downloads/$DATASET_ID/$seq/meta"
  mkdir -p "$meta"
  hdr="$("${CURL[@]}" --range 0-0 --output /dev/null --dump-header - "$url" | tr -d '\r')"
  size="$(printf '%s\n' "$hdr" | sed -n 's#^[Cc]ontent-[Rr]ange: bytes 0-0/\([0-9][0-9]*\)$#\1#p' | tail -1)"
  etag="$(printf '%s\n' "$hdr" | sed -n 's#^[Ee][Tt]ag: "\(.*\)"$#\1#p' | tail -1)"
  lastmod="$(printf '%s\n' "$hdr" | sed -n 's#^[Ll]ast-[Mm]odified: \(.*\)$#\1#p' | tail -1)"
  [[ "$size" =~ ^[0-9]+$ && -n "$etag" ]] || { echo "FATAL: no size/ETag for $seq" >&2; exit 1; }
  for _ in $(seq 1 60); do
    step="$("${HELPER[@]}" plan --seq "$seq" --size "$size")"
    [ "$step" = "DONE" ] && break
    read -r tag off len <<<"$step"
    [[ "$tag" = NEED && "$off" =~ ^[0-9]+$ && "$len" =~ ^[0-9]+$ && "$len" -ge 1 && "$len" -le 65536 ]] \
      || { echo "FATAL: bad planner output '$step'" >&2; exit 1; }
    "${CURL[@]}" --range "$off-$((off + len - 1))" -H "If-Match: \"$etag\"" --max-filesize 70000 \
      --output "$meta/$off-$len.bin.part" "$url"
    [ "$(stat -c %s "$meta/$off-$len.bin.part")" = "$len" ] || { echo "FATAL: short range for $seq" >&2; exit 1; }
    mv "$meta/$off-$len.bin.part" "$meta/$off-$len.bin"
  done
  [ "$step" = "DONE" ] || { echo "FATAL: planner did not converge for $seq" >&2; exit 1; }
  "${HELPER[@]}" discover-row --seq "$seq" --etag "$etag" --last-modified "$lastmod"
done
