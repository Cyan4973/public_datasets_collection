#!/usr/bin/env bash
# Fetch the 256 pinned IUE SWP low-dispersion NEWSIPS raw-image FITS files
# (swpNNNNN.rilo.gz) listed in sources.tsv, plus the MAST data-use policy page.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mast_iue_swp_raw_image_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RILO_DIR="$DOWNLOAD_DIR/rilo"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
EXPECTED_FILES=256
EXPECTED_BYTES=85299872
EVIDENCE_URL="https://archive.stsci.edu/publishing/data-use"
UA="openzl-public-datasets-iue-swp-raw/1.0"

mkdir -p "$RILO_DIR" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Rights evidence: MAST data-use policy (public-domain default; IUE not among copyrighted collections).
evidence="$DOWNLOAD_DIR/evidence/mast_data_use.html"
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 --user-agent "$UA" \
  --output "$evidence.part" "$EVIDENCE_URL"
mv "$evidence.part" "$evidence"
python3 "$CHECK" evidence "$evidence"

# Liveness: one-byte range GET on the first pinned file.
first_url="$(awk -F'\t' 'NR==2 {print $3}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'image_no\tfilename\tsize_bytes\tgzip_crc32\tsha256\n' > "$plan.part"
count=0
bytes=0
fetched=0
# Project the first seven columns with a non-whitespace separator so an empty
# sha256 column is preserved (tab is IFS whitespace and would collapse).
while IFS='|' read -r image_no filename url size_bytes crc32 isize pinned_sha; do
  target="$RILO_DIR/$filename"
  if [[ -s "$target" ]]; then
    if [[ "$(stat -c %s "$target")" != "$size_bytes" ]] \
      || ! sha="$(python3 "$CHECK" rilo "$target" "$image_no" "$crc32" "$isize")"; then
      echo "stale_or_invalid_cache file=$filename; refetching"
      rm -f "$target"
    fi
  fi
  if [[ ! -s "$target" ]]; then
    if [[ -s "$target.part" ]] && (( $(stat -c %s "$target.part") > size_bytes )); then
      rm -f "$target.part"
    fi
    curl --fail --silent --show-error --location -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 5000000 \
      --user-agent "$UA" --output "$target.part" "$url"
    actual="$(stat -c %s "$target.part")"
    if [[ "$actual" != "$size_bytes" ]]; then
      echo "FATAL size mismatch file=$filename expected=$size_bytes actual=$actual" >&2
      rm -f "$target.part"
      exit 1
    fi
    if ! sha="$(python3 "$CHECK" rilo "$target.part" "$image_no" "$crc32" "$isize")"; then
      echo "FATAL semantic validation failed file=$filename" >&2
      rm -f "$target.part"
      exit 1
    fi
    mv "$target.part" "$target"
    fetched=$((fetched + 1))
    echo "fetched image=$image_no bytes=$size_bytes sha256=$sha"
  fi
  if [[ -n "$pinned_sha" && "$sha" != "$pinned_sha" ]]; then
    echo "FATAL SHA-256 mismatch file=$filename expected=$pinned_sha actual=$sha" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$image_no" "$filename" "$size_bytes" "$crc32" "$sha" >> "$plan.part"
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $2 "|" $3 "|" $4 "|" $5 "|" $6 "|" $7}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FILES" || "$bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL unexpected selection totals files=$count bytes=$bytes (expected $EXPECTED_FILES / $EXPECTED_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_now=$fetched"
