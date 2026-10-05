#!/usr/bin/env bash
# Download twelve pinned GOES-18 ABI L2 CMI band-13 full-disk COGs from the
# Microsoft Planetary Computer `goes-cmi` collection (NOAA NODD data).
#
# Network I/O is curl only. Python is used only to parse the anonymous
# Planetary Computer SAS response and to validate the downloaded TIFFs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_goes18_abi_cmi_c13_fulldisk_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RASTER_DIR="$DOWNLOAD_DIR/cogs"
mkdir -p "$LOG_DIR" "$RASTER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="${PC_UA:-openzl-public-datasets/1.0}"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/goeseuwest/noaa-goes-cogs"
VALIDATOR="$RECIPE_DIR/scripts/goes_cog.py"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
EXPECTED_FILES=12
EXPECTED_TOTAL_BYTES=431073260

# One GOES-18 Mode-6 full-disk scan per month: the 20:00 UTC slot on the 15th,
# October 2025 through September 2026. Item IDs, hrefs, Content-Length and
# Azure Content-MD5 (base64) were resolved by discover.sh on 2026-10-05.
cat > "$PLAN.tmp" <<'EOF'
month	scan_start_utc	scan_end_utc	item_id	source_netcdf	url	size_bytes	content_md5_b64
2025-10	2025-10-15T20:00:20.800000Z	2025-10-15T20:09:51.600000Z	OR_ABI-L2-F-M6_G18_s20252882000208	OR_ABI-L2-MCMIPF-M6_G18_s20252882000208_e20252882009516_c20252882009583.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2025/288/20/OR_ABI-L2-MCMIPF-M6_G18_s20252882000208_e20252882009516_c20252882009583_CMI_C13.tif	35265395	yT96na8z3H5jxzW87OQR/A==
2025-11	2025-11-15T20:00:21.300000Z	2025-11-15T20:09:52.800000Z	OR_ABI-L2-F-M6_G18_s20253192000213	OR_ABI-L2-MCMIPF-M6_G18_s20253192000213_e20253192009528_c20253192009588.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2025/319/20/OR_ABI-L2-MCMIPF-M6_G18_s20253192000213_e20253192009528_c20253192009588_CMI_C13.tif	35676899	2ShjHPm7Jp5d+LeFdbN7fQ==
2025-12	2025-12-15T20:00:21.500000Z	2025-12-15T20:09:52.900000Z	OR_ABI-L2-F-M6_G18_s20253492000215	OR_ABI-L2-MCMIPF-M6_G18_s20253492000215_e20253492009529_c20253492009587.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2025/349/20/OR_ABI-L2-MCMIPF-M6_G18_s20253492000215_e20253492009529_c20253492009587_CMI_C13.tif	35930429	Xp2k6+ZnIBMKnTkbbdUWlQ==
2026-01	2026-01-15T20:00:22.100000Z	2026-01-15T20:09:52.900000Z	OR_ABI-L2-F-M6_G18_s20260152000221	OR_ABI-L2-MCMIPF-M6_G18_s20260152000221_e20260152009529_c20260152010004.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/015/20/OR_ABI-L2-MCMIPF-M6_G18_s20260152000221_e20260152009529_c20260152010004_CMI_C13.tif	35119545	KGYRH/VN4NfiBf4zJcAkyA==
2026-02	2026-02-15T20:00:22.600000Z	2026-02-15T20:09:54.100000Z	OR_ABI-L2-F-M6_G18_s20260462000226	OR_ABI-L2-MCMIPF-M6_G18_s20260462000226_e20260462009541_c20260462010005.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/046/20/OR_ABI-L2-MCMIPF-M6_G18_s20260462000226_e20260462009541_c20260462010005_CMI_C13.tif	35046735	HOfIBnHcoS9nFBqpocQmNg==
2026-03	2026-03-15T20:00:22.600000Z	2026-03-15T20:09:54.600000Z	OR_ABI-L2-F-M6_G18_s20260742000226	OR_ABI-L2-MCMIPF-M6_G18_s20260742000226_e20260742009546_c20260742010004.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/074/20/OR_ABI-L2-MCMIPF-M6_G18_s20260742000226_e20260742009546_c20260742010004_CMI_C13.tif	34567256	zIraFCPd1lifliKMagmeVw==
2026-04	2026-04-15T20:00:20.200000Z	2026-04-15T20:09:52.200000Z	OR_ABI-L2-F-M6_G18_s20261052000202	OR_ABI-L2-MCMIPF-M6_G18_s20261052000202_e20261052009522_c20261052009585.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/105/20/OR_ABI-L2-MCMIPF-M6_G18_s20261052000202_e20261052009522_c20261052009585_CMI_C13.tif	36596117	9zMr/a3/gM9qNGu5q8muNg==
2026-05	2026-05-15T20:00:21.200000Z	2026-05-15T20:09:52Z	OR_ABI-L2-F-M6_G18_s20261352000212	OR_ABI-L2-MCMIPF-M6_G18_s20261352000212_e20261352009520_c20261352010002.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/135/20/OR_ABI-L2-MCMIPF-M6_G18_s20261352000212_e20261352009520_c20261352010002_CMI_C13.tif	36259462	YVJ8Z1xYdOc5bDlyrFKvbg==
2026-06	2026-06-15T20:00:22.500000Z	2026-06-15T20:09:54.800000Z	OR_ABI-L2-F-M6_G18_s20261662000225	OR_ABI-L2-MCMIPF-M6_G18_s20261662000225_e20261662009548_c20261662010000.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/166/20/OR_ABI-L2-MCMIPF-M6_G18_s20261662000225_e20261662009548_c20261662010000_CMI_C13.tif	35812486	wSvnlo/HAnNBUoAeccrBgQ==
2026-07	2026-07-15T20:00:22.700000Z	2026-07-15T20:09:54.700000Z	OR_ABI-L2-F-M6_G18_s20261962000227	OR_ABI-L2-MCMIPF-M6_G18_s20261962000227_e20261962009547_c20261962010019.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/196/20/OR_ABI-L2-MCMIPF-M6_G18_s20261962000227_e20261962009547_c20261962010019_CMI_C13.tif	36558746	Ud7wzjHe7Lc0I68Qgu0gFg==
2026-08	2026-08-15T20:00:22.500000Z	2026-08-15T20:09:53.400000Z	OR_ABI-L2-F-M6_G18_s20262272000225	OR_ABI-L2-MCMIPF-M6_G18_s20262272000225_e20262272009534_c20262272010025.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/227/20/OR_ABI-L2-MCMIPF-M6_G18_s20262272000225_e20262272009534_c20262272010025_CMI_C13.tif	37940280	Pn3lgN7wLzuVK4QLWYO1Gg==
2026-09	2026-09-15T20:00:20.600000Z	2026-09-15T20:09:52Z	OR_ABI-L2-F-M6_G18_s20262582000206	OR_ABI-L2-MCMIPF-M6_G18_s20262582000206_e20262582009520_c20262582009596.nc	https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/2026/258/20/OR_ABI-L2-MCMIPF-M6_G18_s20262582000206_e20262582009520_c20262582009596_CMI_C13.tif	36299910	aB3R+56iPbq+q15PA1L1Yw==
EOF
mv "$PLAN.tmp" "$PLAN"

