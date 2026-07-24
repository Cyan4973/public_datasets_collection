#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
ID="landsat_scene_cloud_cover_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start $ID"
URL="https://storage.googleapis.com/gcp-public-data-landsat/index.csv.gz"
TGT="$DOWNLOAD_DIR/index.csv.gz"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-800000000}"
echo "fetch $URL"
if [[ ! -s "$TGT" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -A "openzl-public-datasets/1.0" -o "$TGT.tmp" "$URL"
  mv "$TGT.tmp" "$TGT"
else
  echo "cache_hit $TGT"
fi
python3 - <<PY
from pathlib import Path
import os, json, gzip
repo=Path(os.environ.get("REPO_ROOT",Path.cwd()))
dd=repo/Path(os.environ.get("DATA_DIR",".data"))/f"downloads/{os.environ.get('ID','landsat_scene_cloud_cover_f64')}"
if not dd.exists():
    dd=Path(".data/downloads/landsat_scene_cloud_cover_f64")
f=dd/"index.csv.gz"
if not f.exists():
    raise SystemExit("missing index.csv.gz")
print(f"bytes={f.stat().st_size}")
# peek first lines
import gzip
with gzip.open(f,'rt',errors='replace') as gz:
    header=gz.readline()
    print(f"header={header[:300]}")
    if "CLOUD_COVER" not in header:
        raise SystemExit("no CLOUD_COVER column")
(dd/"download_inventory.json").write_text(json.dumps({"dataset_id":"landsat_scene_cloud_cover_f64","file":f.name,"bytes":f.stat().st_size},indent=2,sort_keys=True)+"\n")
print("semantic_validation=ok")
PY
echo "[$(date -Is)] download done $ID"
