#!/usr/bin/env bash
# Download the pinned Dataverse v1.1 listing and the 19 original country CSVs
# of the AfSIS Phase I MIR spectra (doi:10.34725/DVN/QXCWP1).
#
# The Dataverse access API ignores Range requests, so a partial file cannot be
# resumed with -C -. Each file is fetched whole into a .part file, retried on
# transient failures and stalls, then checked against the pinned original size
# and the Dataverse MD5, and against the pinned header grid, before rename.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icraf_afsis1_soil_mir_spectra_f32"
BASE_URL="${AFSIS_DATAVERSE_BASE:-https://data.worldagroforestry.org}"
PERSISTENT_ID="doi:10.34725/DVN/QXCWP1"
LISTING_URL="$BASE_URL/api/datasets/:persistentId/versions/1.1?persistentId=$PERSISTENT_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
CSV_DIR="$DOWNLOAD_DIR/csv"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/afsis_mir.py"
SOURCES="$RECIPE_DIR/sources.tsv"
EXPECTED_FILES=19
EXPECTED_BYTES=327146877
MAX_ATTEMPTS="${AFSIS_MAX_ATTEMPTS:-6}"
UA="openzl-public-datasets-afsis1-mir/1.0"

mkdir -p "$CSV_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

curl_common=(
  --fail --location --silent --show-error
  --retry 10 --retry-all-errors --retry-delay 15
  --connect-timeout 30 --speed-limit 1024 --speed-time 120
  --user-agent "$UA"
)

# 1. Pinned version-1.1 listing (license text, file ids, sizes, MD5s).
listing="$DOWNLOAD_DIR/dataset_version_1.1.json"
listing_ok=0
if [[ -s "$listing" && "${FORCE_DOWNLOAD:-0}" != "1" ]] \
  && python3 "$TOOL" check-listing --json "$listing" --sources "$SOURCES"; then
  listing_ok=1
  echo "cache_hit listing=$listing"
fi
attempt=0
while [[ "$listing_ok" != 1 ]]; do
  attempt=$((attempt + 1))
  if (( attempt > MAX_ATTEMPTS )); then
    echo "FATAL: could not obtain a valid version-1.1 listing" >&2
    exit 1
  fi
  rm -f "$listing.part"
  rc=0
  curl "${curl_common[@]}" --max-time 300 --max-filesize 5000000 \
    --output "$listing.part" "$LISTING_URL" || rc=$?
  if [[ "$rc" == 0 ]]; then
    # A listing that parses but disagrees with the pins is semantic, not transient.
    python3 "$TOOL" check-listing --json "$listing.part" --sources "$SOURCES"
    mv "$listing.part" "$listing"
    listing_ok=1
  else
    echo "listing attempt=$attempt curl_rc=$rc; sleeping before retry"
    sleep $((attempt * 30))
  fi
done

# 2. The 19 original country CSVs, keyed by Dataverse datafile id.
file_matches() {
  local path="$1" size="$2" md5="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" == "$size" ]] || return 1
  printf '%s  %s\n' "$md5" "$path" | md5sum --check --status
}

file_count=0
file_bytes=0
while IFS=$'\t' read -r datafile_id local_filename upstream_name country size md5; do
  [[ "$datafile_id" != "datafile_id" ]] || continue
  target="$CSV_DIR/$local_filename"
  url="$BASE_URL/api/access/datafile/$datafile_id?format=original"
  if [[ "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    rm -f "$target"
  fi
  if file_matches "$target" "$size" "$md5"; then
    echo "cache_hit id=$datafile_id file=$local_filename bytes=$size"
  else
    rm -f "$target"
    attempt=0
    while :; do
      attempt=$((attempt + 1))
      if (( attempt > MAX_ATTEMPTS )); then
        echo "FATAL: id=$datafile_id ($upstream_name) failed after $MAX_ATTEMPTS attempts" >&2
        exit 1
      fi
      rm -f "$target.part"
      echo "fetch id=$datafile_id upstream=\"$upstream_name\" expected_bytes=$size attempt=$attempt"
      rc=0
      curl "${curl_common[@]}" --max-filesize $((size + 1048576)) \
        --output "$target.part" "$url" || rc=$?
      if [[ "$rc" == 0 ]] && file_matches "$target.part" "$size" "$md5"; then
        break
      fi
      got="$(stat -c %s "$target.part" 2>/dev/null || echo 0)"
      echo "retry id=$datafile_id attempt=$attempt curl_rc=$rc got_bytes=$got (need size=$size md5=$md5)"
      sleep $((attempt * 30))
    done
    python3 "$TOOL" check-file --path "$target.part" --country "$country"
    mv "$target.part" "$target"
  fi
  file_count=$((file_count + 1))
  file_bytes=$((file_bytes + size))
done < "$SOURCES"

if [[ "$file_count" != "$EXPECTED_FILES" || "$file_bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL: got files=$file_count bytes=$file_bytes, expected $EXPECTED_FILES / $EXPECTED_BYTES" >&2
  exit 1
fi
(cd "$CSV_DIR" && sha256sum -- *.csv) > "$DOWNLOAD_DIR/csv_sha256.txt"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$file_count bytes=$file_bytes"
