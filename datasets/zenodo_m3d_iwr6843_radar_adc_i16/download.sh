#!/usr/bin/env bash
# Download the 16 pinned M3D Motion IWR6843AOP raw-ADC captures by exact ZIP
# byte ranges from Zenodo record 22811456 (CC-BY-4.0), without fetching the
# whole 3.71 GB dataset_260917.zip.
#
# 1. Fetch the record JSON and check id, license (cc-by-4.0), the single file
#    key, its size (3,712,631,577) and its Zenodo MD5 (provenance only).
# 2. Range-GET the last 64 KiB, parse the EOCD and require the pinned
#    central-directory offset/size/entry count and SHA-256 (the record
#    publishes no per-member checksums, so the CD is the pin).
# 3. Range-GET every conf_file.cfg, DCA1000 LogFile.csv and session legend,
#    inflate each and check its CRC-32 against the central directory.
# 4. Re-derive the selection (every capture whose conf_file.cfg has the exact
#    pinned profileCfg/chirpCfg/channel/ADC/LVDS lines and frameCfg
#    "0 2 L 0 100 1 0" with L in {48, 64}; complete DCA1000 log) and require
#    it to equal the pinned selection.tsv byte for byte.
# 5. Range-GET each selected .bin member (resumable: partial .part files are
#    continued with the next byte range), then inflate it fully and check the
#    DEFLATE boundary, size, CRC-32, size % 1088 == 0, every 64-byte HSI chirp
#    header equal to the pinned header (magic 0x0CDA0ADC0CDA0ADC), and that
#    the payload is not degenerate.
# Every 206 response must carry the exact requested Content-Range against the
# pinned archive size. Re-runs reuse validated files; FORCE_DOWNLOAD=1 starts over.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_m3d_iwr6843_radar_adc_i16"
API_URL="https://zenodo.org/api/records/22811456"
ZIP_URL="https://zenodo.org/api/records/22811456/files/dataset_260917.zip/content"
ZIP_SIZE=3712631577
TAIL_BYTES=65536
DL="$DATA_ROOT/downloads/$DATASET_ID"
META="$DL/meta"
RANGES="$DL/ranges"
TMP="$DL/tmp"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/m3d_tool.py"
PINNED_SELECTION="$RECIPE_DIR/selection.tsv"

mkdir -p "$DL" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$META" "$RANGES" "$TMP" "$DL/record.json" "$DL/tail.bin" "$DL/cd.tsv" "$DL/derived_selection.tsv"
fi
mkdir -p "$META" "$RANGES" "$TMP"

# fetch_range URL START END OUT: exact byte range into OUT, resumable via OUT.part.
fetch_range() {
  local url="$1" start="$2" end="$3" out="$4"
  local part="$out.part" hdr="$out.hdr"
  local total=$((end - start + 1)) have from rc status cr attempt
  for attempt in $(seq 1 40); do
    have=0
    [ -f "$part" ] && have="$(stat -c%s "$part")"
    if [ "$have" -eq "$total" ]; then break; fi
    if [ "$have" -gt "$total" ]; then
      echo "WARN: $part larger than range; restarting it"
      rm -f "$part"
      have=0
    fi
    from=$((start + have))
    : > "$hdr"
    set +e
    curl -sS -fL --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --max-filesize $((total - have + 1)) -r "$from-$end" -D "$hdr" "$url" >> "$part"
    rc=$?
    set -e
    status="$(grep -i '^HTTP/' "$hdr" | tail -n 1 | awk '{print $2}' | tr -d '\r')"
    cr="$(grep -i '^content-range:' "$hdr" | tail -n 1 | awk '{print $2" "$3}' | tr -d '\r')"
    if [ "$status" != "206" ] || [ "$cr" != "bytes $from-$end/$ZIP_SIZE" ]; then
      echo "WARN: attempt $attempt bad response status='$status' content-range='$cr' rc=$rc; truncating to $have"
      truncate -s "$have" "$part"
      sleep $((attempt < 6 ? attempt * 5 : 30))
      continue
    fi
    if [ "$rc" -ne 0 ]; then
      echo "WARN: attempt $attempt curl rc=$rc at $(stat -c%s "$part")/$total bytes; resuming"
      sleep 5
    fi
  done
  have="$(stat -c%s "$part" 2>/dev/null || echo 0)"
  if [ "$have" -ne "$total" ]; then
    echo "FATAL: $out incomplete ($have/$total bytes)" >&2
    return 1
  fi
  mv -f "$part" "$out"
  rm -f "$hdr"
}

