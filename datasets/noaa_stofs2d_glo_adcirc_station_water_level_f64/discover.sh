#!/usr/bin/env bash
# Documents how sources.tsv was resolved (run once by the recipe author on
# 2026-10-06; download.sh does NOT run this).  For each pinned cycle date
# (00z, every 20 days from 2024-06-01, 40 cycles) it issues one anonymous S3
# ListObjectsV2 request whose prefix is the exact object key and prints
# "date<TAB>key<TAB>size<TAB>etag".  Usage:
#   bash discover.sh > /tmp/sources.tsv
set -euo pipefail

BASE_URL="https://noaa-gestofs-pds.s3.amazonaws.com"
START="2024-06-01"
STEP_DAYS=20
COUNT=40

printf 'date\tkey\tsize_bytes\tetag\n'
for k in $(seq 0 $((COUNT - 1))); do
  day="$(date -u -d "$START + $((k * STEP_DAYS)) days" +%Y%m%d)"
  key="stofs_2d_glo.${day}/00/rerun/stofs_2d_glo_fcst.61.nc"
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
