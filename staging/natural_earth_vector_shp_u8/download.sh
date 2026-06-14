#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="natural_earth_vector_shp_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
ZIP_DIR="$DOWNLOAD_DIR/zips"
mkdir -p "$ZIP_DIR"
cat > "$DOWNLOAD_DIR/resources.tsv" <<'EOF'
layer	url
ne_10m_admin_0_countries	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip
ne_10m_admin_1_states_provinces	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip
ne_10m_populated_places	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places.zip
ne_10m_roads	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_roads.zip
ne_10m_railroads	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_railroads.zip
ne_10m_ports	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_ports.zip
ne_10m_airports	https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_airports.zip
ne_10m_land	https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip
ne_10m_ocean	https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_ocean.zip
ne_10m_lakes	https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip
ne_10m_rivers_lake_centerlines	https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_rivers_lake_centerlines.zip
ne_10m_coastline	https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_coastline.zip
EOF

tail -n +2 "$DOWNLOAD_DIR/resources.tsv" | while IFS=$'\t' read -r layer url; do
  curl -fL --retry 3 --retry-delay 2 -o "$ZIP_DIR/$layer.zip" "$url"
done

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import os
import zipfile
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
zips = sorted((download_dir / "zips").glob("*.zip"))
if len(zips) < 10:
    raise SystemExit(f"too few Natural Earth ZIPs: {len(zips)}")
for path in zips:
    with zipfile.ZipFile(path) as zf:
        shp = [name for name in zf.namelist() if name.lower().endswith(".shp")]
        if len(shp) != 1:
            raise SystemExit(f"{path.name}: expected exactly one .shp member, found {shp}")
        if zf.getinfo(shp[0]).file_size < 1024:
            raise SystemExit(f"{path.name}: .shp member too small")
print(f"semantic_validation=ok zip_files={len(zips)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
