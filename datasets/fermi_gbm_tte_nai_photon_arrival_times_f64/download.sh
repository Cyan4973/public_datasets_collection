#!/usr/bin/env bash
# Fetch the 60 pinned Fermi GBM burst TTE NaI FITS files (sources.tsv) from the
# anonymous nasa-heasarc S3 mirror of the HEASARC archive.
#
# Resumable and stall-bounded (curl -C - with --speed-limit/--speed-time, no
# hard --max-time on payloads). Each file lands in <name>.part and is renamed
# only after its exact size, S3 ETag (MD5 / 8 MiB-part composite MD5), FITS
# identity, EVENTS schema, FITS CHECKSUM/DATASUM, pinned NAXIS2 and pinned
# TZERO1 all validate (scripts/validate_download.py).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="fermi_gbm_tte_nai_photon_arrival_times_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
VALIDATE="$RECIPE_DIR/scripts/validate_download.py"
BASE_URL="https://nasa-heasarc.s3.amazonaws.com"
POLICY_URL="https://fermi.gsfc.nasa.gov/ssc/data/policy/"
UA="openzl-public-datasets-fermi-gbm-tte/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$VALIDATE" inventory "$SOURCES"

# Liveness: one-byte range GET on the first pinned object.
first_key="$(awk -F'\t' 'NR==2 {print $5}' "$SOURCES")"
curl -fsSL --retry 5 --retry-delay 5 --max-time 60 -A "$UA" -r 0-0 -o /dev/null "$BASE_URL/$first_key"
echo "liveness=ok key=$first_key"

# Provenance: the Fermi Science Support Center data-policy page. Soft: a fetch
# failure only warns, but a fetched page that no longer states the GBM
# open-data policy is fatal.
policy="$DOWNLOAD_DIR/fssc_data_policy.html"
if curl -fsSL --retry 3 --retry-delay 5 --max-time 120 -A "$UA" -o "$policy.part" "$POLICY_URL"; then
  mv "$policy.part" "$policy"
  if ! sed -e 's/<[^>]*>//g' "$policy" | tr -s ' \n\t' ' ' | grep -q "GBM data were not proprietary at any time during the mission"; then
    echo "FATAL: FSSC data-policy page no longer states that GBM data were never proprietary" >&2
    exit 1
  fi
  echo "policy=ok sha256=$(sha256sum "$policy" | awk '{print $1}')"
else
  rm -f "$policy.part"
  echo "WARN: could not fetch FSSC data-policy page (provenance only)"
fi

fetched=0
cached=0
while IFS=$'\t' read -r burst year detector version key bytes etag rows tzero1 rest <&3; do
  [[ "$burst" == "burst" ]] && continue
  name="$(basename "$key")"
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    if python3 "$VALIDATE" file "$SOURCES" "$burst" "$target"; then
      cached=$((cached + 1))
      continue
    fi
    echo "cached $name failed validation; refetching from scratch"
    rm -f "$target.part"
  fi
  rm -f "$target"
  part="$target.part"
  if [[ -f "$part" ]]; then
    have="$(stat -c %s "$part")"
    if (( have > bytes )); then
      echo "discarding oversized partial $name ($have > $bytes)"
      rm -f "$part"
    fi
  fi
  echo "fetch burst=$burst detector=$detector bytes=$bytes key=$key"
  attempt=0
  until [[ -f "$part" && "$(stat -c %s "$part")" -eq "$bytes" ]] || curl -fL -C - --no-progress-meter --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize $((bytes + 1)) \
      -A "$UA" -o "$part" "$BASE_URL/$key"; do
    attempt=$((attempt + 1))
    if (( attempt >= 3 )); then
      echo "FATAL: curl failed repeatedly for $key" >&2
      exit 1
    fi
    if [[ -f "$part" && "$(stat -c %s "$part")" -ge "$bytes" ]]; then
      break
    fi
    echo "retrying (resume) $name attempt=$attempt"
    sleep 10
  done
  if ! python3 "$VALIDATE" file "$SOURCES" "$burst" "$part"; then
    echo "FATAL: downloaded payload failed validation; removing $part" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  fetched=$((fetched + 1))
done 3< "$SOURCES"
echo "fetched=$fetched cached=$cached"

python3 "$VALIDATE" summary "$SOURCES" "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
