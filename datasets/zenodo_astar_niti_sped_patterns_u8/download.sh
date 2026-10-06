#!/usr/bin/env bash
# Download the pinned Zenodo record metadata (15183487, 15183021), the
# 4096-byte IMGBLO header of each of the eight NiTi ASTAR blockfiles, and
# every 16th scan row of diffraction-pattern frames as exact HTTP byte ranges.
#
# Blockfile layout (NanoMegas ASTAR .blo, as read by RosettaSciIO): header at
# 0, virtual bright-field image (NX*NY uint8) at 4096, then NX*NY frames from
# DP_offset in (NY, NX) raster order. Each frame is a 6-byte prefix (u16
# 0x55AA, u32 frame index) plus 144*144 uint8 pixels, so scan row r is the
# contiguous range [DP_offset + r*NX*20742, DP_offset + (r+1)*NX*20742).
# curl -C - does not compose with --range, so a failed row is discarded and
# re-requested whole (up to ROW_ATTEMPTS times) instead of resumed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="zenodo_astar_niti_sped_patterns_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
CHECK="$RECIPE_DIR/scripts/check_download.py"
PINS_FILE="$RECIPE_DIR/row_sha256.tsv"
UA="openzl-public-datasets-astar-sped/1.0"

FRAME_BYTES=20742     # 6-byte frame prefix + 144 x 144 uint8 pixels
HEADER_BYTES=4096     # IMGBLO header + note, up to the VBF offset
ROW_STRIDE=16         # keep scan rows 0, 16, 32, ... of each map
EXPECTED_ROWS=92
EXPECTED_ROW_BYTES=306587502
ROW_ATTEMPTS="${ROW_ATTEMPTS:-5}"         # whole-row re-requests per row
RETRY_BACKOFF_S="${RETRY_BACKOFF_S:-10}"   # sleep attempt*backoff between attempts

