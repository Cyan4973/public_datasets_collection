#!/usr/bin/env bash
# fetch_span.sh URL START END OUTPUT TOTAL_SIZE
# Fetch the inclusive byte range START-END of a pinned Zenodo file into OUTPUT,
# resumably: an existing OUTPUT.part of k bytes is continued from START+k.
# Every response must be a 206 with the exact Content-Range of the requested
# remainder; the piece is appended only after that check. Stall detection via
# --speed-limit/--speed-time (no hard --max-time).
set -euo pipefail
url="$1"; start="$2"; end="$3"; out="$4"; total="$5"
UA="openzl-public-datasets-gwtc3-pe/1.0"
want=$((end - start + 1))
[ "$want" -gt 0 ] || { echo "ERROR: empty span $start-$end" >&2; exit 1; }
if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$want" ]; then
  exit 0
fi
mkdir -p "$(dirname "$out")"
part="$out.part"
piece="$out.piece"
hdr="$out.headers"
touch "$part"
failures=0
while :; do
  have="$(stat -c %s "$part")"
  if [ "$have" -gt "$want" ]; then
    rm -f "$part"; echo "ERROR: $part grew beyond $want bytes" >&2; exit 1
  fi
  [ "$have" -lt "$want" ] || break
  from=$((start + have))
  rm -f "$piece" "$hdr"
  if curl --fail --silent --show-error --location \
      --retry 8 --retry-delay 5 --retry-all-errors \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --range "$from-$end" --dump-header "$hdr" --output "$piece" "$url" < /dev/null; then
    status="$(grep -E '^HTTP/' "$hdr" | tail -n 1 | awk '{print $2}')"
    crange="$(grep -i '^content-range:' "$hdr" | tail -n 1 | tr -d '\r' | awk '{print $3}')"
    got="$(stat -c %s "$piece")"
    if [ "$status" = "206" ] && [ "$crange" = "$from-$end/$total" ] && [ "$got" = "$((end - from + 1))" ]; then
      cat "$piece" >> "$part"
      rm -f "$piece" "$hdr"
      continue
    fi
    echo "WARN span $from-$end of $url: status=$status content-range=$crange bytes=$got" >&2
  else
    # curl failed mid-transfer: keep whatever arrived if the header was a correct 206.
    status="$(grep -E '^HTTP/' "$hdr" 2>/dev/null | tail -n 1 | awk '{print $2}' || true)"
    crange="$(grep -i '^content-range:' "$hdr" 2>/dev/null | tail -n 1 | tr -d '\r' | awk '{print $3}' || true)"
    if [ "$status" = "206" ] && [ "$crange" = "$from-$end/$total" ] && [ -s "$piece" ]; then
      echo "WARN span $from-$end of $url interrupted after $(stat -c %s "$piece") bytes; resuming" >&2
      cat "$piece" >> "$part"
    fi
  fi
  rm -f "$piece" "$hdr"
  failures=$((failures + 1))
  [ "$failures" -le 12 ] || { echo "ERROR: could not fetch span $start-$end of $url" >&2; exit 1; }
  sleep $((failures * 10))
done
mv "$part" "$out"
