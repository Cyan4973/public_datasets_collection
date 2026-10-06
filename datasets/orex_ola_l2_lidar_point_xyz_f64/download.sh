#!/usr/bin/env bash
# Fetch the 44 pinned OSIRIS-REx OLA L2 (data_calibrated_v2) products of the
# recon_b and recon_c phases from the PDS Small Bodies Node archive at PSI.
#
# Scope rule (documented by discover.sh, pinned in sources.tsv): every
# data_calibrated_v2 product in recon_b and recon_c whose PDS4 label file_size
# is below 200,000,000 bytes. Nothing from data_calibrated (v1), the
# data_calibrated_l2a_v20/v21 collections or other phases is fetched.
#
# Fetched, in order:
#   1. collection_inventory_ola_data_calibrated_v2.csv (79,790 bytes, SHA-256
#      pinned); every pinned LIDVID must be a primary member;
#   2. per product, the PDS4 label (.xml, size and SHA-256 pinned in
#      sources.tsv) and the binary table (.dat, size pinned in sources.tsv and
#      equal to label records * 186), resumable into a .part file, validated
#      (record framing, met strings, flag codes, valid-return fraction, |xyz|
#      band) by scripts/ola_l2.py check-dat before it is renamed into place.
# If payload_sha256.tsv exists in the recipe, every .dat must also match it.
# Re-runs skip finished files and resume partial ones.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="orex_ola_l2_lidar_point_xyz_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
PINS="$RECIPE_DIR/payload_sha256.tsv"
TOOL="$RECIPE_DIR/scripts/ola_l2.py"
BASE="https://sbnarchive.psi.edu/pds4/orex/orex.ola/data_calibrated_v2"
INVENTORY_NAME="collection_inventory_ola_data_calibrated_v2.csv"
INVENTORY_BYTES=79790
INVENTORY_SHA256="19641a0bc30d1499885077023ede6c82b33ed48e5970a490ac990a32d8c7df45"
UA="openzl-public-datasets-orex-ola/1.0"
CURL_SMALL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --max-time 300 --user-agent "$UA")
CURL_BIG=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$TOOL" self-test

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }
file_sha256() { sha256sum "$1" | cut -d' ' -f1; }
pinned_sha256() {
  [ -f "$PINS" ] || return 0
  awk -F'\t' -v p="$1" 'NR > 1 && $1 == p { print $3 }' "$PINS"
}

# Liveness and range support: one-byte range GET on the first pinned product.
read -r first_phase first_product first_bytes < <(awk -F'\t' 'NR == 2 { print $1, $2, $5 }' "$SOURCES")
live_headers="$DOWNLOAD_DIR/liveness.headers"
"${CURL_SMALL[@]}" --max-time 120 --range 0-0 --dump-header "$live_headers" --output /dev/null \
  "$BASE/$first_phase/$first_product.dat" < /dev/null
if ! grep -qiE "^content-range: bytes 0-0/${first_bytes}[[:space:]]*$" "$live_headers"; then
  echo "FATAL: $first_product.dat size changed or byte ranges unsupported" >&2
  cat "$live_headers" >&2
  exit 1
fi
rm -f "$live_headers"
echo "liveness=ok first_product=$first_product bytes=$first_bytes"

# 1. Collection inventory.
inventory="$DOWNLOAD_DIR/$INVENTORY_NAME"
if [ "$(file_size "$inventory")" != "$INVENTORY_BYTES" ] || [ "$(file_sha256 "$inventory")" != "$INVENTORY_SHA256" ]; then
  rm -f "$inventory.part"
  "${CURL_SMALL[@]}" --output "$inventory.part" "$BASE/$INVENTORY_NAME" < /dev/null
  if [ "$(file_size "$inventory.part")" != "$INVENTORY_BYTES" ] || [ "$(file_sha256 "$inventory.part")" != "$INVENTORY_SHA256" ]; then
    echo "FATAL: $INVENTORY_NAME changed upstream (size/SHA-256 differ from the pin)" >&2
    exit 1
  fi
  mv "$inventory.part" "$inventory"
