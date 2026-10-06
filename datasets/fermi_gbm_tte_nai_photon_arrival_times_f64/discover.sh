#!/usr/bin/env bash
# Documentation of how sources.tsv was resolved. Not part of the download/build
# contract: download.sh only reads the pinned sources.tsv.
#
# 1. List the anonymous nasa-heasarc S3 mirror with delimiter=/ : first the
#    year prefixes under fermi/data/gbm/bursts/, then every year's burst
#    directories (ListObjectsV2 pages at 1000 keys; keyset pagination via
#    continuation-token).
# 2. scripts/select_bursts.py picks N evenly spaced bursts over the
#    2008-2025 population, lists each candidate's current/ prefix, applies the
#    detector rule (largest highest-version NaI TTE file), and validates each
#    pick with a 40 KiB range-GET header probe.
#
# Usage: bash discover.sh [OUT_DIR]   (default /tmp/autocollect/<id>/discover)
set -euo pipefail

DATASET_ID="fermi_gbm_tte_nai_photon_arrival_times_f64"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-/tmp/autocollect/$DATASET_ID/discover}"
BASE="https://nasa-heasarc.s3.amazonaws.com"
ROOT_PREFIX="fermi/data/gbm/bursts/"
UA="openzl-public-datasets-fermi-gbm-tte/1.0"

mkdir -p "$OUT_DIR/pages"
rm -f "$OUT_DIR"/pages/*.xml

list_prefix() {  # list_prefix <prefix> <tag> : delimiter=/ listing, all pages
  local prefix="$1" tag="$2" next_page="" page=0 out
  while :; do
    page=$((page + 1))
    out="$OUT_DIR/pages/${tag}_$(printf '%03d' "$page").xml"
    if [[ -z "$next_page" ]]; then
      curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -o "$out" --get \
        --data-urlencode "list-type=2" --data-urlencode "prefix=$prefix" --data-urlencode "delimiter=/" \
        --data-urlencode "max-keys=1000" "$BASE/"
    else
      curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -o "$out" --get \
        --data-urlencode "list-type=2" --data-urlencode "prefix=$prefix" --data-urlencode "delimiter=/" \
        --data-urlencode "max-keys=1000" --data-urlencode "continuation-token=$next_page" "$BASE/"
    fi
    next_page="$(python3 - "$out" <<'PY'
import sys
import xml.etree.ElementTree as ET
ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
root = ET.parse(sys.argv[1]).getroot()
print(root.findtext("s3:NextContinuationToken", default="", namespaces=ns)
      if root.findtext("s3:IsTruncated", default="false", namespaces=ns) == "true" else "")
PY
)"
    [[ -n "$next_page" ]] || break
  done
}

list_prefix "$ROOT_PREFIX" "root"
years="$(python3 - "$OUT_DIR" <<'PY'
import re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
years = []
for page in sorted(Path(sys.argv[1], "pages").glob("root_*.xml")):
    for item in ET.parse(page).getroot().findall("s3:CommonPrefixes", ns):
        match = re.fullmatch(r"fermi/data/gbm/bursts/(\d{4})/", item.findtext("s3:Prefix", namespaces=ns))
        if match:
            years.append(match.group(1))
print(" ".join(sorted(years)))
PY
)"
echo "years: $years"
for year in $years; do
  list_prefix "${ROOT_PREFIX}${year}/" "year${year}"
done

python3 - "$OUT_DIR" <<'PY'
import collections, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
out = Path(sys.argv[1])
rows = set()
for page in sorted((out / "pages").glob("year*.xml")):
    for item in ET.parse(page).getroot().findall("s3:CommonPrefixes", ns):
        prefix = item.findtext("s3:Prefix", namespaces=ns)
        match = re.fullmatch(r"fermi/data/gbm/bursts/(\d{4})/(bn(\d{2})\d{7})/", prefix)
        if not match or match.group(1)[2:] != match.group(3):
            raise SystemExit(f"unexpected burst prefix {prefix}")
        rows.add((match.group(1), match.group(2)))
with (out / "burst_inventory.tsv").open("w", encoding="utf-8") as handle:
    handle.write("year\tburst\n")
    for year, burst in sorted(rows, key=lambda r: r[1]):
        handle.write(f"{year}\t{burst}\n")
counts = collections.Counter(year for year, _ in rows)
print(f"bursts={len(rows)} per_year={dict(sorted(counts.items()))}")
PY

python3 "$RECIPE_DIR/scripts/select_bursts.py" \
  --bursts "$OUT_DIR/burst_inventory.tsv" \
  --work-dir "$OUT_DIR" \
  --out "$OUT_DIR/sources.selected.tsv"
echo "selected inventory: $OUT_DIR/sources.selected.tsv (copy to $RECIPE_DIR/sources.tsv)"
