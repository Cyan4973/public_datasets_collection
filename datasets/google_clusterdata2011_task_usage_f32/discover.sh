#!/usr/bin/env bash
# Documents how the pinned resources were resolved. Metadata only: the GCS
# JSON object listing for task_usage/, the bucket's SHA256SUM/README/schema.csv,
# the license page, and 256 KiB head ranges of parts 0-6 (first start time of
# each part). Prints to stdout; writes only to a temporary directory it removes.
set -euo pipefail

BUCKET="clusterdata-2011-2"
BASE="https://storage.googleapis.com/$BUCKET"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/clusterdata2011_discover.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
get() { curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors --max-time 120 "$@"; }

get "https://storage.googleapis.com/storage/v1/b/$BUCKET/o?prefix=task_usage/&maxResults=1000&fields=items(name,size,md5Hash,generation),nextPageToken" -o "$TMP/listing.json"
get "$BASE/SHA256SUM" -o "$TMP/SHA256SUM"
get "$BASE/schema.csv" -o "$TMP/schema.csv"
get "https://raw.githubusercontent.com/google/cluster-data/master/ClusterData2011_2.md" -o "$TMP/ClusterData2011_2.md"
grep -n "CC-BY\|made available under" "$TMP/ClusterData2011_2.md"
grep '^task_usage' "$TMP/schema.csv" | grep -E ',(1|2|6|16|17),'
python3 - "$TMP/listing.json" "$TMP/SHA256SUM" <<'PY'
import json, sys
items = json.load(open(sys.argv[1]))["items"]
sums = {}
for line in open(sys.argv[2]):
    digest, name = line.split()
    sums[name.lstrip("*")] = digest
print(f"task_usage parts={len(items)} total_bytes={sum(int(i['size']) for i in items)}")
for item in items[:7]:
    print(f"{item['name']}\t{item['size']}\tmd5={item['md5Hash']}\tsha256={sums.get(item['name'])}")
PY
for n in 0 1 2 3 4 5 6; do
  url="$BASE/task_usage/part-0000$n-of-00500.csv.gz"
  get --range 0-262143 -o "$TMP/head$n.gz" "$url"
  python3 - "$TMP/head$n.gz" "$n" <<'PY'
import hashlib, sys, zlib
raw = open(sys.argv[1], "rb").read()
first = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw).split(b"\n", 1)[0].split(b",")
print(f"part {sys.argv[2]} head sha256={hashlib.sha256(raw).hexdigest()} first_start_us={first[0].decode()} window_s={int(first[0]) // 300000000 * 300}")
PY
done
