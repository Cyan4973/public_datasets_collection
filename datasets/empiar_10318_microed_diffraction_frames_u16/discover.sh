#!/usr/bin/env bash
# Document how scripts/archives.tsv and scripts/frames.tsv were resolved, using
# only small requests: the data directory listing, one HEAD and one 64 KiB tail
# range per archive (central directory + end records), and the first 4 KiB of
# each selected member range (enough to inflate its 512-byte SMV header).
# Writes under $DATA_DIR/discovery/<id>/ (about 640 KB) and diffs the result
# against the committed pin tables. Not part of the download/build path.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10318_microed_diffraction_frames_u16"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
OUT="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE="https://ftp.ebi.ac.uk/empiar/world_availability/10318/data"
UA="openzl-public-datasets-acquisition/1.0"

mkdir -p "$OUT" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

small() { curl --fail --silent --show-error --location --retry 3 --max-time 120 --user-agent "$UA" "$@"; }

small --output "$OUT/listing.html" "$BASE/"
for name in $(grep -o 'href="[^"?/]*\.zip"' "$OUT/listing.html" | sed 's/href="//; s/\.zip"//' | sort -u); do
  small --head --output "$OUT/head_$name.txt" "$BASE/$name.zip"
  total="$(tr -d '\r' < "$OUT/head_$name.txt" | awk 'tolower($1)=="content-length:" {v=$2} END {print v}')"
  small --range "$((total - 65536))-$((total - 1))" --max-filesize 70000 --output "$OUT/tail_$name.bin" "$BASE/$name.zip"
  echo "archive $name bytes=$total"
done

python3 "$RECIPE_DIR/scripts/discover_pins.py" archives "$OUT"
tail -n +2 "$OUT/header_ranges.tsv" | while IFS=$'\t' read -r archive member url start end; do
  small --range "$start-$end" --max-filesize 8192 --output "$OUT/hdr_${archive}__${member}.bin" "$url"
done
python3 "$RECIPE_DIR/scripts/discover_pins.py" frames "$OUT"

status=0
for table in archives.tsv frames.tsv; do
  if diff -u "$RECIPE_DIR/scripts/$table" "$OUT/$table"; then
    echo "pins unchanged: $table"
  else
    echo "PINS DIFFER: $table (review before updating scripts/$table)"
    status=1
  fi
done
echo "[$(date -Is)] discover done dataset=$DATASET_ID status=$status"
exit "$status"
