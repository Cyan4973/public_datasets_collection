#!/usr/bin/env bash
# Metadata-only discovery (not part of the acceptance path): re-list the SEVIR VIL prefix
# and compare the six STORMEVENTS objects with the pins in containers.tsv. This documents
# how containers.tsv was resolved: sizes/ETags/Last-Modified come from the S3 listing,
# event_count/tail_offset from parsing the 2048-byte metadata head (scripts/sevir_hdf5.py).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="sevir_vil_storm_events_u8"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$OUT" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1

curl --fail --silent --show-error --max-time 60 \
  --output "$OUT/list_vil.xml" "https://sevir.s3.amazonaws.com/?list-type=2&prefix=data/vil/"

python3 - "$OUT/list_vil.xml" "$RECIPE_DIR/containers.tsv" <<'PY'
import re
import sys

listing = open(sys.argv[1]).read()
if "<IsTruncated>false</IsTruncated>" not in listing:
    raise SystemExit("listing truncated")
objects = {
    m.group(1): (m.group(2), m.group(3).replace("&quot;", ""), int(m.group(4)))
    for m in re.finditer(r"<Key>(.*?)</Key><LastModified>(.*?)</LastModified><ETag>(.*?)</ETag><Size>(\d+)</Size>", listing)
}
storm = sorted(k for k in objects if "STORMEVENTS" in k)
print(f"vil_objects={len(objects)} stormevents_objects={len(storm)}")
lines = open(sys.argv[2]).read().splitlines()
header = lines[0].split("\t")
ok = True
for line in lines[1:]:
    row = dict(zip(header, line.split("\t")))
    last_modified, etag, size = objects.get(row["object_key"], ("", "", -1))
    same = (etag, size) == (row["etag"], int(row["size_bytes"]))
    ok &= same
    print(f"{'same' if same else 'CHANGED'} {row['object_key']} size={size} etag={etag} last_modified={last_modified}")
if not ok or len(storm) != len(lines) - 1:
    raise SystemExit("containers.tsv pins no longer match the bucket listing")
PY
