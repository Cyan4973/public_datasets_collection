#!/usr/bin/env bash
# Download the 51 pinned USDA NASS CDL 2021 confidence-layer COGs listed in
# sources.tsv from the Microsoft Planetary Computer usda-cdl container.
#
# Access: the container needs a short-lived read-only SAS signature that the
# Planetary Computer issues anonymously (no account, key, or login) at
# /api/sas/v1/token/landcoverdata/usda-cdl. Only the unsigned hrefs are pinned;
# the signature is requested at run time, stored under a mode-700 directory,
# refreshed every 20 minutes (and after any failed transfer), and never printed.
#
# Only the 'confidence' asset of cropland_2021_* items is fetched; the
# cropland class codes, cultivated, frequency and per-crop assets never are.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mpc_usda_cdl_confidence_u8"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/rasters"
SAS_DIR="$DOWNLOAD_DIR/sas"
SOURCES="$RECIPE_DIR/sources.tsv"
mkdir -p "$LOG_DIR" "$RASTER_DIR" "$SAS_DIR"
chmod 700 "$SAS_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets/1.0 ($DATASET_ID)"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/landcoverdata/usda-cdl"
SAS_JSON="$SAS_DIR/landcoverdata_usda-cdl.json"
EXPECTED_FILES=51
EXPECTED_BYTES=364924830

# ---- validate the pinned plan before any network access -------------------
python3 - "$SOURCES" "$EXPECTED_FILES" "$EXPECTED_BYTES" <<'PY'
import csv, re, sys
path, n_expected, bytes_expected = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rows = list(csv.DictReader(open(path, encoding="utf-8", newline=""), delimiter="\t"))
assert len(rows) == n_expected, f"plan rows {len(rows)} != {n_expected}"
assert sum(int(r["size_bytes"]) for r in rows) == bytes_expected, "plan byte total mismatch"
assert len({r["item_id"] for r in rows}) == n_expected, "duplicate item IDs in plan"
regions = {"corn_belt", "plains_wheat", "northern_plains", "delta", "central_valley", "palouse_columbia", "southeast"}
assert {r["region"] for r in rows} == regions, "unexpected region set"
for r in rows:
    m = re.fullmatch(r"cropland_2021_(-?\d+)_(\d+)_90000", r["item_id"])
    assert m, r["item_id"]
    x, y = m.groups()
    want = (f"https://landcoverdata.blob.core.windows.net/usda-cdl/tiles/{x}/"
            f"2021_30m_confidence_layer_{x}_{y}_90000.tif")
    assert r["url"] == want, f"unexpected URL for {r['item_id']}"
    assert re.fullmatch(r"[0-9a-f]{32}", r["content_md5_hex"]), r["item_id"]
print(f"plan_ok rows={len(rows)} regions={len(regions)} bytes={bytes_expected}")
PY

sas_query=""
refresh_sas() {
  local age=999999
  if [ -s "$SAS_JSON" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$SAS_JSON") ))
  fi
  if [ "$age" -gt 1200 ] || [ -z "$sas_query" ]; then
    if [ "$age" -gt 1200 ]; then
      echo "request_sas_signature account=landcoverdata container=usda-cdl"
      curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 \
        --connect-timeout 30 --max-time 60 -A "$UA" -o "$SAS_JSON.tmp" "$SAS_ENDPOINT"
      chmod 600 "$SAS_JSON.tmp"
      mv "$SAS_JSON.tmp" "$SAS_JSON"
    fi
    sas_query="$(python3 -c 'import json,sys; t=str(json.load(open(sys.argv[1])).get("token","")).lstrip("?"); print(t) if t else sys.exit("SAS response has no signature")' "$SAS_JSON")"
  fi
}

file_ok() {
  # file_ok PATH SIZE MD5HEX -> 0 when size, MD5 and TIFF magic match the pin
  local path="$1" size="$2" md5="$3"
  [ -f "$path" ] || return 1
  [ "$(stat -c %s "$path")" = "$size" ] || return 1
  [ "$(md5sum "$path" | cut -d ' ' -f1)" = "$md5" ] || return 1
  [ "$(od -An -tx1 -N4 "$path" | tr -d ' \n')" = "49492a00" ] || return 1
}

fetched=0
cached=0
while IFS=$'\t' read -r region item_id lon_min lat_min lon_max lat_max screen_zero screen_100 size_bytes md5_hex url; do
  [ "$region" != "region" ] || continue
  out="$RASTER_DIR/$(basename "$url")"
  if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && file_ok "$out" "$size_bytes" "$md5_hex"; then
    cached=$((cached + 1))
    echo "cache_hit item=$item_id bytes=$size_bytes"
    continue
  fi
  rm -f "$out"
  part="$out.part"
  for attempt in 1 2 3 4; do
    part_size=0
    [ -f "$part" ] && part_size="$(stat -c %s "$part")"
    if [ "$part_size" -gt "$size_bytes" ]; then
      rm -f "$part"
      part_size=0
    fi
    if [ "$part_size" -lt "$size_bytes" ]; then
      refresh_sas
      echo "fetch item=$item_id region=$region bytes=$size_bytes resume_from=$part_size attempt=$attempt"
      if ! curl --globoff -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 -A "$UA" \
        -sS -o "$part" "${url}?${sas_query}"; then
        echo "WARN: curl exited non-zero item=$item_id attempt=$attempt (partial kept; forcing a fresh SAS signature)" >&2
        rm -f "$SAS_JSON"
        sas_query=""
        sleep $((attempt * 15))
      fi
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
python3 "$RECIPE_DIR/scripts/cdl_cog.py" --check-headers "$SOURCES" "$RASTER_DIR"

# ---- receipts (sha256) for build provenance --------------------------------
receipts="$DOWNLOAD_DIR/download_receipts.tsv"
printf 'item_id\tsize_bytes\tmd5\tsha256\n' > "$receipts.tmp"
total=0
count=0
while IFS=$'\t' read -r region item_id lon_min lat_min lon_max lat_max screen_zero screen_100 size_bytes md5_hex url; do
  [ "$region" != "region" ] || continue
  out="$RASTER_DIR/$(basename "$url")"
  printf '%s\t%s\t%s\t%s\n' "$item_id" "$size_bytes" "$md5_hex" "$(sha256sum "$out" | cut -d ' ' -f1)" >> "$receipts.tmp"
  total=$((total + size_bytes))
  count=$((count + 1))
done < "$SOURCES"
mv "$receipts.tmp" "$receipts"

present="$(find "$RASTER_DIR" -maxdepth 1 -type f -name '2021_30m_confidence_layer_*.tif' | wc -l | tr -d ' ')"
if [ "$count" -ne "$EXPECTED_FILES" ] || [ "$present" -ne "$EXPECTED_FILES" ] || [ "$total" -ne "$EXPECTED_BYTES" ]; then
  echo "FATAL: expected $EXPECTED_FILES files / $EXPECTED_BYTES bytes; plan=$count present=$present bytes=$total" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count fetched=$fetched cached=$cached bytes=$total"
