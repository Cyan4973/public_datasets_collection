#!/usr/bin/env bash
# Range-fetch only the HDF5 metadata and the three ion-velocity chunk spans of
# 120 pinned ICON IVM-A L2-7 daily NetCDF4 files from the NASA HelioCloud
# public bucket, plus one complete control file for a whole-file cross-check.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icon_ivm_a_l27_ion_drift_velocity_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
LICENSE_URL="https://science.data.nasa.gov/about/license"
BUCKET="https://gov-nasa-hdrl-data1.s3.amazonaws.com/"
USER_AGENT="openzl-public-datasets-icon-ivm-a/1.0"
MAX_META_ROUNDS=80
META_PARALLEL=8
DATA_PARALLEL=4

mkdir -p "$DOWNLOAD_DIR/license" "$DOWNLOAD_DIR/control" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
TOOL=(python3 "$RECIPE_DIR/scripts/icon_ivm.py")
FETCH_RANGE="$RECIPE_DIR/scripts/fetch_range.sh"
die() { echo "ERROR: $*" >&2; exit 1; }

python3 "$RECIPE_DIR/scripts/selftest.py"

# 1. License evidence: NASA Science Data license page (CC0 for NASA-led missions).
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
  --max-time 300 --max-filesize 5000000 --user-agent "$USER_AGENT" \
  --output "$DOWNLOAD_DIR/license/nasa_science_data_license.html.part" "$LICENSE_URL" < /dev/null
mv "$DOWNLOAD_DIR/license/nasa_science_data_license.html.part" "$DOWNLOAD_DIR/license/nasa_science_data_license.html"
"${TOOL[@]}" check-license "$DOWNLOAD_DIR/license/nasa_science_data_license.html"

# 2. Liveness: one-byte range GET of the first pinned object.
first_key="$(sed -n 2p "$RECIPE_DIR/sources.tsv" | cut -f3)"
code="$(curl --silent --location --output /dev/null --write-out '%{http_code}' --range 0-0 \
  --max-time 60 --retry 3 --user-agent "$USER_AGENT" "$BUCKET$first_key" < /dev/null || true)"
[ "$code" = "206" ] || die "liveness check of $BUCKET$first_key returned HTTP $code"

# 3. HDF5 metadata: each round, every unresolved day reports the next 16 KiB
#    block its parser needs; fetch them in parallel until all days resolve.
complete=0
for round in $(seq 1 "$MAX_META_ROUNDS"); do
  set +e
  "${TOOL[@]}" meta-plan --downloads "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"
  status=$?
  set -e
  if [ "$status" = 0 ]; then
    complete=1
    break
  fi
  [ "$status" = 3 ] || exit "$status"
  echo "metadata round=$round blocks=$(wc -l < "$DOWNLOAD_DIR/block_requests.tsv")"
  tr '\t' '\n' < "$DOWNLOAD_DIR/block_requests.tsv" \
    | xargs -d '\n' -n 6 -P "$META_PARALLEL" bash "$FETCH_RANGE"
done
[ "$complete" = 1 ] || die "HDF5 metadata did not resolve within $MAX_META_ROUNDS rounds"

# 4. One contiguous byte span per (day, velocity component) covering its 169
#    shuffle+deflate chunks.
echo "data spans=$(wc -l < "$DOWNLOAD_DIR/data_ranges.tsv")"
tr '\t' '\n' < "$DOWNLOAD_DIR/data_ranges.tsv" \
  | xargs -d '\n' -n 6 -P "$DATA_PARALLEL" bash "$FETCH_RANGE"

# 5. Control: the complete file of the pinned control day (resumable).
control_line="$(awk -F'\t' '$1 == "20210407"' "$RECIPE_DIR/sources.tsv")"
[ -n "$control_line" ] || die "control day missing from sources.tsv"
control_key="$(echo "$control_line" | cut -f3)"
control_size="$(echo "$control_line" | cut -f4)"
control_etag="$(echo "$control_line" | cut -f5)"
control_out="$DOWNLOAD_DIR/control/$(basename "$control_key")"
if [ ! -f "$control_out" ] || [ "$(stat -c %s "$control_out")" != "$control_size" ]; then
  part="$control_out.part"
  if [ ! -f "$part" ] || [ "$(stat -c %s "$part")" -lt "$control_size" ]; then
    curl --fail --silent --show-error --location --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --user-agent "$USER_AGENT" --dump-header "$control_out.hdr" \
      --output "$part" "$BUCKET$control_key" < /dev/null
    etag_seen="$(tr -d '\r"' < "$control_out.hdr" | grep -i '^etag:' | tail -n 1 | cut -d' ' -f2- || true)"
    rm -f "$control_out.hdr"
    [ "$etag_seen" = "$control_etag" ] || { rm -f "$part"; die "control ETag '$etag_seen' != pinned '$control_etag'"; }
  fi
  [ "$(stat -c %s "$part")" = "$control_size" ] || { rm -f "$part"; die "control file size mismatch"; }
  [ "$(head -c 8 "$part" | od -An -tx1 | tr -d ' \n')" = "894844460d0a1a0a" ] || { rm -f "$part"; die "control file lacks the HDF5 signature"; }
  mv "$part" "$control_out"
fi

# 6. Semantic validation: identity attributes, <f8 dtype, rank-1 shape, filter
#    pipeline, chunk grid, every chunk inflated and unshuffled, and the control
#    day's range decode byte-identical to its whole-file decode.
"${TOOL[@]}" inventory --downloads "$DOWNLOAD_DIR" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
