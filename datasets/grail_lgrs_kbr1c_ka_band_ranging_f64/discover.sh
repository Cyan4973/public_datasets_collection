#!/usr/bin/env bash
# Documents how sources.tsv was resolved. Metadata only: it fetches the volume
# MD5 manifest (2.9 MB) and the first 4 KB of each selected KBR1C .asc (range
# GET), never a whole data file.
#
# Scope rule: every KBR1C_YYYY_MM_DD_X_04.ASC listed in grail_0101_230316.md5
# whose date falls in the GRAIL extended mission (2012-08-30 .. 2012-12-14),
# i.e. the 2-second-cadence products. The primary-mission products
# (2012-03-01 .. 2012-05-29) are 5-second cadence and are not selected.
#
# Usage: bash discover.sh OUT_SOURCES_TSV [SCRATCH_DIR]
set -euo pipefail
OUT="${1:?usage: discover.sh OUT_SOURCES_TSV [SCRATCH_DIR]}"
SCRATCH="${2:-$(mktemp -d)}"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1"
BASE="$ROOT/grail_0101/level_1b"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 120)
mkdir -p "$SCRATCH"

"${CURL[@]}" -o "$SCRATCH/grail_0101_230316.md5" "$ROOT/grail_0101_230316.md5"
grep -iE 'level_1b\\2012_(08|09|10|11|12)_[0-9]{2}\\kbr1c_.*\.asc' "$SCRATCH/grail_0101_230316.md5" \
  | tr -d '\r' | awk '{print $1, $2}' > "$SCRATCH/kbr1c_ext.txt"
wc -l < "$SCRATCH/kbr1c_ext.txt"

printf 'date\tfile\tasc_md5\thttp_bytes\theader_filesize\theader_records\tdata_records\tfirst_tdb\tlast_tdb\tlabel_md5\n' > "$OUT.part"
while read -r md5 path; do
  name="$(basename "${path//\\//}")"
  date="$(echo "$name" | sed -E 's/^kbr1c_([0-9_]{10})_x_04\.asc$/\1/')"
  lblmd5="$(grep -i "\\\\${name%.asc}.lbl" "$SCRATCH/grail_0101_230316.md5" | tr -d '\r' | awk '{print tolower($1)}')"
  "${CURL[@]}" -r 0-4095 -D "$SCRATCH/h" -o "$SCRATCH/head.asc" "$BASE/$date/$name" < /dev/null
  total="$(grep -i '^content-range:' "$SCRATCH/h" | tail -1 | sed -E 's#.*/([0-9]+).*#\1#' | tr -d '\r')"
  python3 -I - "$SCRATCH/head.asc" "$date" "$name" "$(echo "$md5" | tr A-F a-f)" "$total" "$lblmd5" >> "$OUT.part" <<'PY'
import re, sys
path, date, name, md5, total, lblmd5 = sys.argv[1:]
text = open(path, "rb").read().decode("ascii")
lines = text.split("\n")
hdr = {}
nhead = None
for i, ln in enumerate(lines):
    if ln.startswith("END OF HEADER"):
        nhead = i  # header record count excludes the END OF HEADER line
        break
    k, _, v = ln.partition(":")
    hdr.setdefault(k.strip(), v.strip())
assert nhead is not None, name
assert int(hdr["NUMBER OF HEADER RECORDS"]) == nhead, (name, nhead, hdr["NUMBER OF HEADER RECORDS"])
first = hdr["TIME FIRST OBS(SEC PAST EPOCH)"].split()[0]
last = hdr["TIME LAST OBS(SEC PAST EPOCH)"].split()[0]
print("\t".join([date, name, md5, total, hdr["FILESIZE (BYTES)"], str(nhead),
                 hdr["NUMBER OF DATA RECORDS"], str(int(float(first))), str(int(float(last))), lblmd5]))
PY
done < "$SCRATCH/kbr1c_ext.txt"
mv "$OUT.part" "$OUT"
awk -F'\t' 'NR>1 {n++; b+=$4; r+=$7; if ($4 != $5) bad++} END {print n " files, " b " bytes, " r " records, size mismatches " bad+0}' "$OUT"
