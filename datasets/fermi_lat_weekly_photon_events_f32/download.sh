#!/usr/bin/env bash
# Fetch the 18 pinned Fermi LAT weekly photon files (sources.tsv) from HEASARC.
#
# Resumable and stall-bounded (curl -C - with --speed-limit/--speed-time, no
# hard --max-time on payloads). Each file lands in <name>.part and is renamed
# only after its exact size, FITS structure, full EVENTS schema, every FITS
# CHECKSUM/DATASUM, and the pinned NAXIS2 / EVENTS DATASUM / TSTART / TSTOP /
# GTI row count all validate (scripts/validate_download.py). A resumed part
# that fails validation (e.g. the file was rewritten upstream mid-transfer) is
# refetched once from scratch before the run fails.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="fermi_lat_weekly_photon_events_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
VALIDATE="$RECIPE_DIR/scripts/validate_download.py"
BASE_URL="https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon"
POLICY_URL="https://fermi.gsfc.nasa.gov/ssc/data/policy/"
UA="openzl-public-datasets-fermi-lat-weekly/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$VALIDATE" inventory "$SOURCES"

# Liveness: one-byte range GET on the first pinned file.
first_name="$(awk -F'\t' 'NR==2 {print $2}' "$SOURCES")"
curl -fsSL --retry 5 --retry-delay 5 --max-time 60 -A "$UA" -r 0-0 -o /dev/null "$BASE_URL/$first_name"
echo "liveness=ok file=$first_name"

# Provenance: the Fermi Science Support Center data-policy page. Soft: a fetch
# failure only warns, but a fetched page that no longer states the LAT
# open-release policy is fatal.
policy="$DOWNLOAD_DIR/fssc_data_policy.html"
if curl -fsSL --retry 3 --retry-delay 5 --max-time 120 -A "$UA" -o "$policy.part" "$POLICY_URL"; then
  mv "$policy.part" "$policy"
  if ! sed -e 's/<[^>]*>//g' "$policy" | tr -s ' \n\t' ' ' | grep -q "all LAT science data has been released as early as possible"; then
    echo "FATAL: FSSC data-policy page no longer states the LAT open-release policy" >&2
    exit 1
  fi
  echo "policy=ok sha256=$(sha256sum "$policy" | awk '{print $1}')"
else
  rm -f "$policy.part"
  echo "WARN: could not fetch FSSC data-policy page (provenance only)"
fi

fetch_part() {  # fetch_part <name> <bytes> : resume <name>.part up to <bytes>
  local name="$1" bytes="$2" part="$DOWNLOAD_DIR/$1.part" attempt=0
  if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$bytes" ]]; then
    echo "discarding oversized partial $name"
    rm -f "$part"
  fi
  until [[ -f "$part" && "$(stat -c %s "$part")" -eq "$bytes" ]] || curl -fL -C - --no-progress-meter --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize $((bytes + 1)) \
      -A "$UA" -o "$part" "$BASE_URL/$name"; do
    attempt=$((attempt + 1))
    if (( attempt >= 5 )); then
      echo "FATAL: curl failed repeatedly for $name" >&2
      return 1
    fi
    if [[ -f "$part" && "$(stat -c %s "$part")" -ge "$bytes" ]]; then
      break
    fi
    echo "retrying (resume) $name attempt=$attempt"
    sleep 10
  done
}

fetched=0
cached=0
while IFS=$'\t' read -r week name bytes rest <&3; do
  [[ "$week" == "week" ]] && continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    if python3 "$VALIDATE" file "$SOURCES" "$week" "$target"; then
      cached=$((cached + 1))
      continue
    fi
    echo "cached $name failed validation; refetching from scratch"
    rm -f "$target.part"
  fi
  rm -f "$target"
  echo "fetch week=$week bytes=$bytes file=$name"
  fetch_part "$name" "$bytes"
  if ! python3 "$VALIDATE" file "$SOURCES" "$week" "$target.part"; then
    echo "WARN: $name failed validation; refetching once from scratch"
    rm -f "$target.part"
    fetch_part "$name" "$bytes"
    if ! python3 "$VALIDATE" file "$SOURCES" "$week" "$target.part"; then
      echo "FATAL: downloaded payload failed validation twice; removing $target.part" >&2
      rm -f "$target.part"
      exit 1
    fi
  fi
  mv "$target.part" "$target"
  fetched=$((fetched + 1))
done 3< "$SOURCES"
echo "fetched=$fetched cached=$cached"

python3 "$VALIDATE" summary "$SOURCES" "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
