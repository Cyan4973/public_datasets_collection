#!/usr/bin/env bash
# Documents how sources.tsv was resolved. Not part of the acceptance path.
#
# Fetches only metadata from the PDS SBN (PSI) archive: the data_calibrated_v2
# collection inventory, the Apache listings of the recon_b and recon_c phase
# directories, and the PDS4 label (.xml, ~17 KB) of every .dat product in
# them. It then applies the scope rule (scripts/ola_l2.py select):
#
#   data_calibrated_v2 products in recon_b and recon_c whose label file_size
#   is below 200,000,000 bytes
#
# and diffs the result against the pinned sources.tsv.
#
# With PROBE_FLAGS=1 it also samples 150 evenly spaced records of every product
# below 200 MB in preliminary_survey, recon_b, recon_c and sample_collection
# with one multipart byte-range request per product (~50 KB each) and prints
# the flag_status and laser/scan-mode mix. That probe is the evidence for
# excluding preliminary_survey and sample_collection (see README).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="orex_ola_l2_lidar_point_xyz_f64"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/ola_l2.py"
BASE="https://sbnarchive.psi.edu/pds4/orex/orex.ola/data_calibrated_v2"
UA="openzl-public-datasets-orex-ola/1.0"
CURL=(curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors
  --max-time 300 --user-agent "$UA")
mkdir -p "$OUT_DIR/labels" "$OUT_DIR/flag_probe" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

"${CURL[@]}" --output "$OUT_DIR/collection_inventory_ola_data_calibrated_v2.csv" \
  "$BASE/collection_inventory_ola_data_calibrated_v2.csv"
sha256sum "$OUT_DIR/collection_inventory_ola_data_calibrated_v2.csv"

fetch_labels() {
  local phase="$1" product
  "${CURL[@]}" --output "$OUT_DIR/$phase.html" "$BASE/$phase/"
  while read -r product; do
    [ -s "$OUT_DIR/labels/$product.xml" ] || "${CURL[@]}" --output "$OUT_DIR/labels/$product.xml" \
      "$BASE/$phase/$product.xml"
  done < <(python3 "$TOOL" list --listing "$OUT_DIR/$phase.html")
}

for phase in recon_b recon_c; do
  fetch_labels "$phase"
done
python3 "$TOOL" select --discovery-dir "$OUT_DIR" --out "$OUT_DIR/sources.tsv"
python3 "$TOOL" check-inventory --sources "$OUT_DIR/sources.tsv" \
  --inventory "$OUT_DIR/collection_inventory_ola_data_calibrated_v2.csv"
if [ -f "$RECIPE_DIR/sources.tsv" ]; then
  diff -u "$RECIPE_DIR/sources.tsv" "$OUT_DIR/sources.tsv" && echo "selection matches pinned sources.tsv"
fi

if [ "${PROBE_FLAGS:-0}" = "1" ]; then
  for phase in preliminary_survey sample_collection; do
    fetch_labels "$phase"
  done
  printf 'phase\tproduct\trecords\tfile_size\tsampled\tvalid_fraction\tflag_counts\tlaser_scan_mode_counts\tvalid_radius_m\n' \
    > "$OUT_DIR/flag_probe.tsv"
  for phase in preliminary_survey recon_b recon_c sample_collection; do
    while read -r product; do
      label="$OUT_DIR/labels/$product.xml"
      records="$(grep -oP '(?<=<records>)\d+' "$label")"
      size="$(grep -oP '(?<=<file_size unit="byte">)\d+' "$label")"
      [ "$size" -lt 200000000 ] || continue
      ranges=""
      for i in $(seq 0 149); do
        offset=$(( (records * i / 150) * 186 ))
        ranges="$ranges,$offset-$((offset + 185))"
      done
      "${CURL[@]}" --range "${ranges#,}" --output "$OUT_DIR/flag_probe/$product.multipart" \
        "$BASE/$phase/$product.dat"
      python3 "$TOOL" sample-flags --phase "$phase" --label "$label" \
        --response "$OUT_DIR/flag_probe/$product.multipart" >> "$OUT_DIR/flag_probe.tsv"
    done < <(python3 "$TOOL" list --listing "$OUT_DIR/$phase.html")
  done
  column -t -s $'\t' "$OUT_DIR/flag_probe.tsv"
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
