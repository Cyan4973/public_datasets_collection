# Shared curl helpers for discover.sh and download.sh (sourced, not executed).
# All network I/O for this recipe goes through these functions.

ARNI_RECORD_ID=6985104
ARNI_API_URL="https://zenodo.org/api/records/$ARNI_RECORD_ID"
ARNI_FILES_URL="https://zenodo.org/records/$ARNI_RECORD_ID/files"
ARNI_UA="openzl-public-datasets-arni-rir/1.0"
# Zenodo advertises ~133 requests/minute for anonymous clients; stay near 1/s.
ARNI_REQUEST_INTERVAL="${ARNI_REQUEST_INTERVAL:-1}"
ARNI_TAIL_BYTES=65536

arni_archive_url() {
  printf '%s/%s?download=1' "$ARNI_FILES_URL" "$1"
}

# arni_curl_get URL OUT MAX_BYTES : small whole-object GET (metadata, CSV).
arni_curl_get() {
  local url="$1" out="$2" max_bytes="$3"
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 8 --retry-all-errors --retry-max-time 1800 \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --max-filesize "$max_bytes" --user-agent "$ARNI_UA" \
    --output "$out.part" "$url"
  mv "$out.part" "$out"
  sleep "$ARNI_REQUEST_INTERVAL"
}

# arni_curl_range URL START END OUT HEADERS : exact inclusive byte range.
# curl retries 408/429/5xx (honouring Retry-After) with exponential backoff;
# the caller validates the 206 status and the Content-Range total.
arni_curl_range() {
  local url="$1" start="$2" end="$3" out="$4" headers="$5"
  rm -f "$out.part" "$headers.part"
  curl --fail --silent --show-error --location \
    --retry 8 --retry-all-errors --retry-max-time 1800 \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --max-filesize "$((end - start + 1 + 1024))" --user-agent "$ARNI_UA" \
    --range "$start-$end" --dump-header "$headers.part" --output "$out.part" "$url"
  mv "$headers.part" "$headers"
  mv "$out.part" "$out"
  sleep "$ARNI_REQUEST_INTERVAL"
}

# arni_fetch_directory TOOL META_DIR ARCHIVE SIZE : tail + exact central directory.
arni_fetch_directory() {
  local tool="$1" meta_dir="$2" archive="$3" size="$4"
  local url tail_start cd_range cd_start cd_end
  url="$(arni_archive_url "$archive")"
  tail_start=$((size - ARNI_TAIL_BYTES))
  if [ ! -s "$meta_dir/$archive.tail.bin" ] || [ ! -s "$meta_dir/$archive.tail.headers" ]; then
    arni_curl_range "$url" "$tail_start" "$((size - 1))" "$meta_dir/$archive.tail.bin" "$meta_dir/$archive.tail.headers"
  fi
  cd_range="$(python3 "$tool" locate --tail "$meta_dir/$archive.tail.bin" \
    --headers "$meta_dir/$archive.tail.headers" --size "$size")"
  cd_start="${cd_range%%$'\t'*}"
  cd_end="${cd_range##*$'\t'}"
  if [ -s "$meta_dir/$archive.cd.bin" ] && [ -s "$meta_dir/$archive.cd.headers" ] \
    && python3 "$tool" check-range --headers "$meta_dir/$archive.cd.headers" \
      --file "$meta_dir/$archive.cd.bin" --start "$cd_start" --end "$cd_end" --total "$size" >/dev/null 2>&1; then
    echo "cache_hit central_directory archive=$archive"
  else
    arni_curl_range "$url" "$cd_start" "$cd_end" "$meta_dir/$archive.cd.bin" "$meta_dir/$archive.cd.headers"
  fi
  python3 "$tool" check-range --headers "$meta_dir/$archive.cd.headers" \
    --file "$meta_dir/$archive.cd.bin" --start "$cd_start" --end "$cd_end" --total "$size"
}
