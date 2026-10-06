#!/usr/bin/env bash
# Download a deterministic 2,000-view selection (20 per series) of TCIA
# LDCT-and-Projection-data Siemens "Full dose projections" DICOM-CT-PD
# instances from the 100 pinned CC BY 4.0 chest/liver series.
#
# Steps (all via the public anonymous NBIA v1 API, curl only):
#   1. refresh getSeries and assert every pinned series' identity, instance
#      count, byte size and CC BY 4.0 license (series_pins.tsv)
#   2. list SOP Instance UIDs for each pinned series (cached; ~236 MB total)
#   3. pick 20 evenly spaced ranks of the lexicographically sorted UIDs
#   4. fetch each selected instance with getSingleImage and reject anything
#      that is not a 736x64 unsigned 16-bit Siemens full-dose DICOM-CT-PD view
#   5. re-validate everything and write download_inventory.json
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tcia_ldct_siemens_ct_projections_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/ldct_ctpd.py"
PINS="$RECIPE_DIR/series_pins.tsv"
API="https://services.cancerimagingarchive.net/nbia-api/services/v1"
COLLECTION="LDCT-and-Projection-data"
DELAY_SECONDS="${DELAY_SECONDS:-0.2}"
UA="openzl-public-datasets-tcia-ldct-projections/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR/sop_lists" "$DOWNLOAD_DIR/dicom" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$TOOL" selftest

fetch() {
  # fetch <url> <output> <max-bytes>: small API objects, stall-based abort.
  curl --fail --silent --show-error --location \
    --retry 8 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-filesize "$3" \
    --user-agent "$UA" --output "$2" "$1"
}

# 1. Live series listing: identity, counts, sizes and license of every pin.
listing="$DOWNLOAD_DIR/series_listing.json"
rm -f "$listing.part"
fetch "$API/getSeries?Collection=$COLLECTION" "$listing.part" 20000000 </dev/null
python3 "$TOOL" check-series --listing "$listing.part" --pins "$PINS"
mv -f "$listing.part" "$listing"

# 2. SOP Instance UID listings, one JSON per pinned series.
listed=0
reused=0
while IFS=$'\t' read -r -u 3 patient _body series _study count _bytes; do
  [ "$patient" = "patient_id" ] && continue
  out="$DOWNLOAD_DIR/sop_lists/$patient.json"
  if [ -s "$out" ] && python3 "$TOOL" check-sops --file "$out" --count "$count" >/dev/null 2>&1; then
    reused=$((reused + 1))
    continue
  fi
  rm -f "$out" "$out.part"
  ok=0
  for attempt in 1 2 3 4; do
    if fetch "$API/getSOPInstanceUIDs?SeriesInstanceUID=$series" "$out.part" 40000000 </dev/null \
      && python3 "$TOOL" check-sops --file "$out.part" --count "$count"; then
      ok=1
      break
    fi
    echo "retry sop_listing patient=$patient attempt=$attempt"
    rm -f "$out.part"
    sleep $((attempt * 15))
  done
  if [ "$ok" != 1 ]; then
    echo "FATAL: SOP listing for $patient failed validation" >&2
    exit 1
  fi
  mv "$out.part" "$out"
  listed=$((listed + 1))
  sleep "$DELAY_SECONDS"
done 3< "$PINS"
echo "sop_listings listed=$listed reused=$reused bytes=$(du -sb "$DOWNLOAD_DIR/sop_lists" | cut -f1)"

# 3. Deterministic selection: 20 evenly spaced ranks per series.
python3 "$TOOL" select --pins "$PINS" --sop-dir "$DOWNLOAD_DIR/sop_lists" --out "$DOWNLOAD_DIR/selection.tsv"

# 4. Selected instances via getSingleImage, validated before acceptance.
fetched=0
reused=0
seen=0
while IFS=$'\t' read -r -u 3 patient series _rank sop; do
  [ "$patient" = "patient_id" ] && continue
  seen=$((seen + 1))
  dir="$DOWNLOAD_DIR/dicom/$patient"
  out="$dir/$sop.dcm"
  mkdir -p "$dir"
  if [ -s "$out" ]; then
    if python3 "$TOOL" check-instance --file "$out" --patient "$patient" --series "$series" --sop "$sop" >/dev/null; then
      reused=$((reused + 1))
      continue
    fi
    echo "discarding invalid cached instance $out"
    rm -f "$out"
  fi
  ok=0
  for attempt in 1 2 3 4 5; do
    rm -f "$out.part"
    if curl --fail --silent --show-error --location \
        --retry 5 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
        --max-time 300 --max-filesize 200000 --user-agent "$UA" \
        --output "$out.part" \
        "$API/getSingleImage?SeriesInstanceUID=$series&SOPInstanceUID=$sop" </dev/null \
      && python3 "$TOOL" check-instance --file "$out.part" --patient "$patient" --series "$series" --sop "$sop" >/dev/null; then
      ok=1
      break
    fi
    echo "retry instance patient=$patient sop=$sop attempt=$attempt"
    sleep $((attempt * 10))
  done
  if [ "$ok" != 1 ]; then
    rm -f "$out.part"
    echo "FATAL: instance $patient/$sop failed download or validation" >&2
    exit 1
  fi
  mv "$out.part" "$out"
  fetched=$((fetched + 1))
  if [ $((seen % 100)) -eq 0 ]; then
    echo "[$(date -Is)] progress instances=$seen fetched=$fetched reused=$reused"
  fi
  sleep "$DELAY_SECONDS"
done 3< "$DOWNLOAD_DIR/selection.tsv"
echo "instances seen=$seen fetched=$fetched reused=$reused"

# 5. Full re-validation and inventory (sizes and SHA-256 of every instance).
python3 "$TOOL" inventory --download-dir "$DOWNLOAD_DIR" --pins "$PINS"
echo "download_dir_bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
