#!/usr/bin/env bash
# Metadata-only discovery that produced scripts/carotid2_slices.tsv.
#
# For each selected Carotid2 slice it issues one HEAD (exact Content-Length),
# one 8-byte header range and one metadata-tail range (bytes 25165832-EOF,
# about 25 KB), validates the FEI single-IFD layout with the recipe parser,
# and emits a pin row: z, file name, size, SHA-256 of the metadata tail, and
# FEI acquisition timestamp. Whole-file SHA-256 pins are filled from the first
# full download (see README). Total transfer is under 1 MB.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_13192_sbfsem_vessel_slices_u8"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/carotid2_sbfsem.py"
BASE_URL="https://ftp.ebi.ac.uk/empiar/world_availability/13192/data/Stalker_SBF-SEM/Carotid2"
IFD_OFFSET=25165832
UA="openzl-public-datasets-empiar-discovery/1.0"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 300 --user-agent "$UA")

mkdir -p "$OUT_DIR/probe" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

"${CURL[@]}" --max-filesize 5000000 --output "$OUT_DIR/carotid2_listing.html" "$BASE_URL/"
python3 "$PY" check-listing "$OUT_DIR/carotid2_listing.html"

PINS="$OUT_DIR/carotid2_slices.tsv"
printf 'z\tfile_name\tsize_bytes\tmetadata_sha256\tacquisition_datetime\tfile_sha256\n' > "$PINS.part"
for z in $(python3 "$PY" selected); do
  name="$(printf 'Carotid2_Z%04d.tif' "$z")"
  size="$("${CURL[@]}" --head "$BASE_URL/$name" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  [[ "$size" =~ ^[0-9]+$ ]] || { echo "no Content-Length for $name" >&2; exit 1; }
  "${CURL[@]}" --range 0-7 --output "$OUT_DIR/probe/$name.head" "$BASE_URL/$name"
  "${CURL[@]}" --range "$IFD_OFFSET-" --max-filesize 1000000 --output "$OUT_DIR/probe/$name.tail" "$BASE_URL/$name"
  python3 "$PY" probe-row --z "$z" --size "$size" \
    --head "$OUT_DIR/probe/$name.head" --tail "$OUT_DIR/probe/$name.tail" >> "$PINS.part"
  echo "probed $name size=$size"
done
mv "$PINS.part" "$PINS"
echo "pins written to $PINS ($(($(wc -l < "$PINS") - 1)) slices); copy to $RECIPE_DIR/scripts/carotid2_slices.tsv"
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
