#!/usr/bin/env bash
# Fetch the 36 pinned USAF RSTN Sagamore Hill 2024 SRS day files (kYYMMDD.srs.gz)
# from NOAA NCEI, resumably, and reject any payload that is not exactly the
# pinned SRS day: exact gzip size, gzip CRC32/ISIZE equal to the pinned
# trailer values, decompressed length a multiple of 826 with the pinned record
# count (>= 5000), and every record header with site 5, 2 bands, band
# descriptors (25,75,401,20,0)/(75,180,401,20,0) and the file's own date (or
# the next UT day). The pinned SHA-256 is enforced when sources.tsv has one.
# Also re-fetches the NCEI ISO metadata record that carries the rights text.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_rstn_sagamore_hill_srs_spectra_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
HELPER="$RECIPE_DIR/scripts/srs.py"
ISO_URL="https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ngdc.stp.solar:solar-features_solar-features_solar-radio/xml"
UA="openzl-public-datasets-rstn-srs/1.0"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-10}"

mkdir -p "$DOWNLOAD_DIR/license" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Rights evidence: NCEI ISO 19115 record for the 'Solar Radio' collection,
# which lists "RSTN solar spectral measurements" and states the constraints.
iso="$DOWNLOAD_DIR/license/ncei_iso_solar_radio.xml"
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
  --connect-timeout 30 --max-time 300 --max-filesize 5000000 \
  --user-agent "$UA" --output "$iso.part" "$ISO_URL"
python3 - "$iso.part" <<'EOF'
import re, sys
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", open(sys.argv[1], encoding="utf-8", errors="replace").read()))
needles = [
    "gov.noaa.ngdc.stp.solar:solar-features_solar-features_solar-radio",
    "RSTN solar spectral measurements",
    "Access Constraints: None",
    "Use Constraints: None",
]
missing = [n for n in needles if n not in text]
if missing:
    sys.exit(f"FATAL: NCEI ISO record lacks expected rights/scope text: {missing}")
print("license evidence ok: 'Access Constraints: None Use Constraints: None' for the RSTN-spectral collection")
EOF
mv "$iso.part" "$iso"

# fetch_file URL OUT SIZE: resumable whole-file download into OUT.part.
# Stalls abort via --speed-limit/--speed-time (never a hard --max-time) and
# the next attempt resumes with -C -.
fetch_file() {
  local url="$1" out="$2" size="$3" part="$2.part" attempt=0 have rc
  while :; do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -eq "$size" ]; then
      break
    fi
    if [ "$have" -gt "$size" ]; then
      echo "partial $part is larger than the pinned size; restarting"
      rm -f "$part"
      have=0
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: $(basename "$out") incomplete after $MAX_ATTEMPTS attempts ($have/$size bytes)" >&2
      return 1
    fi
    echo "fetch attempt=$attempt have=$have/$size $(basename "$out")"
    set +e
    curl --fail --location --silent --show-error -C - \
      --retry 10 --retry-delay 5 --connect-timeout 60 \
      --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((size + 1048576))" \
      --user-agent "$UA" --output "$part" "$url"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      echo "curl exit $rc for $(basename "$out"); retrying"
      sleep $((attempt * 5 < 60 ? attempt * 5 : 60))
    fi
  done
  mv "$part" "$out"
}

count=0
while IFS=$'\t' read -r requested selected filename url size lm crc isize records first sha; do
  [ "$requested" = "requested_date" ] && continue
  [ -n "$requested" ] || continue
  out="$DOWNLOAD_DIR/$filename"
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" -eq "$size" ]; then
    echo "cache_hit $filename"
  else
    rm -f "$out"
    fetch_file "$url" "$out" "$size"
  fi
  if ! python3 "$HELPER" validate --sources "$SOURCES" --filename "$filename" --gz "$out"; then
    echo "FATAL: $filename failed SRS validation; removing it so a rerun refetches" >&2
    rm -f "$out" "$out.sha256"
    exit 1
  fi
  sha256sum "$out" | awk -v f="$filename" '{print $1 "  " f}' > "$out.sha256"
  count=$((count + 1))
done < "$SOURCES"

expected="$(($(grep -c . "$SOURCES") - 1))"
if [ "$count" -ne "$expected" ]; then
  echo "FATAL: validated $count files, expected $expected" >&2
  exit 1
fi
echo "sha256 of validated day files:"
cat "$DOWNLOAD_DIR"/*.srs.gz.sha256
du -sb "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count"
