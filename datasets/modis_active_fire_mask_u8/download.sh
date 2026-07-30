#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="modis_active_fire_mask_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/rasters"
TOKEN_DIR="$DOWNLOAD_DIR/tokens"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$RASTER_DIR" "$TOKEN_DIR"
chmod 700 "$TOKEN_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="${PC_UA:-openzl-public-datasets/1.0}"
SAS_URL="${PC_SAS_URL:-https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs}"
MIN_SOURCE_BYTES="${MODIS_FIRE_MIN_SOURCE_BYTES:-1024}"
MAX_SOURCE_BYTES="${MODIS_FIRE_MAX_SOURCE_BYTES:-5000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
TOKEN_FILE="$TOKEN_DIR/modiseuwest_modis-061-cogs.json"

cat > "$PLAN" <<'EOF'
region	date_utc	day_of_year	tile	item_id	url
western_north_america	2024-01-01	001	h08v05	MOD14A2.A2024001.h08v05.061.2024011144704	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/08/05/2024001/MOD14A2.A2024001.h08v05.061.2024011144704_FireMask.tif
western_north_america	2024-05-08	129	h08v05	MOD14A2.A2024129.h08v05.061.2024142132234	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/08/05/2024129/MOD14A2.A2024129.h08v05.061.2024142132234_FireMask.tif
western_north_america	2024-09-13	257	h08v05	MOD14A2.A2024257.h08v05.061.2024268121633	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/08/05/2024257/MOD14A2.A2024257.h08v05.061.2024268121633_FireMask.tif
amazon_basin	2024-01-01	001	h12v09	MOD14A2.A2024001.h12v09.061.2024011144620	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/12/09/2024001/MOD14A2.A2024001.h12v09.061.2024011144620_FireMask.tif
amazon_basin	2024-05-08	129	h12v09	MOD14A2.A2024129.h12v09.061.2024142132406	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/12/09/2024129/MOD14A2.A2024129.h12v09.061.2024142132406_FireMask.tif
amazon_basin	2024-09-13	257	h12v09	MOD14A2.A2024257.h12v09.061.2024268121404	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/12/09/2024257/MOD14A2.A2024257.h12v09.061.2024268121404_FireMask.tif
southern_africa	2024-01-01	001	h20v11	MOD14A2.A2024001.h20v11.061.2024011144119	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/20/11/2024001/MOD14A2.A2024001.h20v11.061.2024011144119_FireMask.tif
southern_africa	2024-05-08	129	h20v11	MOD14A2.A2024129.h20v11.061.2024142104313	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/20/11/2024129/MOD14A2.A2024129.h20v11.061.2024142104313_FireMask.tif
southern_africa	2024-09-13	257	h20v11	MOD14A2.A2024257.h20v11.061.2024268121743	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/20/11/2024257/MOD14A2.A2024257.h20v11.061.2024268121743_FireMask.tif
australia	2024-01-01	001	h30v11	MOD14A2.A2024001.h30v11.061.2024011144747	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/30/11/2024001/MOD14A2.A2024001.h30v11.061.2024011144747_FireMask.tif
australia	2024-05-08	129	h30v11	MOD14A2.A2024129.h30v11.061.2024142133744	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/30/11/2024129/MOD14A2.A2024129.h30v11.061.2024142133744_FireMask.tif
australia	2024-09-13	257	h30v11	MOD14A2.A2024257.h30v11.061.2024268121655	https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD14A2/30/11/2024257/MOD14A2.A2024257.h30v11.061.2024268121655_FireMask.tif
EOF

if [ "$(($(wc -l < "$PLAN") - 1))" -ne 12 ]; then
  echo "FATAL: download plan must contain exactly 12 assets" >&2
  exit 1
fi

echo "request_access_token account=modiseuwest container=modis-061-cogs"
curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 \
  --connect-timeout 30 --max-time 60 -A "$UA" \
  -o "$TOKEN_FILE.tmp" "$SAS_URL"
chmod 600 "$TOKEN_FILE.tmp"
mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"
token="$(python3 - "$TOKEN_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    token = str(json.load(fh).get("token", ""))
if not token:
    raise SystemExit("Planetary Computer token response has no token")
print(token.lstrip("?"))
PY
)"

validate_tiff() {
  local path="$1"
  local size magic
  size="$(wc -c < "$path" | tr -d ' ')"
  if [ "$size" -lt "$MIN_SOURCE_BYTES" ] || [ "$size" -gt "$MAX_SOURCE_BYTES" ]; then
    echo "FATAL: source size outside bounds path=$path bytes=$size" >&2
    return 1
  fi
  magic="$(od -An -tx1 -N4 "$path" | tr -d ' \n')"
  case "$magic" in
    49492a00|4d4d002a|49492b00|4d4d002b) ;;
    *) echo "FATAL: invalid TIFF signature path=$path magic=$magic" >&2; return 1 ;;
  esac
}

while IFS=$'\t' read -r region date_utc day_of_year tile item_id url; do
  [ "$region" != "region" ] || continue
  filename="${item_id}_FireMask.tif"
  out="$RASTER_DIR/$filename"
  if [ -s "$out" ] && validate_tiff "$out" && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit region=$region date=$date_utc tile=$tile file=$filename bytes=$(wc -c < "$out" | tr -d ' ')"
    continue
  fi
  rm -f "$out.part"
  echo "fetch region=$region date=$date_utc doy=$day_of_year tile=$tile item=$item_id url=$url"
  curl --globoff -fL --retry 5 --retry-all-errors --retry-delay 3 \
    --connect-timeout 30 --speed-limit 512 --speed-time 120 -A "$UA" \
    -o "$out.part" "${url}?${token}"
  validate_tiff "$out.part"
  mv "$out.part" "$out"
  echo "validated item=$item_id bytes=$(wc -c < "$out" | tr -d ' ') sha256=$(sha256sum "$out" | cut -d ' ' -f1)"
done < "$PLAN"

token=''

downloaded="$(find "$RASTER_DIR" -maxdepth 1 -type f -name 'MOD14A2.*_FireMask.tif' | wc -l | tr -d ' ')"
if [ "$downloaded" -ne 12 ]; then
  echo "FATAL: expected exactly 12 downloaded rasters, found $downloaded" >&2
  exit 1
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$downloaded"
