#!/usr/bin/env bash
# Fetch the 49 pinned ResStock 2021 (AMY2018 release 1) state-level
# single-family-detached aggregate load-profile CSVs from the public OEDI S3
# bucket, plus the by_state listing, the release data dictionary and the OEDI
# submission page (license). Every object must match its pinned size and md5
# (single-part S3 ETag); every CSV is then fully parsed and rejected unless it
# has the pinned 59-column header, exactly 35,040 rows on the contiguous
# 2018-01-01 00:15 .. 2019-01-01 00:00 EST 15-minute lattice, the right state
# and building type, finite numeric cells and fuel totals equal to their
# end-use sums. Anonymous curl only; resumable .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nrel_resstock2021_state_enduse_load_profiles_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/resstock.py"
SOURCES="$RECIPE_DIR/sources.tsv"
BUCKET="https://oedi-data-lake.s3.amazonaws.com"
RELEASE="nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/resstock_amy2018_release_1"
LIST_URL="$BUCKET/?list-type=2&prefix=$RELEASE/timeseries_aggregates/by_state/"
DICT_URL="$BUCKET/$RELEASE/data_dictionary.tsv"
OEDI_URL="https://data.openei.org/submissions/4520"
UA="openzl-public-datasets-resstock/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/by_state" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/by_state"
  mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/by_state"
fi
rm -f "$DOWNLOAD_DIR/DOWNLOAD_OK"

python3 "$RECIPE_DIR/scripts/selftest.py"

small_get() {  # url output max_bytes
  rm -f "$2.part"
  curl --fail --silent --show-error --location \
    --retry 6 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 300 \
    --max-filesize "$3" --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. The live by_state listing must still hold exactly the 49 pinned
#    single-family-detached objects with the pinned size, ETag and date.
small_get "$LIST_URL" "$DOWNLOAD_DIR/meta/listing_by_state.xml" 5000000
python3 "$HELPER" check-listing --listing "$DOWNLOAD_DIR/meta/listing_by_state.xml" --recipe-dir "$RECIPE_DIR"

# 2. Data dictionary (pinned md5; every out.* column float/kWh, timestamps
#    EST) and the OEDI submission page (JSON-LD license = CC BY 4.0, DOI).
small_get "$DICT_URL" "$DOWNLOAD_DIR/meta/data_dictionary.tsv" 2000000
small_get "$OEDI_URL" "$DOWNLOAD_DIR/meta/oedi_submission_4520.html" 10000000
python3 "$HELPER" check-meta --dictionary "$DOWNLOAD_DIR/meta/data_dictionary.tsv" \
  --oedi-page "$DOWNLOAD_DIR/meta/oedi_submission_4520.html" --recipe-dir "$RECIPE_DIR"

# 3. Liveness: one-byte range GET on the first pinned object.
first_key="$(awk -F'\t' 'NR == 2 {print $2}' "$SOURCES")"
code="$(curl --silent --show-error --location --max-time 60 --range 0-0 --user-agent "$UA" \
  --output /dev/null --write-out '%{http_code}' "$BUCKET/${first_key//=/%3D}")"
if [ "$code" != "206" ]; then
  echo "FATAL: liveness range GET returned HTTP $code" >&2
  exit 1
fi

# 4. The 49 state CSVs (about 1.55 GB). A finished file is kept only when it
#    still matches its pinned size and md5; otherwise it is refetched.
fetched=0
while IFS=$'\t' read -r state key size etag _lastmod <&3; do
  [ "$state" = "state" ] && continue
  lower="$(printf '%s' "$state" | tr '[:upper:]' '[:lower:]')"
  out="$DOWNLOAD_DIR/by_state/$lower-single-family_detached.csv"
  url="$BUCKET/${key//=/%3D}"
  if [ -f "$out" ]; then
    if python3 "$HELPER" check-file --path "$out" --size "$size" --md5 "$etag"; then
      continue
    fi
    echo "WARN: existing $state file failed size/md5; refetching" >&2
  fi
  rm -f "$out"
  if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -gt "$size" ]; then
    rm -f "$out.part"
  fi
  attempt=0
  while :; do
    if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" = "$size" ]; then
      break
    fi
    attempt=$((attempt + 1))
    if curl --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
        --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
        --output "$out.part" "$url"; then
      break
    fi
    if [ "$attempt" -ge 4 ]; then
      echo "FATAL: could not fetch $key after $attempt attempts" >&2
      exit 1
    fi
    echo "WARN: curl failed for $state (attempt $attempt); retrying in 30 s" >&2
    sleep 30
  done
  if ! python3 "$HELPER" check-file --path "$out.part" --size "$size" --md5 "$etag"; then
    rm -f "$out.part"
    echo "FATAL: $state payload failed the size/md5 check (partial file removed; re-run to refetch)" >&2
    exit 1
  fi
  mv "$out.part" "$out"
  fetched=$((fetched + 1))
  echo "[$(date -Is)] fetched $state ($size bytes)"
done 3< "$SOURCES"
echo "[$(date -Is)] state files fetched this run: $fetched"

# 5. Semantic validation of all 49 files (md5, header, 35,040-row lattice,
#    identity columns, finite cells, totals == end-use sums).
python3 "$HELPER" validate --recipe-dir "$RECIPE_DIR" --download-dir "$DOWNLOAD_DIR" \
  --out "$DOWNLOAD_DIR/meta/validation.json"

date -Is > "$DOWNLOAD_DIR/DOWNLOAD_OK"
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
