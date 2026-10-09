#!/usr/bin/env bash
# Fetch the 400 pinned Voyager 1 PWS wideband waveform frames (.DAT + detached
# .LBL) listed in sources.tsv from the PDS PPI UIowa plasma-wave archive
# (volume VGPW_1001), plus the volume README, data-set catalog, data tips,
# row-prefix format and frame index as evidence. Every file is pinned by exact
# size and the upstream MD5 published in VGPW_1001/EXTRAS/MD5LF.TXT; every
# label and every DAT record walk is checked before a frame is accepted.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_voyager1_pws_wideband_waveform_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
BASE="https://space.physics.uiowa.edu/plasma-wave/voyager/data/VGPW_1001"
UA="openzl-public-datasets-voyager-pws/1.0"
EXPECTED_FRAMES=400
EXPECTED_DAT_BYTES=322394112
EXPECTED_LBL_BYTES=2753860

mkdir -p "$DOWNLOAD_DIR/evidence" "$DOWNLOAD_DIR/frames" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

md5_of() { md5sum "$1" | cut -c1-32; }

# fetch_pinned <url> <target> <size> <md5> <max_filesize>: resumable, size+MD5 pinned.
fetch_pinned() {
  local url="$1" target="$2" size="$3" md5="$4" maxsize="$5"
  if [[ -s "$target" ]]; then
    if [[ "$(stat -c %s "$target")" == "$size" && "$(md5_of "$target")" == "$md5" ]]; then
      return 0
    fi
    echo "stale_cache $target; refetching"
    rm -f "$target"
  fi
  if [[ -s "$target.part" ]] && (( $(stat -c %s "$target.part") >= size )); then
    rm -f "$target.part"
  fi
  curl --fail --silent --show-error --location -C - \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize "$maxsize" \
    --user-agent "$UA" --output "$target.part" "$url"
  local actual
  actual="$(stat -c %s "$target.part")"
  if [[ "$actual" != "$size" ]]; then
    echo "FATAL size mismatch for $url (expected $size, got $actual)" >&2
    rm -f "$target.part"
    exit 1
  fi
  if [[ "$(md5_of "$target.part")" != "$md5" ]]; then
    echo "FATAL MD5 mismatch for $url (expected $md5)" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Liveness: one-byte range GET on the first pinned frame.
first_stem="$(awk -F'\t' 'NR==2 {print $5}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$BASE/$first_stem.DAT"
echo "liveness_ok url=$BASE/$first_stem.DAT"

# Evidence (size + upstream MD5 pinned, keyword-checked).
EV="$DOWNLOAD_DIR/evidence"
fetch_pinned "$BASE/AAREADME.TXT" "$EV/AAREADME.TXT" 19111 be20a07ad7ec03735df7e5a3dda825eb 100000
fetch_pinned "$BASE/CATALOG/DATASET.CAT" "$EV/DATASET.CAT" 18145 ab203dc944fe60bca4756e4edb113c46 100000
fetch_pinned "$BASE/DOCUMENT/DATATIPS.TXT" "$EV/DATATIPS.TXT" 3961 f48b029b6d1acdf56e28594a01c0d9d2 100000
fetch_pinned "$BASE/DATA/P2/V1P2_100/WFROWPFX.FMT" "$EV/WFROWPFX.FMT" 27707 e52a56c0097ab621b55c77a600a3598b 100000
fetch_pinned "$BASE/INDEX/INDEX.LBL" "$EV/INDEX.LBL" 5469 1d7c7530814097897920580da16b8413 100000
fetch_pinned "$BASE/INDEX/INDEX.TAB" "$EV/INDEX.TAB" 1472664 ae66745eff2a0c88923e32e0de5de770 5000000
grep -q 'encouraged to acknowledge both the PDS' "$EV/AAREADME.TXT"
grep -q 'VG1-J/S/SS-PWS-1-EDR-WFRM-60MS-V1.0' "$EV/DATASET.CAT"
grep -q 'usually the case that the first' "$EV/DATASET.CAT"
grep -q 'repeated 5 times' "$EV/DATASET.CAT"
grep -q 'samples are 4-bit values' "$EV/DATATIPS.TXT"
grep -q 'FDS_LINE_COUNT' "$EV/WFROWPFX.FMT"
grep -q 'ROWS                    = 11415' "$EV/INDEX.LBL"
echo "evidence_ok"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'product_id\tpath_stem\tdat_size\tdat_sha256\tkept_lines\tvalues\n' > "$plan.part"
count=0
dat_bytes=0
lbl_bytes=0
while IFS='|' read -r product start stem dat_size dat_md5 lbl_size lbl_md5; do
  if ! grep -q "\"$product\",$start,.*\"$stem.LBL\"" "$EV/INDEX.TAB"; then
    echo "FATAL $product $start $stem not found in INDEX.TAB" >&2
    exit 1
  fi
  mkdir -p "$DOWNLOAD_DIR/frames/$(dirname "$stem")"
  dat="$DOWNLOAD_DIR/frames/$stem.DAT"
  lbl="$DOWNLOAD_DIR/frames/$stem.LBL"
  fetch_pinned "$BASE/$stem.LBL" "$lbl" "$lbl_size" "$lbl_md5" 100000
  python3 "$CHECK" label "$lbl" "$product" "$dat_size" "$start"
  new=0
  [[ -s "$dat" ]] || new=1
  fetch_pinned "$BASE/$stem.DAT" "$dat" "$dat_size" "$dat_md5" 2000000
  if ! result="$(python3 "$CHECK" dat "$dat" "$lbl" "$product" "$start")"; then
    echo "FATAL semantic validation failed product=$product" >&2
    rm -f "$dat"
    exit 1
  fi
  read -r sha kept values <<< "$result"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$product" "$stem" "$dat_size" "$sha" "$kept" "$values" >> "$plan.part"
  if (( new )); then echo "fetched product=$product bytes=$dat_size kept_lines=$kept"; fi
  count=$((count + 1))
  dat_bytes=$((dat_bytes + dat_size))
  lbl_bytes=$((lbl_bytes + lbl_size))
done < <(awk -F'\t' 'NR > 1 {print $2 "|" $3 "|" $5 "|" $7 "|" $9 "|" $11 "|" $12}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FRAMES" || "$dat_bytes" != "$EXPECTED_DAT_BYTES" || "$lbl_bytes" != "$EXPECTED_LBL_BYTES" ]]; then
  echo "FATAL unexpected selection totals frames=$count dat_bytes=$dat_bytes lbl_bytes=$lbl_bytes" \
    "(expected $EXPECTED_FRAMES / $EXPECTED_DAT_BYTES / $EXPECTED_LBL_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID frames=$count dat_bytes=$dat_bytes lbl_bytes=$lbl_bytes"
