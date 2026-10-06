#!/usr/bin/env bash
# Download the 48 pinned MOD13A1.061 Terra NDVI COGs listed in sources.tsv
# from the Microsoft Planetary Computer MODIS 6.1 COG container.
#
# Access: the container requires a short-lived read-only SAS signature that
# the Planetary Computer issues anonymously (no account, key, or login) at
# /api/sas/v1/token/modiseuwest/modis-061-cogs. It is stored under a mode-700
# directory, refreshed every 20 minutes, and never printed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mpc_modis_mod13a1_ndvi_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/rasters"
SAS_DIR="$DOWNLOAD_DIR/sas"
SOURCES="$RECIPE_DIR/sources.tsv"
mkdir -p "$LOG_DIR" "$RASTER_DIR" "$SAS_DIR"
chmod 700 "$SAS_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets/1.0 ($DATASET_ID)"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
SAS_JSON="$SAS_DIR/modiseuwest_modis-061-cogs.json"
EXPECTED_FILES=48
EXPECTED_BYTES=575539183

# ---- validate the pinned plan before any network access -------------------
python3 - "$SOURCES" "$EXPECTED_FILES" "$EXPECTED_BYTES" <<'PY'
import csv, re, sys
path, n_expected, bytes_expected = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rows = list(csv.DictReader(open(path, encoding="utf-8", newline=""), delimiter="\t"))
assert len(rows) == n_expected, f"plan rows {len(rows)} != {n_expected}"
assert sum(int(r["size_bytes"]) for r in rows) == bytes_expected, "plan byte total mismatch"
tiles = {r["tile"] for r in rows}
assert len(tiles) == 24, f"expected 24 tiles, got {len(tiles)}"
pairs = {(r["tile"], r["day_of_year"]) for r in rows}
assert pairs == {(t, d) for t in tiles for d in ("017", "193")}, "plan is not 24 tiles x DOY 017/193"
for r in rows:
    item = r["item_id"]
    assert re.fullmatch(rf"MOD13A1\.A2024{r['day_of_year']}\.{r['tile']}\.061\.\d{{13}}", item), item
    h, v = r["tile"][1:3], r["tile"][4:6]
    want = (f"https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD13A1/{h}/{v}/"
            f"2024{r['day_of_year']}/{item}_500m_16_days_NDVI.tif")
    assert r["url"] == want, f"unexpected URL for {item}"
    assert re.fullmatch(r"[0-9a-f]{32}", r["content_md5_hex"]), item
print(f"plan_ok rows={len(rows)} tiles={len(tiles)} bytes={bytes_expected}")
PY

sas_query=""
refresh_sas() {
  local age=999999
  if [ -s "$SAS_JSON" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$SAS_JSON") ))
  fi
  if [ "$age" -gt 1200 ] || [ -z "$sas_query" ]; then
    if [ "$age" -gt 1200 ]; then
      echo "request_sas_signature account=modiseuwest container=modis-061-cogs"
      curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 \
        --connect-timeout 30 --max-time 60 -A "$UA" -o "$SAS_JSON.tmp" "$SAS_ENDPOINT"
      chmod 600 "$SAS_JSON.tmp"
      mv "$SAS_JSON.tmp" "$SAS_JSON"
    fi
    sas_query="$(python3 -c 'import json,sys; t=str(json.load(open(sys.argv[1])).get("token","")).lstrip("?"); print(t) if t else sys.exit("SAS response has no signature")' "$SAS_JSON")"
  fi
}

file_ok() {
  # file_ok PATH SIZE MD5HEX -> 0 when size and MD5 both match the pin
  local path="$1" size="$2" md5="$3"
  [ -f "$path" ] || return 1
  [ "$(stat -c %s "$path")" = "$size" ] || return 1
  [ "$(md5sum "$path" | cut -d ' ' -f1)" = "$md5" ] || return 1
  [ "$(od -An -tx1 -N4 "$path" | tr -d ' \n')" = "49492a00" ] || return 1
}

fetched=0
cached=0
while IFS=$'\t' read -r continent area tile doy start_date end_date item_id size_bytes md5_hex url; do
  [ "$continent" != "continent" ] || continue
  out="$RASTER_DIR/${item_id}_500m_16_days_NDVI.tif"
  if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && file_ok "$out" "$size_bytes" "$md5_hex"; then
    cached=$((cached + 1))
    echo "cache_hit item=$item_id bytes=$size_bytes"
    continue
  fi
  rm -f "$out"
  part="$out.part"
  for attempt in 1 2 3; do
    part_size=0
    [ -f "$part" ] && part_size="$(stat -c %s "$part")"
    if [ "$part_size" -gt "$size_bytes" ]; then
      rm -f "$part"
      part_size=0
    fi
    if [ "$part_size" -lt "$size_bytes" ]; then
      refresh_sas
      echo "fetch item=$item_id tile=$tile doy=$doy area=$area bytes=$size_bytes resume_from=$part_size attempt=$attempt"
      curl --globoff -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 -A "$UA" \
        -sS -o "$part" "${url}?${sas_query}" \
        || echo "WARN: curl exited non-zero item=$item_id attempt=$attempt (partial kept for resume)" >&2
      part_size=0
      [ -f "$part" ] && part_size="$(stat -c %s "$part")"
    fi
    if [ "$part_size" -eq "$size_bytes" ]; then
      if file_ok "$part" "$size_bytes" "$md5_hex"; then
        mv "$part" "$out"
        break
      fi
      echo "WARN: complete file failed MD5/TIFF check item=$item_id attempt=$attempt; discarding" >&2
      rm -f "$part"
    fi
  done
  if ! file_ok "$out" "$size_bytes" "$md5_hex"; then
    echo "FATAL: could not obtain a valid copy of item=$item_id (rerun resumes any partial)" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
  echo "validated item=$item_id bytes=$size_bytes md5=$md5_hex"
done < "$SOURCES"
sas_query=""

# ---- semantic header validation of every pinned COG -----------------------
python3 "$RECIPE_DIR/scripts/mod13a1_cog.py" --check-headers "$SOURCES" "$RASTER_DIR"

# ---- receipts (sha256) for build provenance --------------------------------
receipts="$DOWNLOAD_DIR/download_receipts.tsv"
printf 'item_id\tsize_bytes\tmd5\tsha256\n' > "$receipts.tmp"
total=0
count=0
while IFS=$'\t' read -r continent area tile doy start_date end_date item_id size_bytes md5_hex url; do
  [ "$continent" != "continent" ] || continue
  out="$RASTER_DIR/${item_id}_500m_16_days_NDVI.tif"
  printf '%s\t%s\t%s\t%s\n' "$item_id" "$size_bytes" "$md5_hex" "$(sha256sum "$out" | cut -d ' ' -f1)" >> "$receipts.tmp"
  total=$((total + size_bytes))
  count=$((count + 1))
done < "$SOURCES"
mv "$receipts.tmp" "$receipts"

present="$(find "$RASTER_DIR" -maxdepth 1 -type f -name 'MOD13A1.*_500m_16_days_NDVI.tif' | wc -l | tr -d ' ')"
if [ "$count" -ne "$EXPECTED_FILES" ] || [ "$present" -ne "$EXPECTED_FILES" ] || [ "$total" -ne "$EXPECTED_BYTES" ]; then
  echo "FATAL: expected $EXPECTED_FILES files / $EXPECTED_BYTES bytes; plan=$count present=$present bytes=$total" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count fetched=$fetched cached=$cached bytes=$total"
