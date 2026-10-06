#!/usr/bin/env bash
# Metadata-only scene resolution for mpc_landsat_c2_l1_mss_dn_u8 (no raster payload).
#
# For each of 13 fixed WRS-2 path/rows it runs one Planetary Computer STAC
# search on the landsat-c2-l1 collection (Landsat-5, L1TP, Tier 1, the path
# and row, 1984-03-01..1993-12-31, eo:cloud_cover < 5) and applies the scene
# rule in scripts/stac_select.py: MSS only, collection 02, sun elevation > 30,
# all four band assets plus MTL.json present; lowest cloud cover, then highest
# sun elevation, then earliest datetime, then id. With an anonymous Planetary
# Computer SAS it then HEADs every chosen blob (B1..B4 COGs and MTL.json) for
# its exact Content-Length and Azure Content-MD5, and range-reads the first
# 64 KiB of each COG to check the IFD-0 structure (uint8, Deflate, tiled,
# GDAL_NODATA 0) and record its width, height and predictor.
#
# Output: $DATA_DIR/downloads/<id>/discovered_sources.tsv (one row per file)
# plus a timestamped copy under $DATA_DIR/logs/<id>/. The run of 2026-10-06
# produced the plan pinned in sources.tsv; download.sh uses only that file.
# Re-running this script is optional and lets you compare a fresh resolution
# with the pin.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_landsat_c2_l1_mss_dn_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HELPER="$RECIPE_DIR/scripts/stac_select.py"
COG="$RECIPE_DIR/scripts/mss_cog.py"
UA="openzl-public-datasets/1.0 ($DATASET_ID)"
STAC_SEARCH="https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/landsateuwest/landsat-c2"
OUT="$DOWNLOAD_DIR/discovered_sources.tsv"
MAX_PAGES=10

# region_id, label, wrs_path, wrs_row (chosen for biome and continental spread,
# land-dominant footprints; see README for the candidates that were dropped)
cat > "$WORK/regions.tsv" <<'EOF'
fezzan_libya	Fezzan, central Libyan Sahara (hyper-arid hamada and erg)	186	041
kordofan_sudan	Kordofan-Darfur, Sudan (Sahel savanna, dry season)	176	052
harrat_khaybar_saudi_arabia	Harrat Khaybar and Najd, Saudi Arabia (arid plateau, lava fields)	170	042
aral_sea_ustyurt	Aral Sea west shore and Ustyurt plateau (cold desert, shrinking lake)	162	029
northern_territory_australia	Barkly-Tanami, Northern Territory, Australia (tropical savanna, dry season)	104	073
gran_chaco_argentina	Gran Chaco and sub-Andean ranges, Salta, Argentina (dry forest, clearings)	230	077
corrientes_ibera_argentina	Corrientes and the Ibera wetlands, Argentina (humid grassland, wetland, river)	225	080
llano_estacado_texas	Llano Estacado, Texas, USA (irrigated and dryland cropland)	030	037
lower_michigan_usa	Lower Michigan and Saginaw Bay, USA (temperate farmland and forest)	021	030
everglades_florida	South Florida and the Everglades, USA (subtropical wetland, coast)	015	042
mackenzie_delta_canada	Mackenzie Delta and Beaufort coast, Canada (arctic delta, sea ice)	065	011
bolshezemelskaya_tundra_russia	Bolshezemelskaya tundra, Russia (arctic tundra, thermokarst lakes)	171	012
canadian_shield_nwt_canada	Canadian Shield, NWT-Saskatchewan border, Canada (boreal forest, glacial lakes)	039	017
EOF

stac_post() {  # stac_post <body.json> <out.json>
  curl --globoff -fsS --retry 6 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 180 \
    -A "$UA" -X POST -H 'Content-Type: application/json' --data-binary @"$1" -o "$2" "$STAC_SEARCH"
}

stac_get() {  # stac_get <href> <out.json>
  curl --globoff -fsS --retry 6 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 180 \
    -A "$UA" -o "$2" "$1"
}

