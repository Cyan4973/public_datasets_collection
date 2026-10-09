#!/usr/bin/env bash
# fetch_range.sh URL START END BLOCK_DIR FIRST_BLOCK TOTAL_SIZE
# Fetch one inclusive byte range with curl, accept it only if the server
# answered 206 with the exact Content-Range and the body has the exact length,
# then split it into 64 KiB block files blk_<index>.bin under BLOCK_DIR.
set -euo pipefail
url="$1"; start="$2"; end="$3"; dir="$4"; first="$5"; total="$6"
BLOCK=65536
want=$((end - start + 1))
[ $((start % BLOCK)) = 0 ] || { echo "ERROR: unaligned range start $start" >&2; exit 1; }
mkdir -p "$dir"
part="$dir/run_${start}.part"
hdr="$dir/run_${start}.headers"
for attempt in 1 2 3 4 5 6; do
  rm -f "$part" "$hdr"
  if curl --fail --silent --show-error --location \
      --retry 8 --retry-delay 5 --retry-all-errors \
      --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
      --user-agent "openzl-public-datasets-sxs-bbh/1.0" \
      --range "$start-$end" --dump-header "$hdr" --output "$part" "$url" < /dev/null; then
    status="$(grep -E '^HTTP/' "$hdr" | tail -n 1 | awk '{print $2}')"
    crange="$(grep -i '^content-range:' "$hdr" | tail -n 1 | tr -d '\r' | awk '{print $3}')"
    size="$(stat -c %s "$part")"
    if [ "$status" = "206" ] && [ "$crange" = "$start-$end/$total" ] && [ "$size" = "$want" ]; then
      tmpd="$dir/.split_${start}"
      rm -rf "$tmpd"
      mkdir -p "$tmpd"
      split --bytes="$BLOCK" --numeric-suffixes="$first" --suffix-length=6 \
        --additional-suffix=.bin "$part" "$tmpd/blk_"
      mv -f "$tmpd"/blk_*.bin "$dir/"
      rm -rf "$tmpd" "$part" "$hdr"
      exit 0
    fi
    echo "WARN range $start-$end of $url: status=$status content-range=$crange bytes=$size (attempt $attempt)" >&2
  fi
  sleep $((attempt * 10))
done
rm -f "$part" "$hdr"
echo "ERROR: could not fetch range $start-$end of $url" >&2
exit 1
