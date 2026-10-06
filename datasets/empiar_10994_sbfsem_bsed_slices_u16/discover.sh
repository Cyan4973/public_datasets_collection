#!/usr/bin/env bash
# Metadata-only discovery that produced scripts/slices.tsv.
#
# 1. Fetch the EMPIAR entry record, the FAQ licence page and the live Apache
#    listings of both cells' 01_original_images directories, and check that the
#    listings hold exactly the expected 12 acquisition runs (578 + 474 DM4s).
# 2. Range-fetch the first 4 KB of the KD processed-stack Amira file, whose
#    header documents the depositors' deletion of KD slices 274:276 (1-based),
#    i.e. r01d slices 0014-0016 (the beam-fault frames excluded here).
# 3. For every selected slice (every 8th valid slice of each cell, see
#    scripts/empiar10994.py), HEAD for the exact Content-Length and walk the
#    DM4 tag tree from HTTP byte ranges: start with the first 64 KB and the last
#    32 KB, and let the parser request any further range it needs (it never
#    reads the image arrays). The parser enforces all structural and acquisition
#    rules and emits a pin row: size, Data offset, dimensions, calibration,
#    voltage, acquisition time and the SHA-256 of the metadata skeleton (all
#    bytes except undecoded array values). Typical transfer is ~160 KB per
#    file, about 25 MB in total. Whole-file SHA-256 pins are added from the
#    first full download.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10994_sbfsem_bsed_slices_u16"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/empiar10994.py"
BASE="https://ftp.ebi.ac.uk/empiar/world_availability/10994/data"
UA="openzl-public-datasets-empiar-discovery/1.0"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --max-time 300 --user-agent "$UA")

mkdir -p "$OUT_DIR/probe" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

"${CURL[@]}" --max-filesize 5000000 --output "$OUT_DIR/empiar_10994_entry.json" "https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-10994/"
python3 "$PY" check-entry "$OUT_DIR/empiar_10994_entry.json"
"${CURL[@]}" --max-filesize 5000000 --output "$OUT_DIR/empiar_faq.html" "https://www.ebi.ac.uk/empiar/faq"
python3 "$PY" check-license "$OUT_DIR/empiar_faq.html"
"${CURL[@]}" --max-filesize 5000000 --output "$OUT_DIR/listing_control.html" "$BASE/160621_HeLa_Control/01_original_images/"
python3 "$PY" check-listing control "$OUT_DIR/listing_control.html"
"${CURL[@]}" --max-filesize 5000000 --output "$OUT_DIR/listing_kd.html" "$BASE/161107_HeLa_REEP3-4_KD_LBR/01_original_images/"
python3 "$PY" check-listing kd "$OUT_DIR/listing_kd.html"
"${CURL[@]}" --range 0-4095 --output "$OUT_DIR/kd_processed_amira_head.bin" \
  "$BASE/161107_HeLa_REEP3-4_KD_LBR/02_processed_dataset/161107_HeLa_REEP3-4_KD_LBR_R01.am"
python3 "$PY" check-amira "$OUT_DIR/kd_processed_amira_head.bin"

PINS="$OUT_DIR/slices.tsv"
printf 'cell\tz_index\trun\trun_slice\tfile_name\tsize_bytes\tdata_offset\twidth\theight\tpixel_size_um\tvoltage_v\tacquisition\tskeleton_sha256\tfile_sha256\n' > "$PINS.part"
probe_bytes=0
while IFS=$'\t' read -r cell z run slice name url; do
  size="$("${CURL[@]}" --head "$url" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  [[ "$size" =~ ^[0-9]+$ ]] || { echo "no Content-Length for $url" >&2; exit 1; }
  seg_dir="$OUT_DIR/probe/$cell/$name"
  rm -rf "$seg_dir"; mkdir -p "$seg_dir"
  "${CURL[@]}" --range 0-65535 --output "$seg_dir/seg_0.bin" "$url"
  tail_start=$((size - 32768))
  "${CURL[@]}" --range "$tail_start-$((size - 1))" --output "$seg_dir/seg_$tail_start.bin" "$url"
  row=""
  for round in $(seq 1 12); do
    set +e
    out="$(python3 "$PY" probe-row --cell "$cell" --z "$z" --run "$run" --run-slice "$slice" --size "$size" --seg-dir "$seg_dir")"
    rc=$?
    set -e
    if (( rc == 0 )); then row="$out"; break; fi
    if (( rc == 3 )) && [[ "$out" =~ ^need\ ([0-9]+)\ ([0-9]+)$ ]]; then
      lo="${BASH_REMATCH[1]}"; hi="${BASH_REMATCH[2]}"
      "${CURL[@]}" --range "$lo-$hi" --output "$seg_dir/seg_$lo.bin" "$url"
      continue
    fi
    echo "probe failed for $cell/$name: $out" >&2
    exit 1
  done
  [[ -n "$row" ]] || { echo "probe did not converge for $cell/$name" >&2; exit 1; }
  got=$(du -cb "$seg_dir"/seg_*.bin | tail -1 | cut -f1)
  probe_bytes=$((probe_bytes + got))
  printf '%s\n' "$row" >> "$PINS.part"
  echo "probed $cell z=$z $name size=$size range_bytes=$got"
done < <(python3 "$PY" selected)
mv "$PINS.part" "$PINS"
echo "pins written to $PINS ($(($(wc -l < "$PINS") - 1)) slices, range-probe bytes $probe_bytes); copy to $RECIPE_DIR/scripts/slices.tsv"
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
