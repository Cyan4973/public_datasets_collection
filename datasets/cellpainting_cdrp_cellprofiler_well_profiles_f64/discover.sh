#!/usr/bin/env bash
# Documentation of how plates.tsv was resolved (not part of the acceptance path).
# Lists the cpg0012 backend/CDRP prefix with anonymous S3 ListObjectsV2 and selects the first
# 50 plate CSVs by numeric plate id among objects larger than 30,000,000 bytes (complete
# 384-well plates; 387 of the 405 CSVs are 33-35 MB). Writes the result next to the logs
# and diffs it against the pinned plates.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cellpainting_cdrp_cellprofiler_well_profiles_f64"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
mkdir -p "$OUT_DIR"
PREFIX="cpg0012-wawer-bioactivecompoundprofiling/broad/workspace/backend/CDRP/"

curl --fail --silent --show-error --max-time 120 \
  --output "$OUT_DIR/list.xml" \
  "https://cellpainting-gallery.s3.amazonaws.com/?list-type=2&prefix=$PREFIX"

python3 -I - "$OUT_DIR/list.xml" "$OUT_DIR/plates.discovered.tsv" <<'PY'
import re
import sys

xml = open(sys.argv[1], encoding="utf-8").read()
if "<IsTruncated>false</IsTruncated>" not in xml:
    raise SystemExit("listing truncated; add continuation-token paging")
rows = re.findall(
    r"<Key>([^<]*)</Key><LastModified>([^<]*)</LastModified><ETag>&quot;([^&]*)&quot;</ETag><Size>(\d+)</Size>",
    xml,
)
csvs = sorted(
    (int(k.split("/")[-2]), k, lm, e, int(s)) for k, lm, e, s in rows if k.endswith(".csv")
)
print(f"cdrp_plate_csvs={len(csvs)} total_bytes={sum(r[4] for r in csvs)}")
selected = [r for r in csvs if r[4] > 30_000_000][:50]
with open(sys.argv[2], "w", encoding="ascii") as fh:
    fh.write("plate_id\tsize_bytes\tetag\tlast_modified\tkey\n")
    for plate, key, lm, etag, size in selected:
        fh.write(f"{plate}\t{size}\t{etag}\t{lm}\t{key}\n")
print(f"selected={len(selected)} bytes={sum(r[4] for r in selected)}")
PY

diff "$RECIPE_DIR/plates.tsv" "$OUT_DIR/plates.discovered.tsv" && echo "plates.tsv matches live listing"
