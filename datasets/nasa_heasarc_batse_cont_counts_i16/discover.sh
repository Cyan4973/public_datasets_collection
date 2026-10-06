#!/usr/bin/env bash
# Documentation of how sources.tsv was resolved. Not part of the download/build
# contract: download.sh only reads the pinned sources.tsv.
#
# 1. Page the anonymous nasa-heasarc S3 ListObjectsV2 listing under
#    compton/data/batse/daily/ (keyset pagination via continuation-token) and
#    keep every cont_<TJD>.fits.gz key with its size and ETag.
# 2. scripts/select_days.py picks evenly spaced TJD targets over the mission,
#    snaps each to the nearest day that clears the size floor, and probes the
#    first 64 KiB of each chosen file (one HTTP range GET) to read the
#    BATSE_CNTS header and enforce the row floor.
#
# Usage: bash discover.sh [OUT_DIR]   (default /tmp/autocollect/<id>/discover)
set -euo pipefail

DATASET_ID="nasa_heasarc_batse_cont_counts_i16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-/tmp/autocollect/$DATASET_ID/discover}"
BASE="https://nasa-heasarc.s3.amazonaws.com"
PREFIX="compton/data/batse/daily/"
UA="openzl-public-datasets-batse-cont/1.0"

mkdir -p "$OUT_DIR/pages" "$OUT_DIR/heads"
rm -f "$OUT_DIR"/pages/page_*.xml

next_page=""
page=0
while :; do
  page=$((page + 1))
  out="$OUT_DIR/pages/page_$(printf '%04d' "$page").xml"
  if [[ -z "$next_page" ]]; then
    curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -o "$out" \
      --get --data-urlencode "list-type=2" --data-urlencode "prefix=$PREFIX" \
      --data-urlencode "max-keys=1000" "$BASE/"
  else
    curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -o "$out" \
      --get --data-urlencode "list-type=2" --data-urlencode "prefix=$PREFIX" \
      --data-urlencode "max-keys=1000" --data-urlencode "continuation-token=$next_page" "$BASE/"
  fi
  next_page="$(python3 - "$out" <<'PY'
import sys
import xml.etree.ElementTree as ET
ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
root = ET.parse(sys.argv[1]).getroot()
truncated = root.findtext("s3:IsTruncated", default="false", namespaces=ns) == "true"
print(root.findtext("s3:NextContinuationToken", default="", namespaces=ns) if truncated else "")
PY
)"
  [[ -n "$next_page" ]] || break
done
echo "listing pages=$page"

python3 - "$OUT_DIR" <<'PY'
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
out = Path(sys.argv[1])
rows = []
total_keys = 0
for page in sorted((out / "pages").glob("page_*.xml")):
    root = ET.parse(page).getroot()
    for item in root.findall("s3:Contents", ns):
        total_keys += 1
        key = item.findtext("s3:Key", namespaces=ns)
        match = re.fullmatch(r"compton/data/batse/daily/\d{5}_\d{5}/\d{5}_\d{5}/dds(\d{5})/cont_(\d{5})\.fits\.gz", key)
        if not match:
            continue
        etag = item.findtext("s3:ETag", namespaces=ns).strip('"')
        rows.append((int(match.group(2)), int(match.group(1)), key, int(item.findtext("s3:Size", namespaces=ns)), etag))
gz_files = len(rows)
# A few days are stored twice under neighbouring range directories (e.g.
# cont_10500 under both 10401_10500/ and 10501_10600/). Copies must be
# byte-identical (same size and ETag/MD5); keep the key whose range directory
# contains the TJD, else the lexicographically first key.
by_tjd: dict[int, list[tuple]] = {}
for row in rows:
    if row[0] != row[1]:
        raise SystemExit(f"cont TJD differs from dds directory: {row[2]}")
    by_tjd.setdefault(row[0], []).append(row)
unique = []
duplicates = []
for tjd, copies in sorted(by_tjd.items()):
    if len({(c[3], c[4]) for c in copies}) != 1:
        raise SystemExit(f"conflicting copies for TJD {tjd}: {copies}")
    def in_range(copy: tuple) -> bool:
        low, high = map(int, copy[2].split("/")[5].split("_"))
        return low <= tjd <= high
    copies.sort(key=lambda c: (not in_range(c), c[2]))
    unique.append(copies[0])
    if len(copies) > 1:
        duplicates.append(tjd)
rows = unique
with (out / "cont_inventory.tsv").open("w", encoding="utf-8") as handle:
    handle.write("tjd\tdds_tjd\tkey\tbytes\tetag\n")
    for row in rows:
        handle.write("\t".join(map(str, row)) + "\n")
print(
    f"keys={total_keys} cont_gz_keys={gz_files} unique_days={len(rows)} identical_duplicates={duplicates} "
    f"tjd={rows[0][0]}..{rows[-1][0]} bytes={sum(r[3] for r in rows)}"
)
PY

python3 "$RECIPE_DIR/scripts/select_days.py" \
  --inventory "$OUT_DIR/cont_inventory.tsv" \
  --heads-dir "$OUT_DIR/heads" \
  --out "$OUT_DIR/sources.selected.tsv"
echo "selected inventory: $OUT_DIR/sources.selected.tsv (copy to $RECIPE_DIR/sources.tsv)"