# 1. Record identity, license and file inventory.
curl -sS -fL --retry 5 --retry-delay 5 --max-time 300 -o "$DL/record.json.tmp" "$API_URL"
mv -f "$DL/record.json.tmp" "$DL/record.json"
python3 "$TOOL" check-record --record "$DL/record.json"

# 2. Archive tail -> pinned central directory.
TAIL_START=$((ZIP_SIZE - TAIL_BYTES))
rm -f "$DL/tail.bin"
fetch_range "$ZIP_URL" "$TAIL_START" "$((ZIP_SIZE - 1))" "$DL/tail.bin"
python3 "$TOOL" parse-cd --tail "$DL/tail.bin" --tail-start "$TAIL_START" --out "$DL/cd.tsv"

# 3. Small metadata members (configs, DCA1000 logs, legends).
small_fetched=0
small_cached=0
while IFS=$'\t' read -r name start end lname; do
  if [ -s "$META/$lname" ]; then
    small_cached=$((small_cached + 1))
    continue
  fi
  rm -f "$TMP/small.range"
  fetch_range "$ZIP_URL" "$start" "$end" "$TMP/small.range"
  python3 "$TOOL" extract-small --cd "$DL/cd.tsv" --name "$name" --range-file "$TMP/small.range" \
    --out "$META/$lname.tmp"
  mv -f "$META/$lname.tmp" "$META/$lname"
  rm -f "$TMP/small.range"
  small_fetched=$((small_fetched + 1))
done < <(python3 "$TOOL" small-list --cd "$DL/cd.tsv")
echo "metadata members fetched=$small_fetched cached=$small_cached"

# 4. Deterministic selection must equal the pinned table.
python3 "$TOOL" derive --cd "$DL/cd.tsv" --meta-dir "$META" --out "$DL/derived_selection.tsv"
python3 "$TOOL" compare --derived "$DL/derived_selection.tsv" --pinned "$PINNED_SELECTION"

# 5. Capture members: exact ranges, fully validated.
fetched=0
cached=0
expected_keys=""
while IFS=$'\t' read -r key start end; do
  expected_keys="$expected_keys $key.zipmember"
  out="$RANGES/$key.zipmember"
  if [ -s "$out" ] && [ "$(stat -c%s "$out")" -eq $((end - start + 1)) ]; then
    cached=$((cached + 1))
  else
    rm -f "$out"
    fetch_range "$ZIP_URL" "$start" "$end" "$out.new"
    mv -f "$out.new" "$out"
    fetched=$((fetched + 1))
  fi
  if ! python3 "$TOOL" check-bin --selection "$PINNED_SELECTION" --key "$key" --range-file "$out"; then
    echo "FATAL: $key failed validation; removing it so a re-run fetches it again" >&2
    rm -f "$out"
    exit 1
  fi
done < <(python3 "$TOOL" bin-list --selection "$PINNED_SELECTION")
for f in "$RANGES"/*; do
  [ -e "$f" ] || continue
  case " $expected_keys " in
    *" $(basename "$f") "*) ;;
    *) echo "removing unpinned $(basename "$f")"; rm -f "$f" ;;
  esac
done
rmdir "$TMP" 2>/dev/null || true
echo "captures fetched=$fetched cached=$cached"
count="$(find "$RANGES" -maxdepth 1 -name '*.zipmember' | wc -l | tr -d ' ')"
if [ "$count" != "16" ]; then
  echo "FATAL: expected 16 capture ranges, found $count" >&2
  exit 1
fi
du -sb "$DL" | awk '{print "download_dir_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