# scan  record   url_key  size  md5  header_sha256  dp_offset  nx  ny
SCANS=(
  "Fig5  15183487 Fig5.blo 453653506 a726b0a4478bf93790dc8ad579da702a 6f6b3522fc910a845996f0b09f7eb35fcf2ec872ed7eb16d08aae5fe66835997 25966 135 162"
  "Fig6  15183487 Fig6.blo 583380228 f9e2647ef0b52a77b22c7a52b1a6f9cb 7be6c4e7b05e1cba663dbd7eb9dd46615fd59a32d69965c0ae62db40b208e086 32220 158 178"
  "Fig7  15183487 Fig7.blo 635258471 745633a3a3be45bbc337b19a266a5e86 bb35bc211256eef89ef36d0d21cb3432f68b524ea0e01f24e6cfe8fad6fc2e67 34721 175 175"
  "Fig8  15183487 Fig8.blo 622045180 d604fc67001a74514bbe5511367b44e8 e3492609166990d19f419fc7a5686636eb3218f79776407360de9ca2b02f3673 34084 147 204"
  "FigS5 15183487 Fig%20S5.blo 543055836 3c89835f180722c8a47212536eb4354d efe138455c15a638945f518ece0fe7ba6fcce64e60f15f0251c62082226aae97 30276 154 170"
  "Fig9  15183021 Fig9_ASTAR_NiTi5_15ms_chlazeni50MPa_zrno5_CL145mm_0p6precese.blo 463485688 feb1e665447b9da0de1a9b72d6a39566 923248db0710b62695da2058eaf6d6bb064e7391c11a020a4e5cfbb2e9d83c40 26440 152 147"
  "Fig10 15183021 Fig10_ASTAR_NiTi5_15ms_300MPa_chlazeni_zrno5.blo 963309016 c2c8ef14513453020309e942ab4f28b5 e5d37c17252b1e8eb7f1b6683d4936275e7615db96c32eeee7de41557b4c6085 50536 215 216"
  "Fig11 15183021 Fig11_ASTAR_NiTi5_15ms_chlazeni600MPa_zrno2_CL100mm_0p5precese_2_2.blo 430836206 6bd1b28d465b88059b8a6f1ed575b8d8 6c58ceb0e759e6cb234045c7d45be966476ce945b71daa32c367f11e129b8b15 24866 134 155"
)
# record  title needle (case-insensitive substring of the Zenodo title)
RECORDS=(
  "15183487|Reconstruction of martensite variant microstructures in grains of deformed NiTi"
  "15183021|Martensitic transformation induced by cooling NiTi wire under various tensile stresses"
)

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID stride=$ROW_STRIDE"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$DOWNLOAD_DIR"/record_*.json "$DOWNLOAD_DIR"/*.header.bin* \
    "$DOWNLOAD_DIR"/*.row*.bin "$DOWNLOAD_DIR"/*.row*.bin.part \
    "$DOWNLOAD_DIR"/*.headers "$DOWNLOAD_DIR"/*.headers.part "$DOWNLOAD_DIR"/row_sha256.tsv
fi

# ---------------------------------------------------------------- metadata
for rec_spec in "${RECORDS[@]}"; do
  rec="${rec_spec%%|*}"
  needle="${rec_spec#*|}"
  metadata="$DOWNLOAD_DIR/record_$rec.json"
  rm -f "$metadata.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --connect-timeout 30 --max-time 180 --max-filesize 20000000 \
    --user-agent "$UA" --header "Accept: application/json" \
    --output "$metadata.part" "https://zenodo.org/api/records/$rec"
  mv "$metadata.part" "$metadata"
  specs=()
  for spec in "${SCANS[@]}"; do
    read -r _scan srec key size md5 _rest <<<"$spec"
    if [ "$srec" = "$rec" ]; then specs+=("$key:$size:$md5"); fi
  done
  python3 "$CHECK" record "$metadata" "$rec" "$needle" "${specs[@]}"
done

# ----------------------------------------------------------------- headers
for spec in "${SCANS[@]}"; do
  read -r scan rec key size _md5 hsha dp_offset nx ny <<<"$spec"
  out="$DOWNLOAD_DIR/$scan.header.bin"
  hdr="$out.headers"
  if [ -s "$out" ] && python3 "$CHECK" header "$out" - "$size" "$hsha" "$dp_offset" "$nx" "$ny" "$scan.header.bin"; then
    echo "cache_hit $scan.header.bin"
    continue
  fi
  ok=0
  for attempt in $(seq 1 "$ROW_ATTEMPTS"); do
    rm -f "$out.part" "$hdr.part"
    if curl --fail --silent --show-error --location \
         --retry 5 --retry-delay 3 --retry-all-errors \
         --connect-timeout 30 --max-time 120 --max-filesize 100000 \
         --range "0-$((HEADER_BYTES - 1))" --user-agent "$UA" \
         --dump-header "$hdr.part" --output "$out.part" \
         "https://zenodo.org/api/records/$rec/files/$key/content" \
       && python3 "$CHECK" header "$out.part" "$hdr.part" "$size" "$hsha" "$dp_offset" "$nx" "$ny" "$scan.header.bin"; then
      mv "$hdr.part" "$hdr"
      mv "$out.part" "$out"
      ok=1
      break
    fi
    echo "header $scan attempt $attempt failed" >&2
    sleep $((attempt * RETRY_BACKOFF_S))
  done
  [ "$ok" = 1 ] || { echo "FATAL: could not fetch a valid header for $scan" >&2; exit 1; }
done

# ------------------------------------------------------------ row ranges
fetch_row() {
  local scan="$1" rec="$2" key="$3" size="$4" dp_offset="$5" nx="$6" row="$7"
  local row_bytes=$((nx * FRAME_BYTES))
  local start=$((dp_offset + row * row_bytes))
  local end=$((start + row_bytes - 1))
  local file; file="$(printf '%s.row%03d.bin' "$scan" "$row")"
  local out="$DOWNLOAD_DIR/$file"
  local headers="$DOWNLOAD_DIR/$file.headers"
  local pins="-"
  [ -f "$PINS_FILE" ] && pins="$PINS_FILE"
  if [ -s "$out" ]; then
    local cached_headers="-"
    [ -s "$headers" ] && cached_headers="$headers"
    if python3 "$CHECK" row "$out" "$cached_headers" "$start" "$end" "$size" "$nx" "$row" "$pins" "$file"; then
      echo "cache_hit $file"
      return 0
    fi
    echo "cached $file failed validation; refetching"
    rm -f "$out" "$headers"
  fi
  local attempt
  for attempt in $(seq 1 "$ROW_ATTEMPTS"); do
    rm -f "$out.part" "$headers.part"
    echo "fetch $file range=$start-$end attempt=$attempt"
    if curl --fail --silent --show-error --location \
         --retry 10 --retry-delay 5 --retry-all-errors \
         --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
         --max-filesize "$((row_bytes + 1024))" \
         --range "$start-$end" --user-agent "$UA" \
         --dump-header "$headers.part" --output "$out.part" \
         "https://zenodo.org/api/records/$rec/files/$key/content"; then
      if python3 "$CHECK" row "$out.part" "$headers.part" "$start" "$end" "$size" "$nx" "$row" "$pins" "$file"; then
        mv "$headers.part" "$headers"
        mv "$out.part" "$out"
        return 0
      fi
    fi
    echo "row $file attempt $attempt failed" >&2
    sleep $((attempt * RETRY_BACKOFF_S))
  done
  rm -f "$out.part" "$headers.part"
  echo "FATAL: could not fetch a valid $file after $ROW_ATTEMPTS attempts" >&2
  return 1
}

for spec in "${SCANS[@]}"; do
  read -r scan rec key size _md5 _hsha dp_offset nx ny <<<"$spec"
  for ((row = 0; row < ny; row += ROW_STRIDE)); do
    fetch_row "$scan" "$rec" "$key" "$size" "$dp_offset" "$nx" "$row"
  done
done

# Record realized row checksums (the recipe pins these in row_sha256.tsv).
(
  printf '# file\tbytes\tsha256\n'
  for spec in "${SCANS[@]}"; do
    read -r scan _rec _key _size _md5 _hsha _dp nx ny <<<"$spec"
    for ((row = 0; row < ny; row += ROW_STRIDE)); do
      f="$(printf '%s.row%03d.bin' "$scan" "$row")"
      printf '%s\t%s\t%s\n' "$f" "$(wc -c < "$DOWNLOAD_DIR/$f" | tr -d ' ')" "$(sha256sum "$DOWNLOAD_DIR/$f" | cut -d' ' -f1)"
    done
  done
) > "$DOWNLOAD_DIR/row_sha256.tsv.part"
mv "$DOWNLOAD_DIR/row_sha256.tsv.part" "$DOWNLOAD_DIR/row_sha256.tsv"
row_files="$(grep -vc '^#' "$DOWNLOAD_DIR/row_sha256.tsv")"
row_total="$(awk -F'\t' '!/^#/ {s += $2} END {print s}' "$DOWNLOAD_DIR/row_sha256.tsv")"
echo "rows=$row_files row_bytes=$row_total"
[ "$row_files" = "$EXPECTED_ROWS" ] && [ "$row_total" = "$EXPECTED_ROW_BYTES" ] \
  || { echo "FATAL: expected $EXPECTED_ROWS rows / $EXPECTED_ROW_BYTES bytes" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID"
