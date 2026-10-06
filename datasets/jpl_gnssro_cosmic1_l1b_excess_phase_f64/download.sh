#!/usr/bin/env bash
# Download the 2,393 pinned JPL COSMIC-1 v2.6 L1b radio-occultation files
# (AWS Open Data "gnss-ro-data" bucket, archive v2.0) listed in sources.tsv,
# plus the upstream data-use-license README.  Anonymous HTTPS only.
#
# Every file is validated against its pinned size and single-part S3 MD5
# ETag, then decoded: the HDF5 metadata checksums, the product identity
# (mission cosmic1, institution jpl, institution_version v2.6, VersionID 2.0,
# data_use_license CC BY 4.0, GranuleID = file name) and the excess_phase
# variable are checked.  Re-runs resume partial .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="jpl_gnssro_cosmic1_l1b_excess_phase_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
BASE_URL="https://gnss-ro-data.s3.amazonaws.com"
README_URL="https://raw.githubusercontent.com/gnss-ro/aws-opendata/master/Readme.md"
MAX_PASSES=8
UA="openzl-public-datasets-gnssro-cosmic1/1.0"
PY="$RECIPE_DIR/scripts/gnssro.py"

mkdir -p "$DOWNLOAD_DIR/files" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# 1. Upstream license statement (small text file, kept as evidence).
readme="$DOWNLOAD_DIR/aws-opendata-Readme.md"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors --max-time 120 --max-filesize 2000000 \
  --user-agent "$UA" --output "$readme.part" "$README_URL"
mv "$readme.part" "$readme"
python3 - "$readme" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
section = text.split("Data use licenses", 1)
if len(section) != 2:
    raise SystemExit("FATAL: upstream README lost its 'Data use licenses' section")
jpl = re.search(r"NASA Jet Propulsion Laboratory.{0,200}?licenses/by/4\.0", section[1], flags=re.S)
if not jpl:
    raise SystemExit("FATAL: upstream README no longer states CC BY 4.0 for JPL data")
print("license_check=ok upstream README states CC BY 4.0 for NASA JPL contributions")
PY

# 2. Liveness: one-byte range GET of the first pinned object.
first_key="$(awk -F'\t' 'NR == 2 {print $3}' "$SOURCES")"
code="$(curl --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null --write-out '%{http_code}' "$BASE_URL/$first_key" || true)"
if [ "$code" != "206" ] && [ "$code" != "200" ]; then
  echo "FATAL: liveness probe of $first_key returned HTTP $code" >&2
  exit 1
fi
echo "liveness=ok http=$code key=$first_key"

# 3. Fetch pinned files in passes; plan validates size+MD5 and resumes .part files.
config="$DOWNLOAD_DIR/curl_files.cfg"
for pass in $(seq 1 "$MAX_PASSES"); do
  python3 "$PY" plan --sources "$SOURCES" --downloads "$DOWNLOAD_DIR" --config "$config"
  pending="$(grep -c '^url = ' "$config" || true)"
  if [ "$pending" = "0" ]; then
    echo "files complete after pass=$pass"
    break
  fi
  echo "[$(date -Is)] pass=$pass fetching=$pending"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --continue-at - --parallel --parallel-max 8 \
    --user-agent "$UA" --config "$config" || echo "curl reported failures on pass=$pass; revalidating"
done
python3 "$PY" plan --sources "$SOURCES" --downloads "$DOWNLOAD_DIR" --config "$config"
if [ "$(grep -c '^url = ' "$config" || true)" != "0" ]; then
  echo "FATAL: files still incomplete after $MAX_PASSES passes" >&2
  exit 1
fi
rm -f "$config"

# 4. Semantic check: every file is the pinned JPL COSMIC-1 v2.6 L1b product.
python3 "$PY" check-downloads --sources "$SOURCES" --downloads "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