python3 - "$PLAN" "$EXPECTED_FILES" "$EXPECTED_TOTAL_BYTES" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8"), delimiter="\t"))
if len(rows) != int(sys.argv[2]):
    raise SystemExit(f"FATAL: plan has {len(rows)} rows, expected {sys.argv[2]}")
if len({r["item_id"] for r in rows}) != len(rows) or len({r["month"] for r in rows}) != len(rows):
    raise SystemExit("FATAL: duplicate item or month in plan")
total = sum(int(r["size_bytes"]) for r in rows)
if total != int(sys.argv[3]):
    raise SystemExit(f"FATAL: plan bytes {total} != {sys.argv[3]}")
print(f"plan ok rows={len(rows)} bytes={total}")
PY

fsize() {
  if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi
}

# md5_b64 <file>: Azure Content-MD5 representation (base64 of the raw digest).
md5_b64() {
  python3 - "$1" <<'PY'
import base64, hashlib, sys
h = hashlib.md5()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
print(base64.b64encode(h.digest()).decode())
PY
}

# valid_cog <file> <size> <md5_b64> <source_netcdf>: exact size, exact MD5,
# and the expected TIFF/GDAL structure of the CMI_C13 primary grid.
valid_cog() {
  local path="$1" size="$2" md5="$3" netcdf="$4" actual_size actual_md5
  actual_size="$(wc -c < "$path" | tr -d ' ')"
  if [ "$actual_size" != "$size" ]; then
    echo "size mismatch path=$path bytes=$actual_size expected=$size" >&2
    return 1
  fi
  actual_md5="$(md5_b64 "$path")"
  if [ "$actual_md5" != "$md5" ]; then
    echo "md5 mismatch path=$path md5=$actual_md5 expected=$md5" >&2
    return 1
  fi
  python3 "$VALIDATOR" validate "$path" "$netcdf" > "$path.validation.json"
}

