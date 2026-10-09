#!/usr/bin/env bash
# Fetch the 1,604 pinned ISIS-2 SFS average-ionogram CDFs (ULA Fairbanks,
# 1974) from the anonymous NASA HDRL S3 mirror of SPDF/CDAWeb. Every object is
# checked against its pinned size and S3 ETag (single-part MD5) and CDF magic,
# then the whole set is parsed to reject semantically invalid payloads.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="spdf_isis2_topside_ionogram_amplitude_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
SOURCE_DIR="$DOWNLOAD_DIR/cdf"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
BUCKET="https://gov-nasa-hdrl-data1.s3.amazonaws.com"
UA="openzl-public-datasets-isis2-ionogram-download/1.0"
EXPECTED_COUNT=1604
EXPECTED_BYTES=304729594

mkdir -p "$SOURCE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Liveness: one-byte range GET on the first pinned object.
first_key="$(awk -F'\t' 'NR==2{print $1}' "$RECIPE_DIR/sources.tsv")"
curl --globoff -fsSL --max-time 60 --retry 3 -r 0-0 -o /dev/null "$BUCKET/$first_key"

count=0
bytes=0
fetched=0
while IFS=$'\t' read -r key filename size_bytes md5 last_modified; do
  [[ "$key" != "key" ]] || continue
  target="$SOURCE_DIR/$filename"
  if [[ -s "$target" && "$(stat -c %s "$target")" = "$size_bytes" ]] \
     && printf '%s  %s\n' "$md5" "$target" | md5sum --check --status; then
    :
  else
    rm -f "$target"
    curl --globoff --fail --silent --show-error --location \
      --retry 8 --retry-delay 3 --retry-all-errors \
      --connect-timeout 30 --max-time 600 --speed-limit 1024 --speed-time 120 \
      --max-filesize 2000000 --user-agent "$UA" \
      --output "$target.part" "$BUCKET/$key"
    mv "$target.part" "$target"
    fetched=$((fetched + 1))
    actual="$(stat -c %s "$target")"
    if [[ "$actual" != "$size_bytes" ]]; then
      echo "size mismatch $filename expected=$size_bytes actual=$actual" >&2
      rm -f "$target"; exit 1
    fi
    if ! printf '%s  %s\n' "$md5" "$target" | md5sum --check --status; then
      echo "MD5/ETag mismatch $filename" >&2
      rm -f "$target"; exit 1
    fi
  fi
  magic="$(head -c 8 "$target" | od -An -tx1 | tr -d ' \n')"
  if [[ "$magic" != "cdf260020000ffff" ]]; then
    echo "not a CDF v2.6 single-file payload: $filename magic=$magic" >&2
    exit 1
  fi
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
  if (( count % 200 == 0 )); then
    echo "[$(date -Is)] progress files=$count bytes=$bytes fetched_this_run=$fetched"
  fi
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" = "$EXPECTED_COUNT" ]] || { echo "unexpected file count $count" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $bytes" >&2; exit 1; }

stray="$(find "$SOURCE_DIR" -type f ! -name '*.cdf' | head -5)"
[[ -z "$stray" ]] || { echo "stray files in $SOURCE_DIR: $stray" >&2; exit 1; }

# Semantic validation: every file must parse as CDF v2.6 with a GZIP-compressed
# CDF_UINT1 'ampl' variable of 223 delay bins whose CVVRs decompress to exactly
# (MaxRec+1)*223 bytes.
python3 -I -B "$RECIPE_DIR/scripts/isis2_ionogram.py" validate \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_this_run=$fetched"