: > "$WORK/chosen.tsv"
while IFS=$'\t' read -r region label path row; do
  key="p${path}r${row}"
  page=1
  body="$WORK/$key.body.1.json"
  python3 "$HELPER" body "$path" "$row" > "$body"
  stac_post "$body" "$WORK/$key.page.1.json"
  pages="$WORK/$key.page.1.json"
  while :; do
    next="$(python3 "$HELPER" next "$body" "$WORK/$key.page.$page.json")"
    [ -n "$next" ] || break
    if [ "$page" -ge "$MAX_PAGES" ]; then
      echo "FATAL: more than $MAX_PAGES result pages for $key" >&2
      exit 1
    fi
    page=$((page + 1))
    case "$next" in
      "GET "*) stac_get "${next#GET }" "$WORK/$key.page.$page.json" ;;
      *) body="$WORK/$key.body.$page.json"; printf '%s' "$next" > "$body"; stac_post "$body" "$WORK/$key.page.$page.json" ;;
    esac
    pages="$pages $WORK/$key.page.$page.json"
    sleep 0.3
  done
  # shellcheck disable=SC2086
  picked="$(python3 "$HELPER" pick $pages)"
  if [ -z "$picked" ]; then
    echo "FATAL: no qualifying scene for region=$region path/row=$path/$row" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$region" "$label" "$path" "$row" "$picked" >> "$WORK/chosen.tsv"
  echo "chosen region=$region path/row=$path/$row $(printf '%s' "$picked" | cut -f1,3-9 | tr '\t' ' ')"
  sleep 0.3
done < "$WORK/regions.tsv"
echo "stac_done scenes=$(wc -l < "$WORK/chosen.tsv" | tr -d ' ')"

# Anonymous SAS for the landsateuwest/landsat-c2 container (no account, key
# or login); then HEAD every blob and range-probe each COG header.
curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
  -A "$UA" -o "$WORK/sas.json" "$SAS_ENDPOINT"
sas_query="$(python3 "$HELPER" sas "$WORK/sas.json")"
rm -f "$WORK/sas.json"

printf 'region_id\tregion_label\twrs_path\twrs_row\titem_id\tproduct_id\tdatetime\tcloud_cover\tsun_elevation\tsun_azimuth\tproj_rows\tproj_cols\tcandidates\tasset\tband\turl\tsize_bytes\tcontent_md5_b64\ttiff_width\ttiff_height\ttiff_predictor\n' > "$OUT.tmp"
while IFS=$'\t' read -r region label path row item_id product_id when cloud sun azimuth prows pcols candidates a1 a2 a3 a4 a5; do
  for spec in "$a1" "$a2" "$a3" "$a4" "$a5"; do
    asset="${spec%%=*}"
    href="${spec#*=}"
    case "$asset" in
      green) band="B1" ;; red) band="B2" ;; nir08) band="B3" ;; nir09) band="B4" ;; mtl.json) band="MTL" ;;
      *) echo "FATAL: unexpected asset $asset" >&2; exit 1 ;;
    esac
    headers="$(curl --globoff -fsSI --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
      -A "$UA" "${href}?${sas_query}" | tr -d '\r')"
    size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:" {print $2}' | tail -1)"
    md5="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-md5:" {print $2}' | tail -1)"
    md5="${md5:-NA}"  # never leave an empty TSV field (bash read collapses adjacent tabs)
    case "$size" in ''|*[!0-9]*) echo "FATAL: no Content-Length for $href" >&2; exit 1 ;; esac
    tw="NA"; th="NA"; tp="NA"
    if [ "$band" = "MTL" ]; then
      if [ "$size" -lt 2000 ] || [ "$size" -gt 200000 ]; then
        echo "FATAL: implausible MTL.json size $size for $href" >&2
        exit 1
      fi
    else
      if [ "$size" -lt 500000 ] || [ "$size" -gt 40000000 ]; then
        echo "FATAL: implausible COG size $size for $href" >&2
        exit 1
      fi
      curl --globoff -fsS --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
        -A "$UA" -r 0-65535 -o "$WORK/head.bin" "${href}?${sas_query}"
      header_json="$(python3 "$COG" header "$WORK/head.bin" --partial)"
      read -r tw th tp <<< "$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["width"], d["height"], d["predictor"])' "$header_json")"
      if [ "$tw" != "$pcols" ] || [ "$th" != "$prows" ]; then
        echo "FATAL: $href IFD0 ${tw}x${th} differs from STAC proj:shape ${prows}x${pcols} (rows x cols)" >&2
        exit 1
      fi
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$region" "$label" "$path" "$row" "$item_id" "$product_id" "$when" "$cloud" "$sun" "$azimuth" \
      "$prows" "$pcols" "$candidates" "$asset" "$band" "$href" "$size" "$md5" "$tw" "$th" "$tp" >> "$OUT.tmp"
    echo "head item=$item_id band=$band bytes=$size content_md5=$md5 ifd0=${tw}x${th} predictor=$tp"
  done
done < "$WORK/chosen.tsv"
sas_query=""
mv "$OUT.tmp" "$OUT"
cp "$OUT" "$LOG_DIR/discovered_sources.$RUN_TS.tsv"
total="$(awk -F'\t' 'NR > 1 {s += $17} END {print s}' "$OUT")"
files="$(awk -F'\t' 'NR > 1' "$OUT" | wc -l | tr -d ' ')"
echo "[$(date -Is)] discover done dataset=$DATASET_ID files=$files bytes=$total plan=$OUT"
