#!/usr/bin/env bash
# Fetch only the pinned B/R/Z_FLUX header+data byte ranges (plus each file's
# primary header) of the DESI DR1 iron main/dark healpix coadd FITS files
# listed in pinned_hdus.tsv. Every range is validated against its pinned size,
# header SHA-256, EXTNAME/BUNIT/BITPIX/NAXIS cards and the FITS DATASUM of the
# data unit, so a byte range is checked as strictly as a whole-file checksum.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="desi_dr1_coadd_dark_flux_f32"
PINS="$RECIPE_DIR/pinned_hdus.tsv"
HELPER="$RECIPE_DIR/scripts/desi_coadd.py"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-desi-dr1-coadd/1.0"
LICENSE_URL="https://data.desi.lbl.gov/doc/acknowledgments/"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$HELPER" selftest

# License evidence: the DESI data license page must still grant CC BY 4.0.
license_page="$DOWNLOAD_DIR/acknowledgments.html"
curl -fsSL --retry 5 --retry-delay 3 --max-time 120 --max-filesize 2000000 \
  --user-agent "$UA" -o "$license_page.part" "$LICENSE_URL"
mv "$license_page.part" "$license_page"
# Strip HTML tags first: the page wraps the license name in <strong>.
if ! sed 's/<[^>]*>//g' "$license_page" | tr -s ' \n' ' ' | grep -q 'licensed under the Creative Commons Attribution 4.0 International License'; then
  echo "FATAL: DESI license page no longer states CC BY 4.0" >&2
  exit 1
fi
echo "license_ok url=$LICENSE_URL"

# fetch_range URL START END OUT: exact byte range with manual resume. Each
# attempt requests only the missing tail, insists on HTTP 206 and caps the
# response size so a server that ignored the Range header cannot pull a
# whole file. Transfers are bounded by stall detection, not wall time.
fetch_range() {
  local url="$1" start="$2" end="$3" out="$4"
  local expected=$((end - start + 1))
  local part="$out.part" chunk="$out.chunk"
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$expected" ]; then
    return 0
  fi
  rm -f "$out"
  local attempt have code
  for attempt in $(seq 1 12); do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -gt "$expected" ]; then rm -f "$part"; have=0; fi
    [ "$have" = "$expected" ] && break
    rm -f "$chunk"
    code="$(curl -sS -L --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --max-filesize $((expected - have + 1)) --user-agent "$UA" \
      -r "$((start + have))-$end" -o "$chunk" -w '%{http_code}' "$url" || true)"
    if [ "$code" != "206" ]; then
      echo "warn: attempt=$attempt http=$code url=$url range=$((start + have))-$end" >&2
      if [ "$code" = "200" ]; then
        rm -f "$chunk" "$part"
        echo "FATAL: server ignored the Range header for $url" >&2
        exit 1
      fi
    fi
    if [ "$code" = "206" ] && [ -f "$chunk" ]; then
      cat "$chunk" >> "$part"
    fi
    rm -f "$chunk"
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    [ "$have" = "$expected" ] && break
    sleep $((attempt < 6 ? attempt * 5 : 30))
  done
  if [ ! -f "$part" ] || [ "$(stat -c %s "$part")" != "$expected" ]; then
    echo "FATAL: incomplete range $url $start-$end" >&2
    exit 1
  fi
  mv "$part" "$out"
}

# Liveness: one-byte range GET against the first pinned file.
first_url="$(awk -F'\t' 'NR==2{print $3}' "$PINS")"
probe_code="$(curl -sS -L --max-time 60 -r 0-0 -o /dev/null -w '%{http_code}' --user-agent "$UA" "$first_url" || true)"
if [ "$probe_code" != "206" ]; then
  echo "FATAL: liveness range probe returned http=$probe_code for $first_url" >&2
  exit 1
fi

files=0
ranges=0
total_bytes=0
while IFS=$'\t' read -r -u 3 healpix group url file_bytes last_modified etag pbytes psha arm extname hoff hbytes hsha doff naxis1 naxis2 dbytes datasum; do
  [ "$healpix" = "healpix" ] && continue
  if [ "$arm" = "B" ]; then
    # Same upstream object as pinned: size and Last-Modified must match.
    head="$(curl -fsSIL --retry 5 --retry-delay 3 --max-time 60 --user-agent "$UA" "$url" | tr -d '\r')"
    live_bytes="$(printf '%s\n' "$head" | awk -F': ' 'tolower($1)=="content-length"{v=$2} END{print v}')"
    live_modified="$(printf '%s\n' "$head" | awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}')"
    if [ "$live_bytes" != "$file_bytes" ] || [ "$live_modified" != "$last_modified" ]; then
      echo "FATAL: $url changed: bytes=$live_bytes (pinned $file_bytes) last-modified=$live_modified (pinned $last_modified)" >&2
      exit 1
    fi
    primary="$DOWNLOAD_DIR/coadd-main-dark-$healpix.PRIMARY.header"
    fetch_range "$url" 0 $((pbytes - 1)) "$primary"
    python3 -I "$HELPER" validate-primary --pins "$PINS" --healpix "$healpix" --path "$primary"
    files=$((files + 1))
    total_bytes=$((total_bytes + pbytes))
  fi
  out="$DOWNLOAD_DIR/coadd-main-dark-$healpix.${arm}_FLUX.range"
  start="$hoff"
  end=$((doff + dbytes - 1))
  if [ $((doff - hoff)) != "$hbytes" ]; then
    echo "FATAL: inconsistent pin for $healpix $arm" >&2
    exit 1
  fi
  echo "fetch healpix=$healpix group=$group arm=$arm range=$start-$end bytes=$((end - start + 1)) shape=${naxis2}x${naxis1}"
  fetch_range "$url" "$start" "$end" "$out"
  python3 -I "$HELPER" validate-range --pins "$PINS" --healpix "$healpix" --arm "$arm" --path "$out"
  ranges=$((ranges + 1))
  total_bytes=$((total_bytes + end - start + 1))
done 3< "$PINS"

expected_ranges=$(($(wc -l < "$PINS") - 1))
if [ "$ranges" != "$expected_ranges" ]; then
  echo "FATAL: validated $ranges ranges, expected $expected_ranges" >&2
  exit 1
fi
echo "download_ok files=$files ranges=$ranges range_bytes=$total_bytes"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
