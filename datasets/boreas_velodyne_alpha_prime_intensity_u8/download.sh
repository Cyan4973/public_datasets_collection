#!/usr/bin/env bash
# Fetch the pinned Boreas Velodyne Alpha Prime sweeps (sources.tsv) from the
# public anonymous S3 bucket (AWS Open Data sponsored) s3://boreas over HTTPS.
#
# Every sweep is checked against its pinned size and MD5 (the S3 single-part
# ETag) and semantically validated (24-byte x,y,z,i,r,t float32 records, all
# fields finite, intensity an integer in 0..255, laser_number an integer in
# 0..127) before it is renamed into place. Re-runs skip sweeps that already
# match size and MD5 and resume partial .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="boreas_velodyne_alpha_prime_intensity_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
TOOL="$RECIPE_DIR/scripts/boreas_lidar.py"
BUCKET="https://boreas.s3.amazonaws.com"
LICENSE_URL="https://raw.githubusercontent.com/utiasASRL/pyboreas/master/DATA_LICENSE.md"
UA="openzl-public-datasets-boreas-lidar/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR/meta" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$TOOL" self-test

# License text (small; the recipe refuses to proceed if the grant changes).
curl "${CURL_COMMON[@]}" --max-time 120 -o "$DOWNLOAD_DIR/meta/DATA_LICENSE.md.part" "$LICENSE_URL"
if ! grep -q 'licensed under a Creative Commons Attribution 4.0 International Public License' \
    "$DOWNLOAD_DIR/meta/DATA_LICENSE.md.part"; then
  echo "FATAL: pyboreas DATA_LICENSE.md no longer states CC BY 4.0" >&2
  exit 1
fi
mv "$DOWNLOAD_DIR/meta/DATA_LICENSE.md.part" "$DOWNLOAD_DIR/meta/DATA_LICENSE.md"
echo "license=CC-BY-4.0 (pyboreas DATA_LICENSE.md)"

# Liveness and range support on the first pinned sweep: one-byte range GET.
first_key="$(awk -F'\t' 'NR==2 {print $3}' "$SOURCES")"
first_size="$(awk -F'\t' 'NR==2 {print $4}' "$SOURCES")"
live_headers="$DOWNLOAD_DIR/meta/liveness.headers"
curl "${CURL_COMMON[@]}" --max-time 120 --range 0-0 --dump-header "$live_headers" \
  --output /dev/null "$BUCKET/$first_key"
if ! grep -qiE "^content-range: bytes 0-0/$first_size" "$live_headers"; then
  echo "FATAL: first pinned sweep changed size or byte ranges unsupported" >&2
  tail -n 20 "$live_headers" >&2
  exit 1
fi
echo "liveness=ok key=$first_key"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  find "$DOWNLOAD_DIR" -mindepth 2 -name '*.bin' -delete
fi
mapfile -t todo < <(python3 "$TOOL" check-payloads --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR" --list)
pinned=$(($(wc -l < "$SOURCES") - 1))
echo "sweeps_pinned=$pinned sweeps_to_fetch=${#todo[@]}"
declare -A need=()
for key in "${todo[@]}"; do need["$key"]=1; done

fetched=0
while IFS=$'\t' read -r sequence timestamp key size md5 points _idx _count; do
  [ "$sequence" = "sequence" ] && continue
  [ -n "${need[$key]:-}" ] || continue
  out_dir="$DOWNLOAD_DIR/$sequence"
  out="$out_dir/$timestamp.bin"
  mkdir -p "$out_dir"
  ok=0
  for attempt in 1 2 3; do
    if curl "${CURL_COMMON[@]}" -C - --max-filesize "$((size + 1024))" \
        --output "$out.part" "$BUCKET/$key" < /dev/null \
      && python3 "$TOOL" check-file --sources "$SOURCES" --key "$key" --file "$out.part" < /dev/null; then
      mv "$out.part" "$out"
      ok=1
      break
    fi
    echo "retry key=$key attempt=$attempt" >&2
    # A complete-but-invalid or oversized partial cannot be resumed; start over.
    if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -ge "$size" ]; then rm -f "$out.part"; fi
    sleep $((attempt * 10))
  done
  if [ "$ok" != "1" ]; then
    rm -f "$out.part"
    echo "FATAL: could not fetch a valid sweep for $key" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
  echo "fetched=$fetched/${#todo[@]} key=$key points=$points"
done < "$SOURCES"

python3 "$TOOL" check-payloads --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR" --strict
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
