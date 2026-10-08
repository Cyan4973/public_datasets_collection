#!/usr/bin/env bash
# fetch_range.sh URL START END OUTPUT TOTAL ETAG
#
# Fetch one exact byte range of a pinned S3 object with curl. The response
# must be a 206 whose Content-Range is exactly "bytes START-END/TOTAL" and
# whose ETag equals the pinned S3 ETag of the whole object, so every range
# provably comes from the same object version. An existing file of the right
# size is kept (re-runs resume at range granularity). Called by download.sh,
# usually through xargs -P for parallel metadata-block rounds.
set -euo pipefail

USER_AGENT="openzl-public-datasets-icon-ivm-a/1.0"
url="$1" start="$2" end="$3" output="$4" total="$5" etag="$6"
expected=$((end - start + 1))

if [ -f "$output" ] && [ "$(stat -c %s "$output")" = "$expected" ]; then
  exit 0
fi
mkdir -p "$(dirname "$output")"
rm -f "$output.part" "$output.hdr"
curl --fail --silent --show-error --location \
  --retry 10 --retry-delay 5 --retry-all-errors \
  --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
  --user-agent "$USER_AGENT" --range "$start-$end" \
  --dump-header "$output.hdr" --output "$output.part" "$url" < /dev/null

content_range="$(tr -d '\r' < "$output.hdr" | grep -i '^content-range:' | tail -n 1 | cut -d' ' -f2- || true)"
etag_seen="$(tr -d '\r"' < "$output.hdr" | grep -i '^etag:' | tail -n 1 | cut -d' ' -f2- || true)"
size="$(stat -c %s "$output.part")"
if [ "$content_range" != "bytes $start-$end/$total" ]; then
  rm -f "$output.part" "$output.hdr"
  echo "ERROR: unexpected Content-Range '$content_range' for $url (want bytes $start-$end/$total)" >&2
  exit 1
fi
if [ "$etag_seen" != "$etag" ]; then
  rm -f "$output.part" "$output.hdr"
  echo "ERROR: ETag '$etag_seen' != pinned '$etag' for $url" >&2
  exit 1
fi
if [ "$size" != "$expected" ]; then
  rm -f "$output.part" "$output.hdr"
  echo "ERROR: range $start-$end of $url returned $size bytes, expected $expected" >&2
  exit 1
fi
mv "$output.part" "$output"
rm -f "$output.hdr"
