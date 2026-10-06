#!/usr/bin/env bash
# Metadata-only discovery: documents how sources.tsv was resolved.
#
# 1. Read the GSE23678 supplementary filelist.txt and keep the first 12 GSM
#    accessions in sort order; each contributes its Cy3 and its Cy5 scan
#    (24 .tif.gz files).
# 2. Map every GSM to its hybridization number from the GEO E-utilities
#    esummary title ("..._hybN").
# 3. For every file: HEAD (size must equal filelist.txt), a range GET of the
#    last 8 bytes (gzip trailer: CRC32 and ISIZE of the uncompressed TIFF), and
#    a range GET of the first 128 KiB, partially gunzipped to read the TIFF
#    header (ImageLength, DateTime, FluorName) with scripts/scanarray.py.
#
# No full payload is fetched. Output goes to sources.tsv.new for review; the
# committed sources.tsv is what download.sh enforces. The sha256 column is
# filled in from download_plan.tsv after the first full download.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GSE="GSE23678"
GSE_UID="200023678"
SERIES_URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE23nnn/$GSE"
SAMPLE_BASE="https://ftp.ncbi.nlm.nih.gov/geo/samples"
ESUMMARY="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gds&id=$GSE_UID&retmode=json"
GSM_COUNT=12
UA="openzl-public-datasets-geo-scanarray-discover/1.0"
OUT="$RECIPE_DIR/sources.tsv.new"
WORK="$(mktemp -d /tmp/autocollect.gpl5423.discover.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

fetch() {  # url out [range]
  local range_args=()
  [[ $# -ge 3 ]] && range_args=(--range "$3")
  curl --globoff --fail --silent --show-error --location --max-time 120 --retry 5 --retry-delay 3 \
    --user-agent "$UA" "${range_args[@]}" --output "$2" "$1"
}

fetch "$SERIES_URL/suppl/filelist.txt" "$WORK/filelist.txt"
fetch "$ESUMMARY" "$WORK/esummary.json"

python3 - "$WORK/filelist.txt" "$WORK/esummary.json" "$GSM_COUNT" > "$WORK/selection.tsv" <<'EOF'
import json, re, sys
filelist, esummary, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
files = []
for line in open(filelist, encoding="utf-8"):
    parts = line.rstrip("\n").split("\t")
    if len(parts) >= 4 and parts[0] == "File" and parts[1].endswith(".tif.gz"):
        files.append((parts[1], int(parts[3])))
gsms = sorted({name.split("_", 1)[0] for name, _ in files})[:count]
result = json.load(open(esummary, encoding="utf-8"))["result"]
hyb = {}
for sample in next(v for k, v in result.items() if k != "uids")["samples"]:
    match = re.search(r"_hyb(\d+)$", sample["title"])
    if match:
        hyb[sample["accession"]] = int(match.group(1))
for name, size in sorted(files):
    gsm = name.split("_", 1)[0]
    if gsm in gsms:
        dye = re.search(r"_(Cy[35])_", name).group(1)
        print(f"{gsm}\t{hyb[gsm]}\t{dye}\t{name}\t{size}")
EOF

printf 'gsm\thyb\tdye\tfilename\tsize_bytes\tgzip_crc32\ttiff_bytes\theight\tscan_datetime\tsha256\turl\n' > "$OUT"
while IFS=$'\t' read -r gsm hyb dye name size; do
  url="$SAMPLE_BASE/${gsm:0:6}nnn/$gsm/suppl/$name"
  head_size="$(curl --globoff --silent --show-error --head --location --max-time 60 --retry 5 \
    --user-agent "$UA" "$url" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-length"{v=$2} END{print v}')"
  [[ "$head_size" = "$size" ]] || { echo "size mismatch $name filelist=$size head=$head_size" >&2; exit 1; }
  fetch "$url" "$WORK/tail.bin" "$((size - 8))-$((size - 1))"
  read -r crc isize < <(python3 -c 'import struct,sys; c,i=struct.unpack("<II",open(sys.argv[1],"rb").read()); print(f"{c:08x} {i}")' "$WORK/tail.bin")
  fetch "$url" "$WORK/head.gz" "0-131071"
  IFS=$'\t' read -r height stamp fluor pmt laser pixel_offset < <(python3 "$RECIPE_DIR/scripts/scanarray.py" probe-header "$WORK/head.gz")
  [[ "$isize" = "$((pixel_offset + height * 4400))" ]] || { echo "ISIZE $isize != header-derived size for $name" >&2; exit 1; }
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t-\t%s\n' "$gsm" "$hyb" "$dye" "$name" "$size" "$crc" "$isize" "$height" "$stamp" "$url" >> "$OUT"
  echo "resolved $name height=$height fluor='$fluor' pmt=$pmt laser=$laser" >&2
done < "$WORK/selection.tsv"
echo "wrote $OUT rows=$(($(wc -l < "$OUT") - 1))" >&2
