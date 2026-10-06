# shellcheck shell=bash
# curl helpers shared by download.sh and discover.sh (sourced, not executed).
# All network I/O of the recipe goes through these two functions.

USER_AGENT="openzl-public-datasets-dandi-ibl-bwm-amplitudes/1.0"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

# fetch_small URL OUTPUT MAX_BYTES
# Small JSON metadata; always refreshed so license/asset checks see the live API.
fetch_small() {
  local url="$1" output="$2" cap="$3"
  mkdir -p "$(dirname "$output")"
  rm -f "$output.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 300 --max-filesize "$cap" \
    --user-agent "$USER_AGENT" --output "$output.part" "$url" < /dev/null
  mv "$output.part" "$output"
  echo "fetched url=$url bytes=$(stat -c %s "$output")"
}

# fetch_range URL START END OUTPUT TOTAL ETAG
# One exact byte range of a pinned S3 blob. The response must be a 206 whose
# Content-Range is exactly START-END/TOTAL and whose ETag is the pinned DANDI
# etag of the whole object, so every range provably comes from the same blob.
# Existing complete files are kept (re-runs resume at range granularity).
# ETAG "-" disables only the ETag comparison (discover.sh probes of unpinned
# assets); download.sh always passes the pinned etag.
fetch_range() {
  local url="$1" start="$2" end="$3" output="$4" total="$5" etag="$6"
  local expected=$((end - start + 1))
  if [ -f "$output" ] && [ "$(stat -c %s "$output")" = "$expected" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$output")"
  rm -f "$output.part" "$output.hdr"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
    --user-agent "$USER_AGENT" --range "$start-$end" \
    --dump-header "$output.hdr" --output "$output.part" "$url" < /dev/null
  local content_range etag_seen size sha
  content_range="$(tr -d '\r' < "$output.hdr" | grep -i '^content-range:' | tail -n 1 | cut -d' ' -f2- || true)"
  etag_seen="$(tr -d '\r"' < "$output.hdr" | grep -i '^etag:' | tail -n 1 | cut -d' ' -f2- || true)"
  size="$(stat -c %s "$output.part")"
  if [ "$content_range" != "bytes $start-$end/$total" ]; then
    rm -f "$output.part"
    die "unexpected Content-Range '$content_range' for $url $start-$end (want bytes $start-$end/$total)"
  fi
  # discover.sh passes "-" (unpinned candidate assets); download.sh always pins.
  if [ "$etag" != "-" ] && [ "$etag_seen" != "$etag" ]; then
    rm -f "$output.part"
    die "ETag '$etag_seen' != pinned '$etag' for $url"
  fi
  if [ "$size" != "$expected" ]; then
    rm -f "$output.part"
    die "range $start-$end of $url returned $size bytes, expected $expected"
  fi
  sha="$(sha256sum "$output.part" | cut -d' ' -f1)"
  mv "$output.part" "$output"
  rm -f "$output.hdr"
  echo "range_fetched start=$start end=$end bytes=$expected sha256=$sha file=${output##*/}"
}
