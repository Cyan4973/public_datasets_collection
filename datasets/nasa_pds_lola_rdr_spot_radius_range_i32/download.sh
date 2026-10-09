#!/usr/bin/env bash
# Fetch the 28 pinned LRO LOLA RDR orbit products (one per mapping-orbit phase
# lro_no_01..13, lro_sm_01..15; see discover.sh and sources.tsv) from the NASA
# PDS Geosciences Node, collection LRO-L-LOLA-3-RDR-V1.0, plus their PDS3
# labels and the shared record format lolardr.fmt.
#
# Fetched, in order:
#   1. label/lolardr.fmt (26,916 bytes, SHA-256 pinned), checked to declare
#      RADIUS_k / RANGE_k / SHOT_FLAG_k at the START_BYTEs the parser uses;
#   2. per orbit, lolardr_<YYDDDHHMM>.lbl (MD5 pinned from the volume MD5
#      list; FILE_RECORDS/ROWS, DATA_SET_ID, phase name checked) and
#      lolardr_<YYDDDHHMM>.dat (size and MD5 pinned), resumable into a .part
#      file, then semantically validated by scripts/lola_rdr.py check-dat
#      (size = records * 256, MD5, kept-spot fraction >= 0.30, kept radii and
#      ranges physically plausible and range < 2^31) before it is renamed.
# Re-runs skip finished files and resume partial ones.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_lola_rdr_spot_radius_range_i32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
TOOL="$RECIPE_DIR/scripts/lola_rdr.py"
BASE="https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx"
FMT_BYTES=26916
FMT_SHA256="62855a2463d09e53a198cf06ccb22726d20ca5999a872da02bb93e290688505f"
EXPECTED_ORBITS=28
UA="openzl-public-datasets-lola-rdr/1.0"
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
read -r first_phase first_file first_bytes < <(awk -F'\t' 'NR == 2 { print $1, $2, $3 }' "$SOURCES")
live_headers="$DOWNLOAD_DIR/liveness.headers"
"${CURL_SMALL[@]}" --max-time 120 --range 0-0 --dump-header "$live_headers" --output /dev/null \
  "$BASE/data/lola_rdr/$first_phase/$first_file" < /dev/null
if ! grep -qiE "^content-range: bytes 0-0/${first_bytes}[[:space:]]*$" "$live_headers"; then
  echo "FATAL: $first_file size changed or byte ranges unsupported" >&2
  cat "$live_headers" >&2
  exit 1
fi
rm -f "$live_headers"
echo "liveness=ok first_file=$first_file bytes=$first_bytes"

# 1. Record format.
fmt="$DOWNLOAD_DIR/lolardr.fmt"
if [ "$(file_size "$fmt")" != "$FMT_BYTES" ] || [ "$(sha256sum "$fmt" | cut -d' ' -f1)" != "$FMT_SHA256" ]; then
  rm -f "$fmt.part"
  "${CURL_SMALL[@]}" --output "$fmt.part" "$BASE/label/lolardr.fmt" < /dev/null
  if [ "$(file_size "$fmt.part")" != "$FMT_BYTES" ] || [ "$(sha256sum "$fmt.part" | cut -d' ' -f1)" != "$FMT_SHA256" ]; then
    echo "FATAL: lolardr.fmt changed upstream (size/SHA-256 differ from the pin)" >&2
    exit 1
  fi
  mv "$fmt.part" "$fmt"
fi
python3 -I "$TOOL" check-fmt --fmt "$fmt" < /dev/null

# 2. Labels and orbit products.
total=$(($(wc -l < "$SOURCES") - 1))
n=0
while IFS=$'\t' read -r phase file dat_bytes dat_md5 records lbl_md5 _rest; do
  [ "$phase" = "phase" ] && continue
  n=$((n + 1))
  case "$phase" in lro_no_0[1-9]|lro_no_1[0-3]|lro_sm_0[1-9]|lro_sm_1[0-5]) ;; *) echo "FATAL: $phase outside the pinned mapping-orbit phases" >&2; exit 1 ;; esac
  dir="$DOWNLOAD_DIR/$phase"
  mkdir -p "$dir"
  stem="${file%.dat}"

  label="$dir/$stem.lbl"
  if [ ! -f "$label" ] || [ "$(file_md5 "$label")" != "$lbl_md5" ]; then
    rm -f "$label.part"
    "${CURL_SMALL[@]}" --output "$label.part" "$BASE/data/lola_rdr/$phase/$stem.lbl" < /dev/null
    mv "$label.part" "$label"
  fi
  python3 -I "$TOOL" check-label --sources "$SOURCES" --file "$file" --label "$label" < /dev/null

  dat="$dir/$file"
  if [ "$(file_size "$dat")" = "$dat_bytes" ] && [ "$(file_md5 "$dat")" = "$dat_md5" ]; then
    echo "have $n/$total $phase/$file bytes=$dat_bytes"
    continue
  fi
  rm -f "$dat"
  part="$dat.part"
  if [ "$(file_size "$part")" -gt "$dat_bytes" ]; then
    rm -f "$part"
  fi
  for attempt in 1 2 3 4 5 6 7 8; do
    [ "$(file_size "$part")" = "$dat_bytes" ] && break
    if "${CURL_BIG[@]}" --continue-at - --output "$part" "$BASE/data/lola_rdr/$phase/$file" < /dev/null; then
      break
    fi
    echo "retry file=$file attempt=$attempt have=$(file_size "$part")/$dat_bytes" >&2
    if [ "$(file_size "$part")" -gt "$dat_bytes" ]; then
      rm -f "$part"
    fi
    sleep $((attempt * 15))
  done
  if [ "$(file_size "$part")" != "$dat_bytes" ]; then
    echo "FATAL: $file is $(file_size "$part") bytes, expected $dat_bytes" >&2
    exit 1
  fi
  if ! python3 -I "$TOOL" check-dat --sources "$SOURCES" --file "$file" --dat "$part" < /dev/null; then
    echo "FATAL: $file failed size/MD5/semantic validation; removing the partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$dat"
  echo "fetched $n/$total $phase/$file bytes=$dat_bytes records=$records"
done < "$SOURCES"

if [ "$n" != "$EXPECTED_ORBITS" ]; then
  echo "FATAL: expected $EXPECTED_ORBITS pinned orbits, processed $n" >&2
  exit 1
fi
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID orbits=$n"
