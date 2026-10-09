#!/usr/bin/env bash
# Documents how files.tsv was resolved (not part of download/build/verify).
# Fetches the 14 data_calibrated/sol_* Apache listings, keeps the full-sol
# ps_calib_<SOL>_<VV>.csv products listed at ~87M, fetches their PDS4 XML
# labels (file_size, records, md5_checksum, start/stop time) and writes
# labels.tsv into the given scratch directory.  scripts/select_files.py then
# applies the selection rule and writes files.tsv.
# Usage: bash discover.sh /tmp/autocollect/<id>/discover
set -euo pipefail
OUT="${1:?scratch dir}"
mkdir -p "$OUT/labels"
BASE="https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated"
UA="openzl-public-datasets-insight-apss/1.0"
DIRS="sol_0000_0122 sol_0123_0210 sol_0211_0300 sol_0301_0389 sol_0390_0477 sol_0478_0566 sol_0567_0668 sol_0669_0745 sol_0746_0832 sol_0833_0921 sol_0922_1010 sol_1011_1100 sol_1101_1188 sol_1189_1276"
: > "$OUT/candidates.txt"
for d in $DIRS; do
  curl -fsS --max-time 60 --retry 3 -A "$UA" "$BASE/$d/" -o "$OUT/list_$d.html"
  sed 's/<[^>]*>/ /g' "$OUT/list_$d.html" \
    | awk -v d="$d" '$1 ~ /^ps_calib_[0-9]{4}_[0-9]{2}\.csv$/ && $(NF-1)=="87M" {print d, $1}' >> "$OUT/candidates.txt"
done
echo "candidates: $(wc -l < "$OUT/candidates.txt")"
while read -r d f; do
  x="${f%.csv}.xml"
  [ -s "$OUT/labels/$x" ] || curl -fsS --max-time 60 --retry 3 -A "$UA" "$BASE/$d/$x" -o "$OUT/labels/$x"
done < "$OUT/candidates.txt"
python3 -I "$(dirname "$0")/scripts/select_files.py" labels "$OUT"
