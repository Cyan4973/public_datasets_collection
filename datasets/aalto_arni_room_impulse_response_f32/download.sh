#!/usr/bin/env bash
# Download the 265 pinned Arni impulse-response WAV members by exact ZIP byte
# ranges from Zenodo record 6985104 (CC-BY-4.0), without fetching the
# 4.3-9.7 GB outer archives.
#
# 1. Fetch and validate the record JSON (identity, CC-BY-4.0, file sizes/MD5s).
# 2. Fetch combinations_setup.csv (1.2 MB) and check its MD5/SHA-256.
# 3. For each archive: fetch a 64 KiB tail, parse the classic or ZIP64 EOCD,
#    fetch the exact central directory, check every 206 Content-Range total.
# 4. Re-derive the selection and require it to equal the pinned
#    zip_archives.tsv (incl. central-directory SHA-256) and selection.tsv.
# 5. For each selected member: range-GET local header + compressed data,
#    inflate, check exact DEFLATE boundary, CRC-32, RIFF/WAVE fmt
#    (3,1,44100,176400,4,32), fact length, PEAK consistency, finiteness,
#    and the float-lattice check (< 1% of values on the int16 2^-15 grid,
#    >= 50,000 distinct float32 bit patterns).
# 6. Receiver distinctness: for every configuration, the zero-lag Pearson
#    |r| of all 10 receiver pairs over samples [1500, 17884) must be < 0.5,
#    so one response is never filed under several mic labels.
# Re-runs skip members already validated and delete cached WAVs that are no
# longer in the pinned selection; FORCE_DOWNLOAD=1 starts over.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="aalto_arni_room_impulse_response_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
META_DIR="$DOWNLOAD_DIR/zip_directory"
RANGE_DIR="$DOWNLOAD_DIR/ranges"
WAV_DIR="$DOWNLOAD_DIR/wav"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/arni_tool.py"
PINNED_ARCHIVES="$RECIPE_DIR/zip_archives.tsv"
PINNED_SELECTION="$RECIPE_DIR/selection.tsv"
CSV_NAME="combinations_setup.csv"
CSV_SIZE=1206376
CSV_MD5="6024ff21d2e709d0e20c23b26a8e1542"
CSV_SHA256="6cd64c3f2360a729396888aba6a3f332a6f1954a7ea5452e53bef8ccd05fbd98"
EXPECTED_MEMBERS=265
# shellcheck source=scripts/fetch_lib.sh
source "$RECIPE_DIR/scripts/fetch_lib.sh"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$META_DIR" "$RANGE_DIR" "$WAV_DIR" "$DOWNLOAD_DIR/record.json" "$DOWNLOAD_DIR/$CSV_NAME"
fi
mkdir -p "$META_DIR" "$RANGE_DIR" "$WAV_DIR"

# 1. Record identity, license and file inventory.
arni_curl_get "$ARNI_API_URL" "$DOWNLOAD_DIR/record.json" 20000000
python3 "$TOOL" check-record --record "$DOWNLOAD_DIR/record.json" --archives "$PINNED_ARCHIVES" \
  --csv-size "$CSV_SIZE" --csv-md5 "$CSV_MD5"

# 2. Panel-configuration table (auxiliary cross-check only).
if [ -s "$DOWNLOAD_DIR/$CSV_NAME" ] && python3 "$TOOL" check-csv --csv "$DOWNLOAD_DIR/$CSV_NAME" \
  --size "$CSV_SIZE" --md5 "$CSV_MD5" --sha256 "$CSV_SHA256" >/dev/null 2>&1; then
  echo "cache_hit $CSV_NAME"
else
  arni_curl_get "$(arni_archive_url "$CSV_NAME")" "$DOWNLOAD_DIR/$CSV_NAME" "$((CSV_SIZE + 1024))"
fi
python3 "$TOOL" check-csv --csv "$DOWNLOAD_DIR/$CSV_NAME" --size "$CSV_SIZE" --md5 "$CSV_MD5" --sha256 "$CSV_SHA256"

# 3. Archive tails and exact central directories.
tail -n +2 "$PINNED_ARCHIVES" | cut -f1-3 > "$META_DIR/inventory.tsv"
while IFS=$'\t' read -r archive size _md5; do
  arni_fetch_directory "$TOOL" "$META_DIR" "$archive" "$size"
done < "$META_DIR/inventory.tsv"

# 4. Deterministic selection must equal the pinned tables.
python3 "$TOOL" derive --meta-dir "$META_DIR" --inventory "$META_DIR/inventory.tsv" \
  --archives-out "$META_DIR/derived_zip_archives.tsv" --selection-out "$META_DIR/derived_selection.tsv"
python3 "$TOOL" compare \
  --derived-archives "$META_DIR/derived_zip_archives.tsv" --pinned-archives "$PINNED_ARCHIVES" \
  --derived-selection "$META_DIR/derived_selection.tsv" --pinned-selection "$PINNED_SELECTION"

declare -A ARCHIVE_SIZE
while IFS=$'\t' read -r archive size _md5; do
  ARCHIVE_SIZE["$archive"]="$size"
done < "$META_DIR/inventory.tsv"

# 5. Exact member ranges -> validated WAV files (cached WAVs that fail
#    their CRC/structure checks are removed first and fetched again; cached
#    WAVs not in the pinned selection are deleted and logged).
python3 "$TOOL" final-check --prune --selection "$PINNED_SELECTION" --wav-dir "$WAV_DIR"
fetched=0
cached=0
while IFS=$'\t' read -r archive member _k _c _mic _sweep _lho _csize usize _crc range_start range_end; do
  out="$WAV_DIR/$member"
  if [ -s "$out" ] && [ "$(wc -c < "$out" | tr -d ' ')" = "$usize" ]; then
    cached=$((cached + 1))
    continue
  fi
  arni_curl_range "$(arni_archive_url "$archive")" "$range_start" "$range_end" \
    "$RANGE_DIR/$member.range" "$RANGE_DIR/$member.headers"
  python3 "$TOOL" extract --selection "$PINNED_SELECTION" --member "$member" \
    --headers "$RANGE_DIR/$member.headers" --range-file "$RANGE_DIR/$member.range" \
    --total "${ARCHIVE_SIZE[$archive]}" --out "$out"
  rm -f "$RANGE_DIR/$member.range" "$RANGE_DIR/$member.headers"
  fetched=$((fetched + 1))
done < <(tail -n +2 "$PINNED_SELECTION")
rmdir "$RANGE_DIR" 2>/dev/null || true
echo "members fetched=$fetched cached=$cached"

python3 "$TOOL" final-check --selection "$PINNED_SELECTION" --wav-dir "$WAV_DIR"
# 6. Fatal receiver-distinctness check.
python3 "$TOOL" distinctness --selection "$PINNED_SELECTION" --wav-dir "$WAV_DIR"
count="$(find "$WAV_DIR" -maxdepth 1 -name '*.wav' | wc -l | tr -d ' ')"
if [ "$count" != "$EXPECTED_MEMBERS" ]; then
  echo "FATAL: expected $EXPECTED_MEMBERS WAV members, found $count" >&2
  exit 1
fi
du -sb "$DOWNLOAD_DIR" | awk '{print "download_dir_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
