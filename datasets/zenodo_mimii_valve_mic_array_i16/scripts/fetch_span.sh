#!/usr/bin/env bash
# Fetch one pinned byte span (one ZIP member: local header + deflate data) of
# 6_dB_valve.zip from Zenodo record 3384388. Called by download.sh through
# xargs with
#   <first byte> <last byte> <path relative to the download dir>
# The response headers are kept next to the .part file so that
# `mimii.py check-members` can check the Content-Range (requested span and
# pinned archive size) before promoting the span.
#
# Zenodo rate-limits anonymous clients (X-RateLimit-Limit was 133 requests
# per minute on 2026-10-06, Retry-After 59 s). curl --retry treats 429 and
# 5xx as transient and honours Retry-After; each call also sleeps
# MIMII_REQUEST_DELAY seconds afterwards to stay well under the limit.
# Always exits 0; validation in mimii.py decides.
set -uo pipefail

first="$1"
last="$2"
rel="$3"
dir="${MIMII_DOWNLOAD_DIR:?MIMII_DOWNLOAD_DIR not set}"
ua="${MIMII_UA:-openzl-public-datasets-mimii/1.0}"
url="${MIMII_URL:?MIMII_URL not set}"
delay="${MIMII_REQUEST_DELAY:-1.2}"
out="$dir/$rel"
length=$((last - first + 1))

mkdir -p "$(dirname "$out")"
rm -f "$out.part" "$out.hdr"
if ! curl --fail --silent --show-error --location \
  --retry 10 --retry-delay 10 --retry-max-time 900 --retry-all-errors --connect-timeout 30 \
  --speed-limit 1024 --speed-time 60 --max-filesize $((length + 4096)) \
  --range "$first-$last" --user-agent "$ua" \
  --dump-header "$out.hdr" --output "$out.part" "$url"; then
  echo "fetch_failed range=$first-$last rel=$rel"
  rm -f "$out.part" "$out.hdr"
fi
sleep "$delay"
exit 0
