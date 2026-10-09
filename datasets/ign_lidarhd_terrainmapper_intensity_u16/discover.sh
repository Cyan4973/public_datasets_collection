#!/usr/bin/env bash
# Documents how sources.tsv was resolved (run once by the author; download.sh
# only reads the committed sources.tsv). Small metadata requests only:
#   1. one WFS GetFeature on IGNF_LIDAR-HD_METADONNEE:metadata filtered on
#      code_mission='21LHD2GO' (tile grid, sensor, point count, url_npl);
#   2. the Atom download-service feed of the delivery
#      NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22 (51 pages x 50 entries; per-file
#      byte length and MD5), paced to the service's 1 request/s limit;
#   3. scripts/select_tiles.py applies the deterministic interior-grid rule;
#   4. one 375-byte range request per selected tile pins the LAS header
#      point count (scripts/add_header_counts.py).
# Usage: OUT_DIR=/tmp/somewhere bash discover.sh   (writes OUT_DIR/sources.tsv)
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUT_DIR:-/tmp/ign_lidarhd_terrainmapper_intensity_u16_discovery}"
UA="openzl-public-datasets-ign-lidarhd/1.0"
DELIVERY="NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22"
WFS="https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_LIDAR-HD_METADONNEE:metadata&OUTPUTFORMAT=application/json&COUNT=5000&PROPERTYNAME=capteur,url_npl,code_mission,nombre_points,coordonnees_nw,date_debut_acquisition,date_fin_acquisition,procede_classement,date_edition&CQL_FILTER=code_mission='21LHD2GO'"
ATOM="https://data.geopf.fr/telechargement/resource/LiDARHD-NUALID/$DELIVERY"

mkdir -p "$OUT_DIR/atom"
curl --globoff -fsS --retry 5 --retry-delay 5 --max-time 300 -A "$UA" -o "$OUT_DIR/wfs_21LHD2GO.json" "$WFS"
pages="$(curl -fsS --retry 5 --max-time 120 -A "$UA" "$ATOM?limit=50&page=1" | grep -o 'gpf_dl:pagecount="[0-9]*"' | grep -o '[0-9]*')"
echo "atom pages=$pages"
for p in $(seq 1 "$pages"); do
  f="$OUT_DIR/atom/page_$(printf %03d "$p").xml"
  [[ -s "$f" ]] || { sleep 1.5; curl -fsS --retry 5 --retry-delay 5 --max-time 120 -A "$UA" -o "$f" "$ATOM?limit=50&page=$p"; }
done
python3 -I "$RECIPE_DIR/scripts/select_tiles.py" \
  --wfs "$OUT_DIR/wfs_21LHD2GO.json" --atom-dir "$OUT_DIR/atom" --out "$OUT_DIR/sources.tsv"
mkdir -p "$OUT_DIR/headers"
tail -n +2 "$OUT_DIR/sources.tsv" | while IFS=$'\t' read -r tile _nw _pts _size _md5 _d0 _d1 url _rest; do
  f="$OUT_DIR/headers/$tile.hdr"
  [[ -s "$f" ]] || { sleep 1.5; curl -fsS --retry 5 --retry-delay 5 --max-time 60 -A "$UA" -r 0-374 -o "$f" "$url"; }
done
python3 -I "$RECIPE_DIR/scripts/add_header_counts.py" "$OUT_DIR/sources.tsv" "$OUT_DIR/headers"
echo "wrote $OUT_DIR/sources.tsv"
