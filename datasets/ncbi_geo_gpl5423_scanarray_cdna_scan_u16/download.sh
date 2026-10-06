#!/usr/bin/env bash
# Download the 24 pinned GSE23678 ScanArray Express scan TIFFs (first 12 GSMs
# in accession order, Cy3 + Cy5 each) listed in sources.tsv, plus two small
# provenance files (NCBI FTP README.ftp and the series filelist.txt).
#
# Each .tif.gz is fetched with resumable curl into a .part file, then checked
# for exact size, gzip trailer CRC32/ISIZE, sha256 (once pinned), a complete
# gunzip, and the pinned ScanArray TIFF layout (scripts/scanarray.py
# check-file) before it is renamed into place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ncbi_geo_gpl5423_scanarray_cdna_scan_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TIFF_DIR="$DOWNLOAD_DIR/tiff"
META_DIR="$DOWNLOAD_DIR/meta"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECKER="$RECIPE_DIR/scripts/scanarray.py"
README_URL="https://ftp.ncbi.nlm.nih.gov/README.ftp"
FILELIST_URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE23nnn/GSE23678/suppl/filelist.txt"
README_SENTENCE="ALL DATA HERE IS PUBLIC, NON-SENSITIVE, UNRESTRICTED SCIENTIFIC DATA SHARING AMONG SCIENTIFIC COMMUNITIES"
UA="openzl-public-datasets-geo-scanarray-download/1.0"
EXPECTED_FILES=24
EXPECTED_BYTES=584061895

mkdir -p "$TIFF_DIR" "$META_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$CHECKER" selftest

# Liveness: one-byte range GET on the first pinned object.
first_url="$(awk -F'\t' 'NR==2{print $11}' "$SOURCES")"
code="$(curl --globoff --silent --show-error --location --range 0-0 --max-time 60 \
  --retry 5 --retry-delay 5 --user-agent "$UA" --output /dev/null --write-out '%{http_code}' "$first_url")"
[[ "$code" = "206" || "$code" = "200" ]] || { echo "liveness check failed http=$code url=$first_url" >&2; exit 1; }
echo "liveness ok http=$code"

# Rights evidence: the NCBI FTP README must still carry the public-data notice.
curl --globoff --fail --silent --show-error --location --max-time 120 --retry 5 --retry-delay 5 \
  --user-agent "$UA" --output "$META_DIR/README.ftp.part" "$README_URL"
grep -qF "$README_SENTENCE" "$META_DIR/README.ftp.part" \
  || { echo "NCBI README.ftp no longer carries the public-data notice; stop and re-check rights" >&2; exit 1; }
mv "$META_DIR/README.ftp.part" "$META_DIR/README.ftp"
echo "rights notice ok: $README_URL"

# Upstream drift check: every pinned file must still be listed with its size.
curl --globoff --fail --silent --show-error --location --max-time 120 --retry 5 --retry-delay 5 \
  --user-agent "$UA" --output "$META_DIR/GSE23678_filelist.txt.part" "$FILELIST_URL"
while IFS=$'\t' read -r gsm hyb dye filename size rest; do
  [[ "$gsm" != "gsm" ]] || continue
  awk -F'\t' -v f="$filename" -v s="$size" '$1=="File" && $2==f && $4==s {found=1} END{exit !found}' \
    "$META_DIR/GSE23678_filelist.txt.part" \
    || { echo "filelist.txt no longer lists $filename with size $size" >&2; exit 1; }
done < "$SOURCES"
mv "$META_DIR/GSE23678_filelist.txt.part" "$META_DIR/GSE23678_filelist.txt"
echo "filelist ok: all pinned files listed with pinned sizes"

validate() {  # path -> 0 if the local file matches its pinned sources.tsv row
  [[ -f "$1" ]] || return 1
  python3 "$CHECKER" check-file --sources "$SOURCES" --file "$1"
}

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'gsm\tdye\tfilename\tsize_bytes\tsha256\turl\n' > "$plan.tmp"
count=0
bytes=0
fetched=0
while IFS=$'\t' read -r -u 3 gsm hyb dye filename size crc tiff_bytes height stamp sha url; do
  [[ "$gsm" != "gsm" ]] || continue
  target="$TIFF_DIR/$filename"
  if validate "$target" >/dev/null 2>&1; then
    :
  else
    rm -f "$target"
    part="$target.part"
    ok=0
    for attempt in 1 2 3 4 5; do
      if [[ -f "$part" ]] && (( $(stat -c %s "$part") > size )); then rm -f "$part"; fi
      if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
        curl --globoff --fail --silent --show-error --location -C - \
          --retry 10 --retry-delay 5 --retry-all-errors \
          --speed-limit 1024 --speed-time 120 --max-filesize 40000000 \
          --user-agent "$UA" --output "$part" "$url" \
          || { echo "curl failed file=$filename attempt=$attempt" >&2; sleep 5; continue; }
      fi
      if validate "$part"; then
        mv "$part" "$target"
        ok=1
        break
      fi
      echo "invalid payload file=$filename attempt=$attempt; discarding partial file" >&2
      rm -f "$part"
    done
    (( ok == 1 )) || { echo "giving up on file=$filename" >&2; exit 1; }
    fetched=$((fetched + 1))
  fi
  digest="$(sha256sum "$target" | awk '{print $1}')"
  if [[ "$sha" != "-" && "$digest" != "$sha" ]]; then  # "-" = not pinned yet
    echo "sha256 mismatch file=$filename got=$digest want=$sha" >&2; exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$gsm" "$dye" "$filename" "$size" "$digest" "$url" >> "$plan.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
  echo "ok files=$count bytes=$bytes fetched_this_run=$fetched file=$filename"
done 3< "$SOURCES"

[[ "$count" = "$EXPECTED_FILES" ]] || { echo "unexpected file count $count (want $EXPECTED_FILES)" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $bytes (want $EXPECTED_BYTES)" >&2; exit 1; }
stray="$(find "$TIFF_DIR" -type f ! -name '*.tif.gz' | wc -l)"
[[ "$stray" = "0" ]] || { echo "unexpected extra files in $TIFF_DIR" >&2; exit 1; }
mv "$plan.tmp" "$plan"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_this_run=$fetched"
