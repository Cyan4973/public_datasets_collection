#!/usr/bin/env bash
# Download the 24 pinned USGS 3DEP CO_CameronPkFire_1_2021 LAZ tiles.
#
# 1. Fetch the work-unit VPC, the official link list and the USGS LazQC LPC
#    report (prd-tnm S3), then re-derive the tile selection; it must equal
#    sources.tsv.
# 2. Fetch each pinned tile from rockyweb.usgs.gov (the only host serving the
#    LAZ files) with resumable curl into a .part file, plus an outer retry
#    loop; up to PARALLEL (default 4) tiles are fetched at once because a
#    single rockyweb stream runs at roughly 0.5 MB/s.
# 3. Validate every tile before keeping it: exact pinned size and ETag, LAS 1.4
#    header (system id 'Riegl VQ-1560 II', software 'GeoCue LAS Updater',
#    creation 2022/pinned day, compressed PDRF 6, 30-byte records, scale
#    0.001, WKT bit, no EVLRs, point count == VPC pc:count, the 15 extended
#    points-by-return counts == the pinned probe values), LASzip VLR
#    (compressor 3, POINT14 v3, chunk 50000), contractor VLR NIIRS10, the
#    Colorado North (ftUS) WKT VLR, the chunk table, and the pinned sha256 when
#    sources.tsv carries one. Digests go to downloads/<id>/meta/sha256.tsv.
# Re-runs skip tiles that already validate and resume partial .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
TOOL="$RECIPE_DIR/scripts/cpk_tiles.py"
S3="https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021"
META_S3="https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/metadata/CO_CameronPeakWildfire_2021_D21"
VPC_NAME="CO_CameronPkFire_1_2021.vpc"
VPC_BYTES=3768776
VPC_SHA256="7f11f71d2d0b77d3f0ee655b8ba1ad3e754b5282d2275373100d8c6b2e0f4897"
LINKS_BYTES=222897
LINKS_SHA256="ca0f5b38d92a8b10ae405089439f5e23a4fea94f9945f70aece26dc70eb71ba3"
LPC_REPORT="USGS_CO_CameronPkFire_1_2021_FINAL_LPC_Report.txt"
LPC_REPORT_BYTES=171978
LPC_REPORT_SHA256="22c8523e656d2f8982192e36cb0886b8cdbe048ec806aeda85556b91b59b8c23"
EXPECTED_TILES=24
EXPECTED_TILE_BYTES=1985279750
PARALLEL="${PARALLEL:-4}"
UA="openzl-public-datasets-usgs-3dep-cpk/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")
OUTER_ATTEMPTS=8

mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/laz" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID parallel=$PARALLEL"

python3 -I "$TOOL" self-test

# 1. Small metadata files from S3 (bounded with --max-time: a few MB at most).
fetch_meta() {  # name url bytes sha strict
  local name="$1" url="$2" bytes="$3" sha="$4" strict="$5" out="$DOWNLOAD_DIR/meta/$1"
  if [ ! -s "$out" ] || [ "$(stat -c %s "$out")" != "$bytes" ]; then
    rm -f "$out.part"
    curl "${CURL_COMMON[@]}" --max-time 900 -o "$out.part" "$url"
    mv "$out.part" "$out"
  fi
  local got
  got="$(sha256sum "$out" | cut -d' ' -f1)"
  if [ "$got" = "$sha" ]; then
    echo "meta=$name bytes=$(stat -c %s "$out") sha256=ok"
  elif [ "$strict" = "strict" ]; then
    echo "FATAL: $name sha256 $got differs from pinned $sha" >&2
    exit 1
  else
    # USGS regenerates VPCs from time to time; the selection check below is
    # what must hold, so a changed digest alone is reported, not fatal.
    echo "WARNING: $name sha256 $got differs from pinned $sha (size $(stat -c %s "$out"))"
  fi
}
fetch_meta "$VPC_NAME" "$S3/$VPC_NAME" "$VPC_BYTES" "$VPC_SHA256" lenient
fetch_meta "0_file_download_links.txt" "$S3/0_file_download_links.txt" "$LINKS_BYTES" "$LINKS_SHA256" lenient
fetch_meta "$LPC_REPORT" "$META_S3/CO_CameronPkFire_1_2021/reports/$LPC_REPORT" "$LPC_REPORT_BYTES" "$LPC_REPORT_SHA256" strict
python3 -I "$TOOL" check-selection --vpc "$DOWNLOAD_DIR/meta/$VPC_NAME" \
  --links "$DOWNLOAD_DIR/meta/0_file_download_links.txt" --sources "$SOURCES"

# Liveness: one-byte range GET on the first pinned tile.
first_url="$(awk -F'\t' 'NR==2{print $11}' "$SOURCES")"
live_ok=0
for attempt in 1 2 3 4 5 6; do
  if curl "${CURL_COMMON[@]}" --max-time 120 --range 0-0 --output /dev/null "$first_url"; then
    live_ok=1; break
  fi
  echo "liveness retry attempt=$attempt" >&2
  sleep $((attempt * 10))
