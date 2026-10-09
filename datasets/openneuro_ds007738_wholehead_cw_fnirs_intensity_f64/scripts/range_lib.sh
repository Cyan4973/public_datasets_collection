# shellcheck shell=bash
# curl helpers for download.sh (sourced, not executed). All network I/O of the
# recipe goes through these functions.

USER_AGENT="openzl-public-datasets-openneuro-ds007738-fnirs/1.0"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

# fetch_small URL OUTPUT MAX_BYTES
# Small metadata (JSON, text, S3 listing pages); always refreshed so the
# license and listing checks see the live bucket.
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
# One exact byte range [START, END] of a pinned S3 object, resumable.
# curl cannot combine --continue-at with --range, so resumption is done here:
# the bytes already in OUTPUT.part are kept and the next request asks for
# START+have..END. Every 206 response must carry Content-Range
# "bytes <from>-END/TOTAL" and the pinned ETag of the whole object, so every
# byte provably comes from the same pinned object. Transfers are bounded by a
# stall rule (--speed-limit/--speed-time), never by --max-time. A complete
# OUTPUT is kept as is (re-runs skip finished ranges).
fetch_range() {
  local url="$1" start="$2" end="$3" output="$4" total="$5" etag="$6"
  local expected=$((end - start + 1))
  if [ -f "$output" ] && [ "$(stat -c %s "$output")" = "$expected" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$output")"
  local part="$output.part" seg="$output.seg" hdr="$output.hdr"
  local attempt have from content_range etag_seen got
  for attempt in $(seq 1 30); do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -gt "$expected" ]; then
      rm -f "$part"
      have=0
    fi
    [ "$have" -lt "$expected" ] || break
    from=$((start + have))
    rm -f "$seg" "$hdr"
    set +e
    curl --fail --silent --show-error --location \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --user-agent "$USER_AGENT" --range "$from-$end" \
      --dump-header "$hdr" --output "$seg" "$url" < /dev/null
    local status=$?
    set -e
    content_range="$(tr -d '\r' < "$hdr" 2>/dev/null | grep -i '^content-range:' | tail -n 1 | cut -d' ' -f2- || true)"
    etag_seen="$(tr -d '\r"' < "$hdr" 2>/dev/null | grep -i '^etag:' | tail -n 1 | cut -d' ' -f2- || true)"
    if [ -f "$seg" ] && [ "$content_range" = "bytes $from-$end/$total" ] && [ "$etag_seen" = "$etag" ]; then
      # A stalled or broken transfer still delivered a valid prefix of the
      # requested range; keep it and resume after it.
      cat "$seg" >> "$part"
    elif [ -n "$content_range" ] || [ -n "$etag_seen" ]; then
      if [ "$etag_seen" != "$etag" ] && [ -n "$etag_seen" ]; then
        rm -f "$seg" "$hdr"
        die "ETag '$etag_seen' != pinned '$etag' for $url (object changed upstream)"
      fi
      if [ "$status" = 0 ]; then
        rm -f "$seg" "$hdr"
        die "unexpected Content-Range '$content_range' for $url $from-$end (want bytes $from-$end/$total)"
      fi
    fi
    rm -f "$seg" "$hdr"
    got=0
    [ -f "$part" ] && got="$(stat -c %s "$part")"
    if [ "$got" -lt "$expected" ]; then
      echo "range_retry attempt=$attempt curl_status=$status have=$got of=$expected file=${output##*/}"
      sleep 5
    fi
  done
  got=0
  [ -f "$part" ] && got="$(stat -c %s "$part")"
  [ "$got" = "$expected" ] || die "range $start-$end of $url incomplete after retries ($got of $expected bytes)"
  mv "$part" "$output"
  echo "range_fetched start=$start end=$end bytes=$expected sha256=$(sha256sum "$output" | cut -d' ' -f1) file=${output##*/}"
}
