#!/usr/bin/env bash
# Documents how sources.tsv was resolved (run once by the recipe author on
# 2026-10-08; download.sh does NOT run this). For each pinned date (every
# 7 days from 2025-01-01, 52 dates, last 2025-12-24) it issues one anonymous
# S3 ListObjectsV2 request whose prefix is the exact key of that day's t03z
# fields.n003 nowcast file and prints "date<TAB>key<TAB>size<TAB>etag".
# Usage:
#   bash discover.sh > /tmp/sources.tsv
set -euo pipefail

BASE_URL="https://noaa-nos-ofs-pds.s3.amazonaws.com"
START="2025-01-01"
STEP_DAYS=7
COUNT=52

printf 'date\tkey\tsize_bytes\tetag\n'
for k in $(seq 0 $((COUNT - 1))); do
  day="$(date -u -d "$START + $((k * STEP_DAYS)) days" +%Y%m%d)"
  key="sfbofs/netcdf/${day:0:4}/${day:4:2}/${day:6:2}/sfbofs.t03z.${day}.fields.n003.nc"
  xml="$(curl --fail --silent --show-error --max-time 60 "$BASE_URL/?list-type=2&prefix=$key")"
  n="$(printf '%s' "$xml" | grep -o '<Contents>' | wc -l | tr -d ' ')"
  if [ "$n" != "1" ]; then
    echo "FATAL: $key: expected exactly one listed object, got $n" >&2
    exit 1
  fi
  size="$(printf '%s' "$xml" | sed -n 's/.*<Size>\([0-9]*\)<\/Size>.*/\1/p')"
  etag="$(printf '%s' "$xml" | sed -n 's/.*<ETag>\([^<]*\)<\/ETag>.*/\1/p' | sed 's/&quot;//g; s/"//g')"
  printf '%s\t%s\t%s\t%s\n' "${day:0:4}-${day:4:2}-${day:6:2}" "$key" "$size" "$etag"
done
