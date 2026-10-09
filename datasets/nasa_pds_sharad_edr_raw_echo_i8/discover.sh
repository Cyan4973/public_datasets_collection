#!/usr/bin/env bash
# Metadata-only discovery that produced sources.tsv (run 2026-10-09).
# Fetches MROSH_0001 INDEX.TAB (3.1 MB), the volume MD5 list (2.9 MB), the 24
# selected detached labels (~8 KB each) and three single-row range probes per
# product (3,786 bytes each). Never downloads a science table.
#   WORK_DIR   scratch directory (default /tmp/autocollect/<id>/discover)
#   OUT        output sources.tsv (default <recipe>/sources.tsv)
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="nasa_pds_sharad_edr_raw_echo_i8"
WORK_DIR="${WORK_DIR:-/tmp/autocollect/$DATASET_ID/discover}"
OUT="${OUT:-$RECIPE_DIR/sources.tsv}"
BASE="https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1"
VOL="$BASE/mrosh_0001"
mkdir -p "$WORK_DIR/labels" "$WORK_DIR/probe"
c() { curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 300 "$@"; }

c -o "$WORK_DIR/index.lbl" "$VOL/index/index.lbl"
c -o "$WORK_DIR/index.tab" "$VOL/index/index.tab"
c -o "$WORK_DIR/mrosh_0001.md5" "$BASE/mrosh_0001_260909.md5"
grep -q 'VOLUME_ID *= *"MROSH_0001"' "$WORK_DIR/index.lbl"
grep -q 'ROW_BYTES *= *327' "$WORK_DIR/index.lbl"

python3 -I "$RECIPE_DIR/scripts/sharad.py" select --index "$WORK_DIR/index.tab" --out "$WORK_DIR/selected.tsv"

tail -n +2 "$WORK_DIR/selected.tsv" | cut -f2 | while read -r lbl; do
  c -o "$WORK_DIR/labels/$(basename "$lbl")" "$VOL/$lbl"
done

python3 -I "$RECIPE_DIR/scripts/sharad.py" pin --selected "$WORK_DIR/selected.tsv" \
  --label-dir "$WORK_DIR/labels" --md5-list "$WORK_DIR/mrosh_0001.md5" --out "$WORK_DIR/sources.tsv"

# Row-header probes (first, middle, last row) so download.sh's per-row checks
# are unlikely to fail after a full fetch.
tail -n +2 "$WORK_DIR/sources.tsv" | while IFS=$'\t' read -r ord pid lbl sdat orbit t0 t1 la0 la1 lo0 lo1 band nrec nbytes md5 lmd5 gain; do
  o=$(printf %02d "$ord")
  for which in first mid last; do
    case $which in first) r=0 ;; mid) r=$((nrec / 2)) ;; last) r=$((nrec - 1)) ;; esac
    c -r "$((r * 3786))-$((r * 3786 + 3785))" -o "$WORK_DIR/probe/${o}_${which}.bin" "$VOL/$sdat"
  done
done
python3 -I "$RECIPE_DIR/scripts/sharad.py" probe-rows --sources "$WORK_DIR/sources.tsv" --probe-dir "$WORK_DIR/probe"

cp "$WORK_DIR/sources.tsv" "$OUT"
sha256sum "$OUT"
