#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
ID="covid19_google_mobility_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start $ID"
URL="https://storage.googleapis.com/covid19-open-data/v3/mobility.csv"
TGT="$DOWNLOAD_DIR/mobility.csv"
echo "fetch $URL"
if [[ ! -s "$TGT" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TGT.tmp" "$URL"
  mv "$TGT.tmp" "$TGT"
else
  echo "cache_hit $TGT"
fi
python3 - <<PY
from pathlib import Path
import os, json
repo=Path(os.environ.get("REPO_ROOT",Path.cwd()))
dd=repo / os.environ.get("DATA_DIR",".data") / "downloads" / os.environ.get("ID","covid19_google_mobility_f64")
if not dd.exists():
    dd=Path(".data/downloads/covid19_google_mobility_f64")
f=dd/"mobility.csv"
if not f.exists() or f.stat().st_size==0:
    raise SystemExit("missing mobility.csv")
print(f"found {f.stat().st_size} bytes")
# quick check for mobility columns
txt=f.read_text(errors='replace')[:5000]
if "mobility_" not in txt:
    raise SystemExit("no mobility columns")
(dd/"download_inventory.json").write_text(json.dumps({"dataset_id":"covid19_google_mobility_f64","file":f.name,"bytes":f.stat().st_size},indent=2,sort_keys=True)+"\n")
print(f"semantic_validation=ok bytes={f.stat().st_size}")
PY
echo "[$(date -Is)] download done $ID"
