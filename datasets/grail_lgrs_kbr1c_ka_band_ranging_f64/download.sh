#!/usr/bin/env bash
# Fetch the 107 pinned GRAIL LGRS KBR1C (Level-1B dual-one-way Ka-band ranging)
# daily products of the extended mission (2012-08-30 .. 2012-12-14, 2-second
# cadence) from the PDS Geosciences Node, volume GRAIL_0101
# (GRAIL-L-LGRS-3-CDR-V1.0, Release 5).
#
# Fetched, in order:
#   1. grail_0101_230316.md5, the volume MD5 manifest (2,948,426 bytes, SHA-256
#      pinned); every pinned .asc/.lbl MD5 must be listed in it;
#   2. per day, the PDS3 label kbr1c_<date>_x_04.lbl (MD5 from the manifest)
#      and the ASCII product kbr1c_<date>_x_04.asc (size pinned in sources.tsv,
#      MD5 from the manifest), resumable into a .part file and semantically
#      validated (header fields, 20 columns per record, finite values, record
#      count, first/last TDB, 2 s lattice) by scripts/kbr1c.py check-asc before
#      it is renamed into place.
# Primary-mission (5 s cadence) products are never fetched.
# Re-runs skip finished files and resume partial ones.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="grail_lgrs_kbr1c_ka_band_ranging_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
TOOL="$RECIPE_DIR/scripts/kbr1c.py"
ROOT_URL="https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1"
BASE="$ROOT_URL/grail_0101/level_1b"
MD5_NAME="grail_0101_230316.md5"
MD5_BYTES=2948426
MD5_SHA256="66193455e5258c971985dd7e2b352416504cddbd531cf3c845818fdaf43185ae"
UA="openzl-public-datasets-grail-kbr1c/1.0"
CURL_SMALL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --max-time 300 --user-agent "$UA")
CURL_BIG=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$TOOL" self-test

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }
file_md5() { md5sum "$1" | cut -d' ' -f1; }

# Liveness and range support: one-byte range GET on the first pinned product.
read -r first_date first_file first_bytes < <(awk -F'\t' 'NR == 2 { print $1, $2, $4 }' "$SOURCES")
live_headers="$DOWNLOAD_DIR/liveness.headers"
"${CURL_SMALL[@]}" --max-time 120 --range 0-0 --dump-header "$live_headers" --output /dev/null \
  "$BASE/$first_date/$first_file" < /dev/null
if ! grep -qiE "^content-range: bytes 0-0/${first_bytes}[[:space:]]*$" "$live_headers"; then
  echo "FATAL: $first_file size changed or byte ranges unsupported" >&2
  cat "$live_headers" >&2
  exit 1
fi
rm -f "$live_headers"
echo "liveness=ok first_file=$first_file bytes=$first_bytes"

# 1. Volume MD5 manifest.
manifest="$DOWNLOAD_DIR/$MD5_NAME"
if [ "$(file_size "$manifest")" != "$MD5_BYTES" ] || [ "$(sha256sum "$manifest" | cut -d' ' -f1)" != "$MD5_SHA256" ]; then
  rm -f "$manifest.part"
  "${CURL_SMALL[@]}" --output "$manifest.part" "$ROOT_URL/$MD5_NAME" < /dev/null
  if [ "$(file_size "$manifest.part")" != "$MD5_BYTES" ] || [ "$(sha256sum "$manifest.part" | cut -d' ' -f1)" != "$MD5_SHA256" ]; then
    echo "FATAL: $MD5_NAME changed upstream (size/SHA-256 differ from the pin)" >&2
    exit 1
  fi
  mv "$manifest.part" "$manifest"
fi
python3 -I "$TOOL" check-md5 --sources "$SOURCES" --md5 "$manifest" < /dev/null

# 2. Labels and products.
total=$(($(wc -l < "$SOURCES") - 1))
n=0
while IFS=$'\t' read -r date file asc_md5 http_bytes _ _ records _ _ label_md5; do
  [ "$date" = "date" ] && continue
  n=$((n + 1))
  case "$date" in 2012_08_3[01]|2012_09_??|2012_1[0-2]_??) ;; *) echo "FATAL: $date outside the extended mission" >&2; exit 1 ;; esac
  dir="$DOWNLOAD_DIR/$date"
  mkdir -p "$dir"

  label="$dir/${file%.asc}.lbl"
  if [ ! -f "$label" ] || [ "$(file_md5 "$label")" != "$label_md5" ]; then
    rm -f "$label.part"
    "${CURL_SMALL[@]}" --output "$label.part" "$BASE/$date/${file%.asc}.lbl" < /dev/null
    mv "$label.part" "$label"
  fi
  python3 -I "$TOOL" check-label --sources "$SOURCES" --date "$date" --label "$label" < /dev/null

  asc="$dir/$file"
  if [ "$(file_size "$asc")" = "$http_bytes" ] && [ "$(file_md5 "$asc")" = "$asc_md5" ]; then
    echo "have $n/$total $date/$file bytes=$http_bytes"
    continue
  fi
  rm -f "$asc"
  part="$asc.part"
  if [ "$(file_size "$part")" -gt "$http_bytes" ]; then
    rm -f "$part"
  fi
  for attempt in 1 2 3 4 5 6 7 8; do
    [ "$(file_size "$part")" = "$http_bytes" ] && break
    if "${CURL_BIG[@]}" --continue-at - --output "$part" "$BASE/$date/$file" < /dev/null; then
      break
    fi
    echo "retry file=$file attempt=$attempt have=$(file_size "$part")/$http_bytes" >&2
    if [ "$(file_size "$part")" -gt "$http_bytes" ]; then
      rm -f "$part"
    fi
    sleep $((attempt * 15))
  done
  if [ "$(file_size "$part")" != "$http_bytes" ]; then
    echo "FATAL: $file is $(file_size "$part") bytes, expected $http_bytes" >&2
    exit 1
  fi
  if ! python3 -I "$TOOL" check-asc --sources "$SOURCES" --date "$date" --asc "$part" < /dev/null; then
    echo "FATAL: $file failed size/MD5/semantic validation; removing the partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$asc"
  echo "fetched $n/$total $date/$file bytes=$http_bytes records=$records"
done < "$SOURCES"

if [ "$n" != "107" ]; then
  echo "FATAL: expected 107 pinned products, processed $n" >&2
  exit 1
fi
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID products=$n"
