#!/usr/bin/env bash
# Fetch one pinned byte span (one ZIP member: local header + LZMA data) of a
# figshare-hosted archive. Called by download.sh through xargs with
#   <figshare file id> <first byte> <last byte> <path relative to download dir>
# Every call goes through ndownloader.figshare.com, which answers with a
# fresh presigned S3 URL (valid for 10 s), so curl -L re-resolves per request.
# The response headers are kept next to the .part file so that
# `rousettus.py check-members` can check the Content-Range against the pinned
# archive size before promoting the span. Always exits 0; validation decides.
set -uo pipefail

file_id="$1"
first="$2"
last="$3"
rel="$4"
dir="${ROUSETTUS_DOWNLOAD_DIR:?ROUSETTUS_DOWNLOAD_DIR not set}"
ua="${ROUSETTUS_UA:-openzl-public-datasets-rousettus/1.0}"
out="$dir/$rel"
length=$((last - first + 1))

mkdir -p "$(dirname "$out")"
rm -f "$out.part" "$out.hdr"
if ! curl --fail --silent --show-error --location \
  --retry 8 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
  --speed-limit 1024 --speed-time 60 --max-filesize $((length + 4096)) \
  --range "$first-$last" --user-agent "$ua" \
  --dump-header "$out.hdr" --output "$out.part" \
  "https://ndownloader.figshare.com/files/$file_id"; then
  echo "fetch_failed file_id=$file_id range=$first-$last rel=$rel"
  rm -f "$out.part" "$out.hdr"
fi
exit 0
