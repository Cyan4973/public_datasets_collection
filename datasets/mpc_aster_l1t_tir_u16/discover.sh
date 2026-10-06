#!/usr/bin/env bash
# Metadata-only scene resolution for mpc_aster_l1t_tir_u16 (no raster payload).
#
# For each of 26 fixed regions and two seasonal windows (Feb 15 - Apr 30 and
# Jul 1 - Sep 15) it runs a Planetary Computer STAC search on the aster-l1t
# collection (bbox + window + eo:cloud_cover < 10), starting at the region's
# base year and falling back to the nearest other year in 2000..2006 until a
# scene qualifies. The scene rule (scripts/stac_select.py) keeps daytime items
# (view:sun_elevation > 20) that carry a TIR asset and takes the lowest cloud
# cover, then the earliest datetime, then the item id. Each chosen TIR href is
# then HEAD-requested with an anonymous Planetary Computer SAS for its exact
# Content-Length and Azure Content-MD5.
#
# Output: $DATA_DIR/downloads/<id>/discovered_sources.tsv, plus a timestamped
# copy under $DATA_DIR/logs/<id>/. The run of 2026-10-05 produced the plan
# pinned in sources.tsv (download.sh uses only that file); re-running this
# script is optional and lets you compare a fresh resolution with the pin.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_aster_l1t_tir_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HELPER="$RECIPE_DIR/scripts/stac_select.py"
UA="openzl-public-datasets/1.0 ($DATASET_ID)"
STAC_SEARCH="https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_ENDPOINT="https://planetarycomputer.microsoft.com/api/sas/v1/token/astersa/aster"
OUT="$DOWNLOAD_DIR/discovered_sources.tsv"
MIN_SCENES=40
MAX_PAGES=30

# region_id, label, west, south, east, north, base_year
cat > "$WORK/regions.tsv" <<'EOF'
sahara_hoggar_algeria	Hoggar massif, central Sahara (hot desert, volcanic uplands)	5.0	22.5	6.5	24.0	2000
sahel_inner_niger_delta_mali	Inner Niger Delta, Sahel (floodplain and semi-arid savanna)	-5.0	14.0	-3.5	15.5	2001
rub_al_khali_saudi_arabia	Rub al Khali (sand sea)	48.5	19.5	50.0	21.0	2002
dasht_e_lut_iran	Dasht-e Lut (hyper-arid basin)	58.5	29.5	60.0	31.0	2003
thar_desert_india	Thar desert (arid plains and dunes)	70.5	26.0	72.0	27.5	2004
turkana_basin_kenya	Lake Turkana basin, East African Rift	35.5	2.5	37.0	4.0	2005
kalahari_botswana	Central Kalahari (semi-arid savanna, pans)	22.5	-22.0	24.0	-20.5	2006
namib_sand_sea_namibia	Namib sand sea and escarpment	15.0	-24.5	16.5	-23.0	2000
karakoram_ladakh	Karakoram and Ladakh (high mountains, glaciers)	76.5	34.5	78.0	36.0	2001
taklamakan_china	Taklamakan desert, Tarim basin	81.5	38.5	83.0	40.0	2002
gobi_mongolia	Gobi (cold desert steppe)	103.0	43.0	104.5	44.5	2003
loess_plateau_china	Loess Plateau (dissected uplands, farmland)	108.0	36.5	109.5	38.0	2004
yakutia_lena_siberia	Central Yakutia, Lena valley (taiga, permafrost)	129.0	61.5	130.5	63.0	2005
aral_sea_kazakhstan	Aral Sea basin (desiccated lake bed, steppe)	59.5	44.5	61.0	46.0	2006
central_anatolia_turkey	Central Anatolian plateau (steppe, salt lake)	32.5	38.0	34.0	39.5	2000
iberian_meseta_spain	Southern Meseta, Iberia (Mediterranean farmland)	-4.0	39.5	-2.5	41.0	2001
pannonian_plain_hungary	Great Hungarian Plain (temperate farmland)	19.5	46.5	21.0	48.0	2002
greenland_ice_margin	West Greenland ice-sheet margin, Kangerlussuaq	-50.5	66.5	-48.5	67.5	2003
death_valley_mojave_usa	Death Valley and Mojave (basin and range)	-117.5	35.5	-116.0	37.0	2004
great_plains_kansas_usa	Central Great Plains, Kansas (cropland)	-100.0	38.0	-98.5	39.5	2005
chihuahuan_desert_mexico	Chihuahuan desert (basin and range)	-107.0	28.5	-105.5	30.0	2006
altiplano_uyuni_bolivia	Altiplano, Salar de Uyuni (high plateau, salt flat)	-68.5	-20.5	-67.0	-19.0	2000
atacama_chile	Atacama desert and Andean volcanoes	-69.8	-24.0	-68.3	-22.5	2001
patagonian_steppe_argentina	Patagonian steppe	-70.0	-46.0	-68.5	-44.5	2002
cerrado_brazil	Brazilian Cerrado plateau (savanna, cropland)	-48.0	-16.0	-46.5	-14.5	2003
great_sandy_desert_australia	Great Sandy Desert, Western Australia	123.0	-21.0	124.5	-19.5	2004
EOF
# window_id, start MM-DD, end MM-DD
cat > "$WORK/windows.tsv" <<'EOF'
feb_apr	02-15	04-30
jul_sep	07-01	09-15
EOF

fallback_years() {
  local base="$1" d y out=""
  for d in 0 1 -1 2 -2 3 -3 4 -4 5 -5 6 -6; do
    y=$((base + d))
    if [ "$y" -ge 2000 ] && [ "$y" -le 2006 ]; then out="$out $y"; fi
  done
  echo $out
}

