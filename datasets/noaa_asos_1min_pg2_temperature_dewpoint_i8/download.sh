#!/usr/bin/env bash
# Fetch the 509 pinned NOAA NCEI ASOS one-minute page-2 (DSI 6406) station-month
# files listed in sources.tsv (44 stations, 2022, months with >=80% coverage;
# 2,400,428,490 bytes) plus the DSI 6406 documentation and the NCEI ISO
# metadata record. Downloads go to this recipe's own directory; nothing is
# shared with the page-1 recipe.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_asos_1min_pg2_temperature_dewpoint_i8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
UA="openzl-public-datasets-asos-pg2/1.0"
DOC_URL="https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2/doc/asos-1min-pg2_documentation.pdf"
DOC_SHA256="e534851592b80bb157ad5c2350cbe8f5ac2f8778e01b69d93a66dba9f2764d46"
ISO_URL="https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00387/xml"
EXPECTED_FILES=509
EXPECTED_TOTAL_BYTES=2400428490

mkdir -p "$DOWNLOAD_DIR/docs" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# --- documentation and license metadata (small) ---------------------------
doc="$DOWNLOAD_DIR/docs/asos-1min-pg2_documentation.pdf"
if [ ! -s "$doc" ]; then
  curl -fsS -L --retry 5 --retry-delay 3 --retry-all-errors --max-time 300 \
    --user-agent "$UA" -o "$doc.part" "$DOC_URL"
  mv "$doc.part" "$doc"
fi
printf '%s  %s\n' "$DOC_SHA256" "$doc" | sha256sum --check --status || {
  echo "FATAL: DSI 6406 documentation SHA-256 mismatch" >&2; rm -f "$doc"; exit 1; }

iso="$DOWNLOAD_DIR/docs/gov.noaa.ncdc_C00387.xml"
curl -fsS -L --retry 5 --retry-delay 3 --retry-all-errors --max-time 300 \
  --user-agent "$UA" -o "$iso.part" "$ISO_URL"
mv "$iso.part" "$iso"
for pattern in "DSI 6406" "1-Minute Page 2 Surface Weather Observations" "Cite as: NOAA National Weather Service"; do
  grep -q "$pattern" "$iso" || { echo "FATAL: ISO record lacks expected text: $pattern" >&2; exit 1; }
done
echo "docs_ok doc_sha256=$DOC_SHA256 iso_bytes=$(wc -c < "$iso" | tr -d ' ')"

# --- pinned list sanity --------------------------------------------------------
pinned_files="$(awk -F'\t' 'NR>1' "$SOURCES" | wc -l | tr -d ' ')"
pinned_total="$(awk -F'\t' 'NR>1 {s+=$4} END {printf "%d", s}' "$SOURCES")"
if [ "$pinned_files" != "$EXPECTED_FILES" ] || [ "$pinned_total" != "$EXPECTED_TOTAL_BYTES" ]; then
  echo "FATAL: sources.tsv has $pinned_files files / $pinned_total bytes, expected $EXPECTED_FILES / $EXPECTED_TOTAL_BYTES" >&2
  exit 1
fi

# --- liveness check ----------------------------------------------------------
first_url="$(awk -F'\t' 'NR==2 {print $7}' "$SOURCES")"
curl -fsS -L -r 0-0 --max-time 60 --user-agent "$UA" -o /dev/null "$first_url" || {
  echo "FATAL: liveness range GET failed for $first_url" >&2; exit 1; }

# --- station-month files -----------------------------------------------------
n=0; fetched=0; cached=0
while IFS=$'\t' read -r station month filename size_bytes last_modified coverage url; do
  [ "$station" = "station" ] && continue
  n=$((n + 1))
  out_dir="$DOWNLOAD_DIR/$month"
  out="$out_dir/$filename"
  mkdir -p "$out_dir"
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$size_bytes" ]; then
    cached=$((cached + 1))
    continue
  fi
  rm -f "$out"
  if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -gt "$size_bytes" ]; then
    rm -f "$out.part"
  fi
  if [ ! -f "$out.part" ] || [ "$(stat -c %s "$out.part")" != "$size_bytes" ]; then
    curl -fsS -L -C - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" -o "$out.part" "$url"
  fi
  got="$(stat -c %s "$out.part")"
  if [ "$got" != "$size_bytes" ]; then
    echo "FATAL: $filename size $got != pinned $size_bytes (NCEI may have republished; rerun discover.sh)" >&2
    exit 1
  fi
  mv "$out.part" "$out"
  fetched=$((fetched + 1))
  if [ $((n % 25)) -eq 0 ]; then echo "progress files=$n fetched=$fetched cached=$cached"; fi
done < "$SOURCES"
echo "files=$n fetched=$fetched cached=$cached"

# --- semantic validation -------------------------------------------------------
# Every file must end with LF, its first line and >=99% of its lines must
# start with a 5-digit WBAN, the expected ICAO, and the file's year-month.
# Invalid payloads are deleted so a rerun refetches them.
python3 -I "$RECIPE_DIR/scripts/asos_pg2.py" validate --sources "$SOURCES" \
  --download-dir "$DOWNLOAD_DIR" --delete-invalid > "$LOG_DIR/validate.latest.log"
tail -n 1 "$LOG_DIR/validate.latest.log"
actual_total="$(find "$DOWNLOAD_DIR" -name 'asos-1min-pg2-*.dat' -printf '%s\n' | awk '{s+=$1} END {printf "%d", s}')"
if [ "$actual_total" != "$EXPECTED_TOTAL_BYTES" ]; then
  echo "FATAL: downloaded total $actual_total != $EXPECTED_TOTAL_BYTES" >&2; exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID total_bytes=$actual_total"
