#!/usr/bin/env bash
# Download the 31 pinned Global Wind Atlas v4 country rasters of mean wind
# speed at 100 m (country_tifs_v4/{ISO3}_wind-speed_100m.tif) from the GWA
# CDN, one file at a time.
#
# Rights hygiene: GWA's GIS page says "This API service is not to be used for
# bulk downloads of all countries or datasets." This recipe fetches a small
# fixed list (31 small/medium countries, one layer, one height), sequentially,
# with a pause between files, and never enumerates countries or layers.
#
# Network I/O is curl only. Python only validates the downloaded TIFFs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwa_v4_country_wind_speed_100m_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TIF_DIR="$DOWNLOAD_DIR/country_tifs_v4"
mkdir -p "$LOG_DIR" "$TIF_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

UA="${GWA_UA:-openzl-public-datasets/1.0 (pinned list of 31 country files)}"
COUNTRIES="$RECIPE_DIR/countries.tsv"
TIFF="$RECIPE_DIR/scripts/gwa_tiff.py"
PLAN="$DOWNLOAD_DIR/download_plan.txt"
EXPECTED_FILES=31
EXPECTED_TOTAL_BYTES=176707851

# Flatten the pinned table (whitespace-free fields) and check its pins and
# totals before any network access. Every file has a pinned sha256 (from the
# 2026-10-06 download) in addition to its size and ETag/MD5.
python3 - "$COUNTRIES" "$EXPECTED_FILES" "$EXPECTED_TOTAL_BYTES" > "$PLAN.tmp" <<'PY'
import csv, re, sys
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8"), delimiter="\t"))
if len(rows) != int(sys.argv[2]):
    raise SystemExit(f"FATAL: countries.tsv has {len(rows)} rows, expected {sys.argv[2]}")
if len({r["iso3"] for r in rows}) != len(rows):
    raise SystemExit("FATAL: duplicate iso3 in countries.tsv")
