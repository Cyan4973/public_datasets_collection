#!/usr/bin/env bash
# Documents how sources.tsv was resolved. Not part of the download/build path.
#
# 1. Crawl every month directory listing under ahead/mag/RTN/ (2006-2026).
# 2. Keep normal-mode STA_L1_MAG_RTN_YYYYMMDD_V06.cdf files dated
#    2007-01-01..2023-12-31 whose listing size is 18M or 19M (complete 8 Hz
#    days; partial/4 Hz conjunction days are smaller). Dedupe hrefs that appear
#    twice in a listing and days listed under two month directories (keep the
#    directory matching the file date).
# 3. Take 50 days at even rank spacing over the eligible sorted dates.
# 4. HEAD each selected file for exact Content-Length and Last-Modified.
#
# Usage: DATA_DIR=/tmp/somewhere bash discover.sh [output_sources_tsv]
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="stereo_a_impact_mag_rtn_bfield_f32"
BASE="https://stereo-ssc.nascom.nasa.gov/data/ins_data/impact/level1/ahead/mag/RTN"
OUT_DIR="$DATA_DIR/discovery/$DATASET_ID"
OUT_TSV="${1:-$OUT_DIR/sources.tsv}"
UA="openzl-public-datasets-stereo-mag-discover/1.0"
mkdir -p "$OUT_DIR"

listing="$OUT_DIR/listing.tsv"
: > "$listing"
for y in $(seq 2006 2026); do
  for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
    curl -fsS --max-time 60 --retry 3 -A "$UA" "$BASE/$y/$m/" 2>/dev/null \
      | grep -o 'href="STA_[^"]*\.cdf">[^<]*</a> *[0-9-]* [0-9:]* *[0-9.]*[KMG]\?' \
      | sed -E 's/href="([^"]*)">[^<]*<\/a> *([0-9-]+ [0-9:]+) *([0-9.KMG]+)/\1\t\2\t\3/' \
      | sort -u | sed "s|^|$y/$m\t|" >> "$listing" || true
  done
done
echo "listing rows: $(wc -l < "$listing")"

python3 -I - "$listing" "$OUT_DIR/selected.tsv" <<'PY'
import sys, re
rows = {}
for line in open(sys.argv[1]):
    ym, name, mtime, size = line.rstrip("\n").split("\t")
    m = re.fullmatch(r"STA_L1_MAG_RTN_(\d{8})_V06\.cdf", name)
    if not m:
        continue
    d = m.group(1)
    if not ("20070101" <= d <= "20231231") or size not in ("18M", "19M"):
        continue
    if ym.replace("/", "") != d[:6]:
        continue  # duplicate entry in a neighbouring month directory
    rows[d] = (ym, name)
dates = sorted(rows)
n = 50
pick = [dates[round(i * (len(dates) - 1) / (n - 1))] for i in range(n)]
assert len(set(pick)) == n
with open(sys.argv[2], "w") as f:
    for d in pick:
        f.write("%s\t%s\n" % rows[d])
print("eligible days:", len(dates), "selected:", n, pick[0], pick[-1])
PY

{
  printf 'date\tfilename\tsize_bytes\tlast_modified\tsha256\turl\n'
  while IFS=$'\t' read -r ym name; do
    url="$BASE/$ym/$name"
    hdr="$(curl -fsSI --max-time 60 --retry 3 -A "$UA" "$url" | tr -d '\r')"
    size="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="content-length"{print $2}' | tail -1)"
    lm="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="last-modified"{print $2}' | tail -1)"
    d="${name:15:8}"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$d" "$name" "$size" "$lm" "" "$url"
  done < "$OUT_DIR/selected.tsv"
} > "$OUT_TSV"
echo "wrote $OUT_TSV ($(($(wc -l < "$OUT_TSV") - 1)) files)"
awk -F'\t' 'NR>1{s+=$3} END{print "total bytes:", s}' "$OUT_TSV"
