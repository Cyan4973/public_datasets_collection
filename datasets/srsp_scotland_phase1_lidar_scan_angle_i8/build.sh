#!/usr/bin/env bash
# Local-only build: decode the pinned Phase I LAZ tiles and emit one raw int8
# scan-angle-rank array per tile.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="srsp_scotland_phase1_lidar_scan_angle_i8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TILES="$RECIPE_DIR/scripts/tiles.tsv"
WORKERS="${SRSP_WORKERS:-$(python3 -c 'import os; print(min(16, os.cpu_count() or 1))')}"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
exec > >(tee "$LOG_FILE" "$LOG_DIR/build.latest.log") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID workers=$WORKERS"
if [ ! -f "$DOWNLOAD_DIR/download_inventory.json" ]; then
  echo "missing $DOWNLOAD_DIR/download_inventory.json; run download.sh first" >&2
  exit 1
fi
python3 -I - "$TILES" "$DOWNLOAD_DIR" <<'PY'
import csv, json, sys
from pathlib import Path
tiles = list(csv.DictReader(open(sys.argv[1], newline=""), delimiter="\t"))
inv = json.loads((Path(sys.argv[2]) / "download_inventory.json").read_text())
by_key = {r["key"]: r for r in inv["records"]}
for t in tiles:
    r = by_key.get(t["key"])
    if r is None:
        raise SystemExit(f"tile not in download inventory: {t['key']}")
    p = Path(sys.argv[2]) / r["local_path"]
    if not p.is_file() or p.stat().st_size != int(t["size_bytes"]):
        raise SystemExit(f"local tile missing or resized: {p}")
    if t.get("sha256") and t["sha256"] != r["sha256"]:
        raise SystemExit(f"inventory sha256 differs from pinned sha256: {t['key']}")
print(f"inventory ok tiles={len(tiles)}")
PY

python3 -I "$RECIPE_DIR/scripts/extract_scan_angle.py" "$TILES" "$DATA_ROOT" "$REPO_ROOT" "$WORKERS"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