total = 0
for r in rows:
    iso = r["iso3"]
    if not re.fullmatch(r"[A-Z]{3}", iso):
        raise SystemExit(f"FATAL: bad iso3 {iso!r}")
    if r["url"] != f"https://gwa.cdn.nazkamapps.com/country_tifs_v4/{iso}_wind-speed_100m.tif":
        raise SystemExit(f"FATAL: unexpected url for {iso}: {r['url']}")
    if not re.fullmatch(r"[0-9a-f]{32}", r["etag_md5"]):
        raise SystemExit(f"FATAL: {iso} etag is not a single-part MD5: {r['etag_md5']}")
    sha = r["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit(f"FATAL: {iso} missing or bad sha256 pin {sha!r}")
    total += int(r["size_bytes"])
    print(iso, r["url"], r["size_bytes"], r["etag_md5"], sha, r["width"], r["height"], r["tile_count"])
if total != int(sys.argv[3]):
    raise SystemExit(f"FATAL: pinned bytes {total} != {sys.argv[3]}")
print(f"plan ok files={len(rows)} bytes={total}", file=sys.stderr)
PY
mv "$PLAN.tmp" "$PLAN"

fsize() {
  if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi
}

# valid_tif <file> <size> <md5> <sha256> <width> <height> <tiles>: exact
# size, MD5 equal to the pinned S3 ETag, the pinned sha256, and the
# expected BigTIFF structure (float32, ZSTD, predictor 3, 512x512 tiles,
# GDAL_NODATA nan, EPSG:4326, 0.0025 deg pixels, overview chain) with the
# pinned IFD0 geometry. Writes <file>.validation.json.
valid_tif() {
  local path="$1" size="$2" md5="$3" sha="$4" width="$5" height="$6" tiles="$7" actual
  actual="$(fsize "$path")"
  if [ "$actual" != "$size" ]; then
    echo "size mismatch path=$path bytes=$actual expected=$size" >&2
    return 1
  fi
  actual="$(md5sum "$path" | cut -d' ' -f1)"
  if [ "$actual" != "$md5" ]; then
    echo "md5 mismatch path=$path md5=$actual expected_etag=$md5" >&2
    return 1
  fi
  actual="$(sha256sum "$path" | cut -d' ' -f1)"
  if [ "$actual" != "$sha" ]; then
    echo "sha256 mismatch path=$path sha256=$actual expected=$sha" >&2
    return 1
  fi
  python3 "$TIFF" validate "$path" > "$path.validation.json" || return 1
  python3 - "$path.validation.json" "$width" "$height" "$tiles" <<'PY' || return 1
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
want = {"width": int(sys.argv[2]), "height": int(sys.argv[3]), "tile_count": int(sys.argv[4])}
got = {k: doc[k] for k in want}
if got != want:
    raise SystemExit(f"geometry mismatch {got} != pinned {want}")
if doc["ifd_count"] < 2:
    raise SystemExit("no overview IFDs; not the expected GDAL COG layout")
PY
}

downloaded=0
while read -r iso url size md5 sha width height tiles; do
  out="$TIF_DIR/${iso}_wind-speed_100m.tif"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && valid_tif "$out" "$size" "$md5" "$sha" "$width" "$height" "$tiles"; then
    echo "cache_hit iso3=$iso bytes=$size"
    downloaded=$((downloaded + 1))
    continue
  fi
  rm -f "$out" "$out.validation.json"
  part="$out.part"
  if [ "$(fsize "$part")" -gt "$size" ]; then
    echo "discarding oversized partial file $part"
    rm -f "$part"
  fi
  echo "fetch iso3=$iso bytes=$size resume_from=$(fsize "$part") url=$url"
  attempt=1
  until [ "$(fsize "$part")" = "$size" ] || \
      curl --globoff -fL -sS -C - --retry 10 --retry-all-errors --retry-delay 5 \
      --connect-timeout 30 --speed-limit 1024 --speed-time 120 -A "$UA" \
      -o "$part" "$url"; do
    if [ "$attempt" -ge 3 ]; then
      echo "FATAL: curl failed repeatedly for iso3=$iso" >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    echo "retrying iso3=$iso (attempt $attempt)"
    sleep 10
  done
  if ! valid_tif "$part" "$size" "$md5" "$sha" "$width" "$height" "$tiles"; then
    echo "FATAL: downloaded payload failed validation iso3=$iso" >&2
    rm -f "$part" "$part.validation.json"
    exit 1
  fi
  mv "$part.validation.json" "$out.validation.json"
  mv "$part" "$out"
  echo "validated iso3=$iso bytes=$size md5=$md5"
  downloaded=$((downloaded + 1))
  sleep "${GWA_PAUSE_SECONDS:-2}"
done < "$PLAN"

found="$(find "$TIF_DIR" -maxdepth 1 -type f -name '???_wind-speed_100m.tif' | wc -l | tr -d ' ')"
if [ "$downloaded" -ne "$EXPECTED_FILES" ] || [ "$found" -ne "$EXPECTED_FILES" ]; then
  echo "FATAL: expected $EXPECTED_FILES validated files, downloaded=$downloaded found=$found" >&2
  exit 1
fi
total="$(find "$TIF_DIR" -maxdepth 1 -type f -name '???_wind-speed_100m.tif' -printf '%s\n' | awk '{s+=$1} END {print s}')"
if [ "$total" -ne "$EXPECTED_TOTAL_BYTES" ]; then
  echo "FATAL: downloaded bytes $total != $EXPECTED_TOTAL_BYTES" >&2
  exit 1
fi
# Record sha256 of every validated file (all equal to the countries.tsv pins).
(cd "$TIF_DIR" && sha256sum ???_wind-speed_100m.tif) > "$DOWNLOAD_DIR/sha256sums.txt"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$found bytes=$total"
