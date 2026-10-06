#!/usr/bin/env bash
# Metadata-only discovery that produced scripts/k2_movies.tsv.
#
# Fetches the EMPIAR-10511 data/ autoindex (about 0.9 MB), checks that it holds
# exactly 2979 movies plus gain-reference.mrc, picks the 40 bin-centre movies of
# the name-sorted list, and for each issues one HEAD (exact Content-Length), one
# 1024-byte header range and one 65,536-byte range at the start of frame z = 20.
# The recipe parser validates the header and emits a pin row: slot, listing
# index, file name, size, header SHA-256 and frame-prefix SHA-256. Whole-frame
# SHA-256 pins are filled from the first full download (pin-frames). Total
# transfer is about 3.6 MB.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10511_k2_counting_movie_frames_u8"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/k2_movie_frames.py"
BASE_URL="https://ftp.ebi.ac.uk/empiar/world_availability/10511/data"
UA="openzl-public-datasets-empiar-discovery/1.0"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 300 --user-agent "$UA")

mkdir -p "$OUT_DIR/probe" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

read -r FILE_SIZE _HDR FRAME_START _FRAME_END _FRAME_BYTES PROBE_BYTES < <(python3 "$PY" constants)
"${CURL[@]}" --max-filesize 5000000 --output "$OUT_DIR/data_listing.html" "$BASE_URL/"

PINS="$OUT_DIR/k2_movies.tsv"
printf 'slot\tlisting_index\tfile_name\tsize_bytes\theader_sha256\tframe_prefix_sha256\tframe_sha256\n' > "$PINS.part"
while IFS=$'\t' read -r slot index name; do
  size="$("${CURL[@]}" --head "$BASE_URL/$name" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  [[ "$size" =~ ^[0-9]+$ ]] || { echo "no Content-Length for $name" >&2; exit 1; }
  "${CURL[@]}" --range 0-1023 --output "$OUT_DIR/probe/$name.hdr" "$BASE_URL/$name"
  "${CURL[@]}" --range "$FRAME_START-$((FRAME_START + PROBE_BYTES - 1))" \
    --output "$OUT_DIR/probe/$name.prefix" "$BASE_URL/$name"
  python3 "$PY" probe-row --slot "$slot" --index "$index" --size "$size" --name "$name" \
    --header "$OUT_DIR/probe/$name.hdr" --prefix "$OUT_DIR/probe/$name.prefix" >> "$PINS.part"
done < <(python3 "$PY" selected "$OUT_DIR/data_listing.html")
mv "$PINS.part" "$PINS"
echo "pins written to $PINS ($(($(wc -l < "$PINS") - 1)) movies, file size $FILE_SIZE); copy to $RECIPE_DIR/scripts/k2_movies.tsv"
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
