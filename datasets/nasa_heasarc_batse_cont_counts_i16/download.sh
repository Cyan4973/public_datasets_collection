#!/usr/bin/env bash
# Fetch the 50 pinned CGRO BATSE CONT daily FITS files (sources.tsv) from the
# anonymous nasa-heasarc S3 mirror of the HEASARC archive.
#
# Resumable and stall-bounded (curl -C - with --speed-limit/--speed-time, no
# hard --max-time). Each file lands in <name>.part and is renamed only after
# its exact size, S3 ETag (MD5 / 8 MiB-part composite MD5), optional pinned
# SHA-256, gzip integrity, FITS identity and BATSE_CNTS schema/row count all
# validate.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_heasarc_batse_cont_counts_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
VALIDATE="$RECIPE_DIR/scripts/validate_download.py"
BASE_URL="https://nasa-heasarc.s3.amazonaws.com"
UA="openzl-public-datasets-batse-cont/1.0"
README_SHA256="bffda7ff0b652cdcb5a3a0e6656005c8bb41182ebd46512c34e4c0c5e7ef665e"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$VALIDATE" inventory "$SOURCES"

# Liveness: one-byte range GET on the first pinned object.
first_key="$(awk -F'\t' 'NR==2 {print $2}' "$SOURCES")"
curl -fsSL --retry 5 --retry-delay 5 --max-time 60 -A "$UA" -r 0-0 -o /dev/null "$BASE_URL/$first_key"
echo "liveness=ok key=$first_key"

# Provenance: the archive's daily-data README (describes CONT as 2.048 s,
# 16-channel LAD count spectra). Soft: a fetch failure or a changed hash only
# warns, but a README that no longer describes CONT this way is fatal.
readme="$DOWNLOAD_DIR/daily_README.txt"
if curl -fsSL --retry 5 --retry-delay 5 --max-time 120 -A "$UA" -o "$readme.part" "$BASE_URL/compton/data/batse/daily/README"; then
  mv "$readme.part" "$readme"
  if ! grep -q "CONT. The Continuous (CONT) data consists of 2.048 second resolution 16-channel count spectra" "$readme"; then
    echo "FATAL: daily README no longer describes CONT as 2.048 s 16-channel LAD spectra" >&2
    exit 1
  fi
  readme_sha="$(sha256sum "$readme" | awk '{print $1}')"
  [[ "$readme_sha" == "$README_SHA256" ]] || echo "WARN: daily README hash changed: $readme_sha"
  echo "readme=ok sha256=$readme_sha"
else
  rm -f "$readme.part"
  echo "WARN: could not fetch daily README (provenance only)"
fi

fetched=0
cached=0
while IFS=$'\t' read -r tjd key bytes etag rows sha256 <&3; do
  [[ "$tjd" == "tjd" ]] && continue
  name="$(basename "$key")"
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    if python3 "$VALIDATE" file "$SOURCES" "$tjd" "$target"; then
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
  echo "fetch tjd=$tjd bytes=$bytes key=$key"
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
  if ! python3 "$VALIDATE" file "$SOURCES" "$tjd" "$part"; then
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