SAS_QS=""
get_sas() {
  # Anonymous, short-lived read SAS for the public noaa-goes-cogs container.
  # The no-SAS blob request returns 404/409; no account or login is involved.
  local response
  response="$(curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 \
    --connect-timeout 30 --max-time 60 -A "$UA" "$SAS_ENDPOINT")"
  SAS_QS="$(printf '%s' "$response" | python3 -c '
import json, sys
doc = json.load(sys.stdin)
value = str(doc.get("token", "")).lstrip("?")
if not value or "sig=" not in value:
    raise SystemExit("Planetary Computer SAS response has no signature")
print(value)
')"
  echo "sas_ok container=goeseuwest/noaa-goes-cogs expiry=$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("msft:expiry",""))')"
}

downloaded=0
while IFS=$'\t' read -r month start_utc end_utc item_id netcdf url size md5; do
  [ "$month" != "month" ] || continue
  out="$RASTER_DIR/${netcdf%.nc}_CMI_C13.tif"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && valid_cog "$out" "$size" "$md5" "$netcdf"; then
    echo "cache_hit month=$month item=$item_id bytes=$size"
    downloaded=$((downloaded + 1))
    continue
  fi
  rm -f "$out"
  if [ -z "$SAS_QS" ]; then
    get_sas
  fi
  part="$out.part"
  if [ "$(fsize "$part")" -gt "$size" ]; then
    echo "discarding oversized partial file $part"
    rm -f "$part"
  fi
  echo "fetch month=$month item=$item_id start=$start_utc bytes=$size resume_from=$(fsize "$part") url=$url"
  attempt=1
  until [ "$(fsize "$part")" = "$size" ] || \
      curl --globoff -fsSL -C - --retry 10 --retry-all-errors --retry-delay 5 \
      --connect-timeout 30 --speed-limit 1024 --speed-time 120 -A "$UA" \
      -o "$part" "${url}?${SAS_QS}"; do
    if [ "$attempt" -ge 3 ]; then
      echo "FATAL: curl failed repeatedly for item=$item_id" >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    echo "retrying item=$item_id with a fresh SAS (attempt $attempt)"
    get_sas
    sleep 5
  done
  if ! valid_cog "$part" "$size" "$md5" "$netcdf"; then
    echo "FATAL: downloaded payload failed validation item=$item_id" >&2
    rm -f "$part" "$part.validation.json"
    exit 1
  fi
  mv "$part.validation.json" "$out.validation.json"
  mv "$part" "$out"
  echo "validated month=$month item=$item_id bytes=$size md5=$md5"
  downloaded=$((downloaded + 1))
done < "$PLAN"
SAS_QS=""

found="$(find "$RASTER_DIR" -maxdepth 1 -type f -name 'OR_ABI-L2-MCMIPF-M6_G18_*_CMI_C13.tif' | wc -l | tr -d ' ')"
if [ "$downloaded" -ne "$EXPECTED_FILES" ] || [ "$found" -ne "$EXPECTED_FILES" ]; then
  echo "FATAL: expected $EXPECTED_FILES validated COGs, downloaded=$downloaded found=$found" >&2
  exit 1
fi
total="$(find "$RASTER_DIR" -maxdepth 1 -type f -name '*_CMI_C13.tif' -printf '%s\n' | awk '{s+=$1} END {print s}')"
if [ "$total" -ne "$EXPECTED_TOTAL_BYTES" ]; then
  echo "FATAL: downloaded bytes $total != $EXPECTED_TOTAL_BYTES" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$found bytes=$total"
