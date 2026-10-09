#!/usr/bin/env bash
# Fetch the 460 pinned GoldenCheetah OpenData athlete zips listed in sources.tsv
# (always via https://osf.io/download/<id>/, whose signed storage redirect
# expires), validate size + SHA-256 + MD5, then validate zip structure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="goldencheetah_opendata_cycling_cadence_u8"
ZIP_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/zips"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-goldencheetah-download/1.0"
EXPECTED_COUNT=460
EXPECTED_BYTES=2807759073

mkdir -p "$ZIP_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

count=0
bytes=0
while IFS=$'\t' read -r filename osf_id size_bytes sha256 md5 date_modified url; do
  [[ "$filename" != "filename" ]] || continue
  [[ "$url" == "https://osf.io/download/$osf_id/" ]] || { echo "bad url row: $filename" >&2; exit 1; }
  target="$ZIP_DIR/$filename"
  if [[ -s "$target" && "$(stat -c %s "$target")" == "$size_bytes" ]]; then
    echo "cache_hit bytes=$size_bytes file=$filename"
  else
    rm -f "$target"
    if [[ -s "$target.part" && "$(stat -c %s "$target.part")" -gt "$size_bytes" ]]; then
      rm -f "$target.part"
    fi
    if [[ -s "$target.part" && "$(stat -c %s "$target.part")" == "$size_bytes" ]]; then
      echo "resume_complete bytes=$size_bytes file=$filename"
    else
      echo "fetch bytes=$size_bytes file=$filename id=$osf_id"
      curl --fail --location --silent --show-error -C - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$target.part" "$url"
    fi
    mv "$target.part" "$target"
  fi
  actual="$(stat -c %s "$target")"
  if [[ "$actual" != "$size_bytes" ]]; then
    echo "size mismatch file=$filename expected=$size_bytes actual=$actual" >&2
    mv "$target" "$target.bad"
    exit 1
  fi
  if [[ "$(sha256sum "$target" | awk '{print $1}')" != "$sha256" ]]; then
    echo "SHA-256 mismatch file=$filename" >&2
    mv "$target" "$target.bad"
    exit 1
  fi
  printf '%s  %s\n' "$md5" "$target" | md5sum --check --status || { echo "MD5 mismatch file=$filename" >&2; exit 1; }
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" == "$EXPECTED_COUNT" ]] || { echo "unexpected file count $count" >&2; exit 1; }
[[ "$bytes" == "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $bytes" >&2; exit 1; }

# Semantic payload check: zip CRCs, athlete RIDES JSON, CSV members/headers.
python3 -I "$RECIPE_DIR/scripts/gc_cadence.py" check-download \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
