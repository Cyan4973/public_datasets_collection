#!/usr/bin/env bash
# Fetch the pinned OzFlux L3/default files' metadata (.dds/.das) and the three
# server-side OPeNDAP projections Fco2.Fco2, Fe.Fe, Fh.Fh (.dods, native
# big-endian Float64) for the 51 thirty-minute files listed in files.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="tern_ozflux_l3_eddy_covariance_fluxes_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DODS_BASE="https://dap.tern.org.au/thredds/dodsC"
UA="openzl-public-datasets-ozflux-l3/1.0"
HELPER="$RECIPE_DIR/scripts/ozflux_dap.py"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch() {
  # fetch <url> <dest>; whole-file retry (OPeNDAP responses are generated on
  # the fly and are small, at most ~3.5 MB), stall-based abort, atomic rename.
  local url="$1" dest="$2"
  rm -f "$dest.part"
  curl --fail --silent --show-error --location --globoff \
    --retry 8 --retry-delay 10 --retry-all-errors \
    --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
    --max-filesize 20000000 --user-agent "$UA" \
    --output "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

files=0
while IFS=$'\t' read -r site release name url_path length step <&3; do
  case "$site" in ''|'#'*) continue ;; esac
  stem="${name%.nc}"
  dir="$DOWNLOAD_DIR/$site"
  mkdir -p "$dir"
  for ext in dds das; do
    if [ ! -s "$dir/$stem.$ext" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
      fetch "$DODS_BASE/$url_path.$ext" "$dir/$stem.$ext"
    fi
  done
  if ! python3 "$HELPER" check-meta "$dir/$stem.dds" "$dir/$stem.das" "$length"; then
    rm -f "$dir/$stem.dds" "$dir/$stem.das"
    echo "FATAL: metadata validation failed for $name" >&2
    exit 1
  fi
  for var in Fco2 Fe Fh; do
    out="$dir/$stem.$var.dods"
    ok=0
    for attempt in 1 2 3; do
      if [ ! -s "$out" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
        fetch "$DODS_BASE/$url_path.dods?$var.$var" "$out"
      fi
      if python3 "$HELPER" check-dods "$out" "$var" "$length" "$url_path"; then
        ok=1
        break
      fi
      echo "invalid payload $out (attempt $attempt); refetching" >&2
      rm -f "$out"
    done
    if [ "$ok" != 1 ]; then
      echo "FATAL: could not obtain a valid $var payload for $name" >&2
      exit 1
    fi
  done
  files=$((files + 1))
done 3< "$RECIPE_DIR/files.tsv"

if [ "$files" != 51 ]; then
  echo "FATAL: expected 51 files, processed $files" >&2
  exit 1
fi
echo "downloaded_files=$files bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