stac_post() {  # stac_post <body.json> <out.json>
  curl --globoff -fsS --retry 6 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 180 \
    -A "$UA" -X POST -H 'Content-Type: application/json' --data-binary @"$1" -o "$2" "$STAC_SEARCH"
}

stac_get() {  # stac_get <href> <out.json>
  curl --globoff -fsS --retry 6 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time 180 \
    -A "$UA" -o "$2" "$1"
}

# search_all <key> <west> <south> <east> <north> <start> <end> -> page file list on stdout
search_all() {
  local key="$1" page=1 body="$WORK/$1.body.1.json" pages="" next
  python3 "$HELPER" body "$2" "$3" "$4" "$5" "$6" "$7" > "$body"
  stac_post "$body" "$WORK/$key.page.1.json"
  pages="$WORK/$key.page.1.json"
  while :; do
    next="$(python3 "$HELPER" next "$body" "$WORK/$key.page.$page.json")"
    [ -n "$next" ] || break
    if [ "$page" -ge "$MAX_PAGES" ]; then
      echo "FATAL: more than $MAX_PAGES result pages for $key" >&2
      return 1
    fi
    page=$((page + 1))
    case "$next" in
      "GET "*) stac_get "${next#GET }" "$WORK/$key.page.$page.json" ;;
      *) body="$WORK/$key.body.$page.json"; printf '%s' "$next" > "$body"; stac_post "$body" "$WORK/$key.page.$page.json" ;;
    esac
    pages="$pages $WORK/$key.page.$page.json"
    sleep 0.3
  done
  echo "$pages"
}

: > "$WORK/selected_ids.txt"
: > "$WORK/chosen.tsv"
searches=0
missing=0
while IFS=$'\t' read -r region label west south east north base; do
  while IFS=$'\t' read -r window wstart wend; do
    picked=""
    for year in $(fallback_years "$base"); do
      key="${region}.${window}.${year}"
      pages="$(search_all "$key" "$west" "$south" "$east" "$north" "${year}-${wstart}T00:00:00Z" "${year}-${wend}T23:59:59Z")"
      searches=$((searches + 1))
      # shellcheck disable=SC2086
      picked="$(python3 "$HELPER" pick "$WORK/selected_ids.txt" $pages)"
      if [ -n "$picked" ]; then
        printf '%s\n' "$picked" | cut -f1 >> "$WORK/selected_ids.txt"
        printf '%s\t%s\t%s\t%s\t%s\n' "$region" "$label" "$window" "$year" "$picked" >> "$WORK/chosen.tsv"
        echo "chosen region=$region window=$window year=$year $(printf '%s' "$picked" | cut -f1-4 | tr '\t' ' ') candidates=$(printf '%s' "$picked" | cut -f7)"
        break
      fi
      echo "no qualifying scene region=$region window=$window year=$year"
      sleep 0.3
    done
    if [ -z "$picked" ]; then
      missing=$((missing + 1))
      echo "WARN: no qualifying scene in 2000..2006 for region=$region window=$window"
    fi
  done < "$WORK/windows.tsv"
done < "$WORK/regions.tsv"

chosen="$(wc -l < "$WORK/chosen.tsv" | tr -d ' ')"
echo "stac_done searches=$searches chosen=$chosen missing_windows=$missing"
if [ "$chosen" -lt "$MIN_SCENES" ]; then
  echo "FATAL: only $chosen scenes resolved (minimum $MIN_SCENES)" >&2
  exit 1
fi

# Anonymous SAS for the astersa/aster container (no account, key or login),
# then HEAD every chosen TIR blob for its exact size and Content-MD5.
curl --globoff -fsSL --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
  -A "$UA" -o "$WORK/sas.json" "$SAS_ENDPOINT"
sas_query="$(python3 "$HELPER" sas "$WORK/sas.json")"
rm -f "$WORK/sas.json"

printf 'region_id\tregion_label\twindow\tyear\titem_id\tdatetime\tcloud_cover\tsun_elevation\tsun_azimuth\tcandidates\turl\tsize_bytes\tcontent_md5_b64\n' > "$OUT.tmp"
while IFS=$'\t' read -r region label window year item_id when cloud sun azimuth href candidates; do
  headers="$(curl --globoff -fsSI --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 60 \
    -A "$UA" "${href}?${sas_query}" | tr -d '\r')"
  size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:" {print $2}' | tail -1)"
  md5="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-md5:" {print $2}' | tail -1)"
  md5="${md5:-NA}"  # never leave an empty TSV field (bash read collapses adjacent tabs)
  ctype="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-type:" {print $2}' | tail -1)"
  case "$size" in ''|*[!0-9]*) echo "FATAL: no Content-Length for $href" >&2; exit 1 ;; esac
  if [ "$size" -lt 200000 ] || [ "$size" -gt 60000000 ]; then
    echo "FATAL: implausible TIR size $size for $href" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$region" "$label" "$window" "$year" "$item_id" \
    "$when" "$cloud" "$sun" "$azimuth" "$candidates" "$href" "$size" "$md5" >> "$OUT.tmp"
  echo "head item=$item_id bytes=$size content_md5=$md5 content_type=${ctype:-none}"
done < "$WORK/chosen.tsv"
sas_query=""
mv "$OUT.tmp" "$OUT"
cp "$OUT" "$LOG_DIR/discovered_sources.$RUN_TS.tsv"
total="$(awk -F'\t' 'NR > 1 {s += $12} END {print s}' "$OUT")"
echo "[$(date -Is)] discover done dataset=$DATASET_ID scenes=$chosen bytes=$total plan=$OUT"
