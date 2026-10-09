#!/usr/bin/env bash
# Download the 20 pinned USGS 3DEP ID_NorthForkPayette_1_2020 LAZ tiles.
#
# 1. Fetch the project VPC, the official link list (prd-tnm S3) and the USGS
#    work-package report (sensor lineage), then re-derive the tile selection;
#    it must equal sources.tsv.
# 2. Fetch each pinned tile from rockyweb.usgs.gov (the only host serving the
#    LAZ files) with resumable curl into a .part file, plus an outer retry
#    loop because rockyweb / the egress proxy fail intermittently (503s).
# 3. Validate every tile before keeping it: exact pinned size and ETag, LAS 1.4
#    header (system id MERGE, software LiDAR Suite, creation 2021/pinned day,
#    compressed PDRF 6, 30-byte records, scale 0.01, offset 0, WKT bit, point
#    count == VPC pc:count, the 15 extended points-by-return counts == the
#    pinned probe values), LASzip VLR (compressor 3, POINT14 v3, chunk 50000),
#    contractor VLR, chunk-table pointer, UTM 11N WKT EVLR, and the pinned
#    sha256 when sources.tsv carries one. Digests go to
#    downloads/<id>/meta/sha256.tsv.
# Re-runs skip tiles that already validate and resume partial .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_3dep_id_northforkpayette_laz_return_number_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
TOOL="$RECIPE_DIR/scripts/nfp_tiles.py"
S3="https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020"
WP_URL="https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/metadata/ID_NorthForkPayette_2020_B20/USGS_ID_NorthForkPayette_2020_B20_WP_Report.pdf"
VPC_NAME="ID_NorthForkPayette_1_2020.vpc"
VPC_BYTES=29483672
VPC_SHA256="a62a72a0855a35dd28f6ff2e1a633aa0cbd03108023d1db30bb3d9cdd8dbdbbe"
LINKS_BYTES=1864351
LINKS_SHA256="81fa503b952bd6665950ebd1ccfebb93e5250f683aa0560bb8ade0b3f3cbc13f"
WP_BYTES=53411
WP_SHA256="ba001930d4b9ebd50e10caa3adc8abb96792c7f2cf4cea41995444e848a2bf64"
EXPECTED_TILES=20
EXPECTED_TILE_BYTES=1007660019
UA="openzl-public-datasets-usgs-3dep-nfp/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")
OUTER_ATTEMPTS=8

mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/laz" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

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
    echo "meta=$name bytes=$bytes sha256=ok"
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
fetch_meta "USGS_ID_NorthForkPayette_2020_B20_WP_Report.pdf" "$WP_URL" "$WP_BYTES" "$WP_SHA256" strict
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

# 2./3. Tiles.
SHA_FILE="$DOWNLOAD_DIR/meta/sha256.tsv"
touch "$SHA_FILE"
record_sha() {
  local name="$1" digest="$2"
  grep -v -F "$name"$'\t' "$SHA_FILE" > "$SHA_FILE.tmp" || true
  printf '%s\t%s\n' "$name" "$digest" >> "$SHA_FILE.tmp"
  sort "$SHA_FILE.tmp" > "$SHA_FILE"
  rm -f "$SHA_FILE.tmp"
}

total=$(($(wc -l < "$SOURCES") - 1))
[ "$total" = "$EXPECTED_TILES" ] || { echo "FATAL: sources.tsv has $total tiles, expected $EXPECTED_TILES" >&2; exit 1; }
sum_bytes=0
done_count=0
# Fields are split on \x1f, not tab: tab is IFS whitespace, so bash would merge
# consecutive tabs and shift columns when a field (e.g. sha256) is empty.
while IFS=$'\x1f' read -r tile_id pc_count vpc_datetime file_name size_bytes etag last_modified creation_day pbr sha256 url; do
  [ "$tile_id" = "tile_id" ] && continue
  case "$url" in
    https://rockyweb.usgs.gov/*/"$file_name") ;;
    *) echo "FATAL: malformed sources.tsv row for tile $tile_id (url='$url')" >&2; exit 1 ;;
  esac
  case "$size_bytes" in ''|*[!0-9]*) echo "FATAL: bad size_bytes for tile $tile_id" >&2; exit 1 ;; esac
  sum_bytes=$((sum_bytes + size_bytes))
  out="$DOWNLOAD_DIR/laz/$file_name"
  headers="$DOWNLOAD_DIR/meta/$tile_id.headers"
  if [ -s "$out" ] && digest="$(python3 -I "$TOOL" check-tile --sources "$SOURCES" --name "$file_name" --file "$out" < /dev/null)"; then
    record_sha "$file_name" "$digest"
    done_count=$((done_count + 1))
    echo "have=$done_count/$total tile=$tile_id"
    continue
  fi
  rm -f "$out"
  ok=0
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
        exit 1
      fi
      if digest="$(python3 -I "$TOOL" check-tile --sources "$SOURCES" --name "$file_name" --file "$out.part" < /dev/null)"; then
        mv "$out.part" "$out"
        record_sha "$file_name" "$digest"
        ok=1
        break
      fi
      echo "invalid payload for $file_name; discarding partial file" >&2
      rm -f "$out.part"
    fi
    echo "retry tile=$tile_id attempt=$attempt" >&2
    sleep $((attempt * 15))
  done
  rm -f "$headers"
  if [ "$ok" != "1" ]; then
    echo "FATAL: could not fetch a valid $file_name after $OUTER_ATTEMPTS attempts" >&2
    exit 1
  fi
  done_count=$((done_count + 1))
  echo "fetched=$done_count/$total tile=$tile_id bytes=$size_bytes points=$pc_count"
done < <(tr '\t' '\037' < "$SOURCES")

[ "$sum_bytes" = "$EXPECTED_TILE_BYTES" ] || { echo "FATAL: pinned tile bytes $sum_bytes != $EXPECTED_TILE_BYTES" >&2; exit 1; }
python3 -I "$TOOL" check-all --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR" | tail -n 1
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