fi
python3 "$TOOL" check-inventory --sources "$SOURCES" --inventory "$inventory" < /dev/null

# 2. Labels and tables.
total=$(($(wc -l < "$SOURCES") - 1))
n=0
computed="$DOWNLOAD_DIR/payload_sha256.computed.tsv"
printf 'product\tdat_bytes\tsha256\n' > "$computed.part"
while IFS=$'\t' read -r phase product _ records dat_bytes label_bytes label_sha256 _; do
  [ "$phase" = "phase" ] && continue
  n=$((n + 1))
  case "$phase" in recon_b|recon_c) ;; *) echo "FATAL: phase $phase outside scope" >&2; exit 1 ;; esac
  dir="$DOWNLOAD_DIR/$phase"
  mkdir -p "$dir"

  label="$dir/$product.xml"
  if [ "$(file_size "$label")" != "$label_bytes" ] || [ "$(file_sha256 "$label")" != "$label_sha256" ]; then
    rm -f "$label.part"
    "${CURL_SMALL[@]}" --output "$label.part" "$BASE/$phase/$product.xml" < /dev/null
    if [ "$(file_size "$label.part")" != "$label_bytes" ] || [ "$(file_sha256 "$label.part")" != "$label_sha256" ]; then
      echo "FATAL: label $product.xml differs from the pinned size/SHA-256" >&2
      exit 1
    fi
    mv "$label.part" "$label"
  fi
  python3 "$TOOL" check-label --sources "$SOURCES" --product "$product" --label "$label" < /dev/null

  dat="$dir/$product.dat"
  pin="$(pinned_sha256 "$product")"
  if [ "$(file_size "$dat")" = "$dat_bytes" ] && { [ -z "$pin" ] || [ "$(file_sha256 "$dat")" = "$pin" ]; }; then
    echo "have $n/$total $phase/$product.dat bytes=$dat_bytes"
  else
    rm -f "$dat"
    part="$dat.part"
    if [ "$(file_size "$part")" -gt "$dat_bytes" ]; then
      rm -f "$part"
    fi
    for attempt in 1 2 3 4 5 6 7 8; do
      [ "$(file_size "$part")" = "$dat_bytes" ] && break
      if "${CURL_BIG[@]}" --continue-at - --output "$part" "$BASE/$phase/$product.dat" < /dev/null; then
        break
      fi
      echo "retry product=$product attempt=$attempt have=$(file_size "$part")/$dat_bytes" >&2
      if [ "$(file_size "$part")" -gt "$dat_bytes" ]; then
        rm -f "$part"
      fi
      sleep $((attempt * 15))
    done
    if [ "$(file_size "$part")" != "$dat_bytes" ]; then
      echo "FATAL: $product.dat is $(file_size "$part") bytes, expected $dat_bytes" >&2
      exit 1
    fi
    if ! python3 "$TOOL" check-dat --sources "$SOURCES" --product "$product" --label "$label" --dat "$part" < /dev/null; then
      echo "FATAL: $product.dat failed semantic validation; removing the partial file" >&2
      rm -f "$part"
      exit 1
    fi
    if [ -n "$pin" ] && [ "$(file_sha256 "$part")" != "$pin" ]; then
      echo "FATAL: $product.dat SHA-256 differs from payload_sha256.tsv" >&2
      rm -f "$part"
      exit 1
    fi
    mv "$part" "$dat"
    echo "fetched $n/$total $phase/$product.dat bytes=$dat_bytes records=$records"
  fi
  printf '%s\t%s\t%s\n' "$product" "$dat_bytes" "$(file_sha256 "$dat")" >> "$computed.part"
done < "$SOURCES"
mv "$computed.part" "$computed"

if [ "$n" != "44" ]; then
  echo "FATAL: expected 44 pinned products, processed $n" >&2
  exit 1
fi
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID products=$n"