done
[ "$live_ok" = "1" ] || { echo "FATAL: rockyweb.usgs.gov not reachable" >&2; exit 1; }
echo "liveness=ok"

# 2./3. Tiles. Each worker writes its digest to meta/sha/<file>.sha256; the
# combined meta/sha256.tsv is assembled after all workers finish.
mkdir -p "$DOWNLOAD_DIR/meta/sha"

fetch_tile() {  # tile_id pc_count file_name size_bytes etag url
  local tile_id="$1" pc_count="$2" file_name="$3" size_bytes="$4" etag="$5" url="$6"
  local out="$DOWNLOAD_DIR/laz/$file_name" headers="$DOWNLOAD_DIR/meta/$tile_id.headers"
  local shaf="$DOWNLOAD_DIR/meta/sha/$file_name.sha256" digest fetched got_etag attempt
  if [ -s "$out" ] && digest="$(python3 -I "$TOOL" check-tile --sources "$SOURCES" --name "$file_name" --file "$out" < /dev/null)"; then
    echo "$digest" > "$shaf"
    echo "have tile=$tile_id"
    return 0
  fi
  rm -f "$out"
  for attempt in $(seq 1 "$OUTER_ATTEMPTS"); do
    if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" -gt "$size_bytes" ]; then
      rm -f "$out.part"
    fi
    if [ -f "$out.part" ] && [ "$(stat -c %s "$out.part")" = "$size_bytes" ]; then
      fetched=1
    elif curl "${CURL_COMMON[@]}" -C - --dump-header "$headers" --output "$out.part" "$url" < /dev/null; then
      fetched=1
    else
      fetched=0
    fi
    if [ "$fetched" = "1" ]; then
      got_etag="$(tr -d '\r' < "$headers" 2>/dev/null | awk 'tolower($1)=="etag:"{e=$2} END{gsub(/"/,"",e); print e}')"
      if [ -n "$got_etag" ] && [ "$got_etag" != "$etag" ]; then
        echo "FATAL: $file_name ETag $got_etag != pinned $etag (upstream file changed)" >&2
        return 2
      fi
      if digest="$(python3 -I "$TOOL" check-tile --sources "$SOURCES" --name "$file_name" --file "$out.part" < /dev/null)"; then
        mv "$out.part" "$out"
        echo "$digest" > "$shaf"
        rm -f "$headers"
        echo "fetched tile=$tile_id bytes=$size_bytes points=$pc_count"
        return 0
      fi
      echo "invalid payload for $file_name; discarding partial file" >&2
      rm -f "$out.part"
    fi
    echo "retry tile=$tile_id attempt=$attempt" >&2
    sleep $((attempt * 15))
  done
  echo "FATAL: could not fetch a valid $file_name after $OUTER_ATTEMPTS attempts" >&2
  return 1
}

total=$(($(wc -l < "$SOURCES") - 1))
[ "$total" = "$EXPECTED_TILES" ] || { echo "FATAL: sources.tsv has $total tiles, expected $EXPECTED_TILES" >&2; exit 1; }
sum_bytes=0
pids=()
# Fields are split on \x1f, not tab: tab is IFS whitespace, so bash would merge
# consecutive tabs and shift columns when a field (e.g. sha256) is empty.
while IFS=$'\x1f' read -r tile_id pc_count _vpc_datetime file_name size_bytes etag _last_modified _creation_day _pbr _sha256 url; do
  [ "$tile_id" = "tile_id" ] && continue
  case "$url" in
    https://rockyweb.usgs.gov/*/"$file_name") ;;
    *) echo "FATAL: malformed sources.tsv row for tile $tile_id (url='$url')" >&2; exit 1 ;;
  esac
  case "$size_bytes" in ''|*[!0-9]*) echo "FATAL: bad size_bytes for tile $tile_id" >&2; exit 1 ;; esac
  sum_bytes=$((sum_bytes + size_bytes))
  while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]; do
    wait -n || true
  done
  fetch_tile "$tile_id" "$pc_count" "$file_name" "$size_bytes" "$etag" "$url" &
  pids+=("$!")
done < <(tr '\t' '\037' < "$SOURCES")

failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=$((failed + 1))
done
[ "$failed" = "0" ] || { echo "FATAL: $failed tile download(s) failed; re-run to resume" >&2; exit 1; }
[ "$sum_bytes" = "$EXPECTED_TILE_BYTES" ] || { echo "FATAL: pinned tile bytes $sum_bytes != $EXPECTED_TILE_BYTES" >&2; exit 1; }

SHA_FILE="$DOWNLOAD_DIR/meta/sha256.tsv"
: > "$SHA_FILE.tmp"
for f in "$DOWNLOAD_DIR"/meta/sha/*.sha256; do
  printf '%s\t%s\n' "$(basename "$f" .sha256)" "$(cat "$f")" >> "$SHA_FILE.tmp"
done
sort "$SHA_FILE.tmp" > "$SHA_FILE"
rm -f "$SHA_FILE.tmp"
python3 -I "$TOOL" check-all --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR" | tail -n 1
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
