#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mdpl2_nbody_dm_particle_xyz_f64"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECORD_ID="5259075"
FILE_KEY="mdpl2_particles_0.7333_72m.npy"
FILE_URL="https://zenodo.org/api/records/$RECORD_ID/files/$FILE_KEY/content"
# 128-byte NPY header plus the first 16,000,000 records of 24 bytes.
PREFIX_BYTES=384000128
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-mdpl2-particles-download/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID record=$RECORD_ID prefix_bytes=$PREFIX_BYTES"

# Record metadata: license and file listing evidence, re-checked on every run.
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 120 \
  --user-agent "$UA" --output "$DOWNLOAD_DIR/zenodo_record_$RECORD_ID.json.part" \
  "https://zenodo.org/api/records/$RECORD_ID"
mv "$DOWNLOAD_DIR/zenodo_record_$RECORD_ID.json.part" "$DOWNLOAD_DIR/zenodo_record_$RECORD_ID.json"

# fetch_prefix <dest>: fetch bytes 0..PREFIX_BYTES-1 with HTTP range requests,
# appending each partial response so a stalled transfer resumes where it stopped.
fetch_prefix() {
  local dest="$1" part="$1.part" have code attempt
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" == "$PREFIX_BYTES" ]]; then
    echo "prefix present: $(basename "$dest")"
    return 0
  fi
  touch "$part"
  for attempt in $(seq 1 40); do
    have="$(stat -c %s "$part")"
    if (( have >= PREFIX_BYTES )); then
      break
    fi
    code="$(curl --silent --show-error --location --speed-limit 1024 --speed-time 120 \
      --range "$have-$((PREFIX_BYTES - 1))" --max-filesize "$((PREFIX_BYTES - have + 1))" \
      --user-agent "$UA" --output "$part.chunk" --write-out '%{http_code}' "$FILE_URL")" || true
    if [[ "$code" == "206" ]] && [[ -f "$part.chunk" ]]; then
      cat "$part.chunk" >> "$part"
      echo "attempt $attempt: appended $(stat -c %s "$part.chunk") bytes, have $(stat -c %s "$part") of $PREFIX_BYTES"
    else
      echo "attempt $attempt: HTTP status ${code:-none}, retrying" >&2
      sleep 10
    fi
    rm -f "$part.chunk"
  done
  if [[ "$(stat -c %s "$part")" != "$PREFIX_BYTES" ]]; then
    echo "prefix incomplete or oversized: $(stat -c %s "$part") of $PREFIX_BYTES bytes" >&2
    exit 1
  fi
  mv "$part" "$dest"
}

fetch_prefix "$DOWNLOAD_DIR/mdpl2_particles_0.7333_72m.prefix.npy"

python3 "$RECIPE_DIR/scripts/mdpl2_particles.py" validate --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
