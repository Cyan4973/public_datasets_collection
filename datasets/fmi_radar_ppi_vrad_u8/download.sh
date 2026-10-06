#!/usr/bin/env bash
# Download the 75 pinned FMI fikor ppi_0.5_vrad_qc GeoTIFF scans listed in
# sources.tsv (S3 key, size, ETag MD5, version id). Each object is fetched by
# its pinned S3 version id with resumable curl into a .part file, then checked
# for exact size and MD5 and with scripts/fmivrad.py check-header: classic LE
# TIFF, 2003x2003, uint8, LZW, Predictor 1, 16 tiles of 512x512, GDAL
# SCALE 0.5 / OFFSET -64 / UNITS VRADH, GDAL_NODATA "255", Software
# "Rack_fmi.fi 10.7", DateTime matching the key, the pinned TM35FIN grid, every
# tile decoding to 512x512 with only codes {0, 112..143, 255}, and the
# near-empty / NoData-geometry rules. Only then is the file renamed into place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="fmi_radar_ppi_vrad_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
SCAN_DIR="$DOWNLOAD_DIR/scans"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECKER="$RECIPE_DIR/scripts/fmivrad.py"
UA="openzl-public-datasets-fmi-vrad-download/1.0"
EXPECTED_FILES=75
EXPECTED_BYTES=31677353

mkdir -p "$SCAN_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Decoder self-test before trusting check-header on real payloads.
python3 "$CHECKER" selftest

# Liveness: one-byte range GET on the first pinned object (by version id).
first_url="$(awk -F'\t' 'NR==2{print $8}' "$SOURCES")"
code="$(curl --globoff --silent --show-error --location --range 0-0 --max-time 60 \
  --retry 5 --retry-delay 5 --retry-all-errors --user-agent "$UA" --output /dev/null \
  --write-out '%{http_code}' "$first_url")" || code="000"
[[ "$code" = "206" || "$code" = "200" ]] || { echo "liveness check failed http=$code url=$first_url" >&2; exit 1; }
echo "liveness ok http=$code"

validate() {  # path key size md5 -> 0 if the local file matches the pin
  local path="$1" key="$2" size="$3" md5="$4"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" = "$size" ]] || { echo "size mismatch key=$key got=$(stat -c %s "$path") want=$size" >&2; return 1; }
  [[ "$(md5sum "$path" | awk '{print $1}')" = "$md5" ]] || { echo "md5 mismatch key=$key" >&2; return 1; }
  python3 "$CHECKER" check-header "$path" "$key" >/dev/null || { echo "GeoTIFF product check failed key=$key" >&2; return 1; }
  return 0
}

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'scan_time\tkey\tsize_bytes\tmd5\tsha256\tversion_id\turl\n' > "$plan.tmp"
count=0
bytes=0
fetched=0
while IFS=$'\t' read -r scan_time key size md5 last_modified version_id software url; do
  [[ "$scan_time" != "scan_time" ]] || continue
  target="$SCAN_DIR/$(basename "$key")"
  if validate "$target" "$key" "$size" "$md5" 2>/dev/null; then
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
          --speed-limit 1024 --speed-time 120 --max-filesize 2000000 \
          --user-agent "$UA" --output "$part" "$url" \
          || { echo "curl failed key=$key attempt=$attempt" >&2; sleep 5; continue; }
      fi
      if validate "$part" "$key" "$size" "$md5"; then
        mv "$part" "$target"
        ok=1
        break
      fi
      echo "invalid payload key=$key attempt=$attempt; discarding partial file" >&2
      rm -f "$part"
    done
    (( ok == 1 )) || { echo "giving up on key=$key" >&2; exit 1; }
    fetched=$((fetched + 1))
  fi
  sha="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$scan_time" "$key" "$size" "$md5" "$sha" "$version_id" "$url" >> "$plan.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
  if (( count % 15 == 0 )); then echo "progress files=$count bytes=$bytes fetched_this_run=$fetched"; fi
done < "$SOURCES"

[[ "$count" = "$EXPECTED_FILES" ]] || { echo "unexpected file count $count (want $EXPECTED_FILES)" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "unexpected byte total $bytes (want $EXPECTED_BYTES)" >&2; exit 1; }
stray="$(find "$SCAN_DIR" -type f ! -name '*_fikor_ppi_0.5_vrad_qc.tif' | wc -l)"
[[ "$stray" = "0" ]] || { echo "unexpected extra files in $SCAN_DIR" >&2; exit 1; }
mv "$plan.tmp" "$plan"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes fetched_this_run=$fetched"
