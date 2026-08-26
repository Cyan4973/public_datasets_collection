#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_geomag_observatory_minute_f32"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
RIGHTS_URL="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"
RIGHTS_FILE="$DOWNLOAD_DIR/usgs_copyrights_and_credits.html"
if [[ ! -s "$RIGHTS_FILE" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  curl --fail-with-body --silent --show-error --location \
    --retry 4 --retry-delay 3 --max-time 180 --max-filesize 5000000 \
    --user-agent "openzl-public-datasets-usgs-geomag-f32/1.0" \
    --output "$RIGHTS_FILE.part" "$RIGHTS_URL"
  mv "$RIGHTS_FILE.part" "$RIGHTS_FILE"
fi
if ! python3 - "$RIGHTS_FILE" <<'PY'
from pathlib import Path
import html
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"(?s)<[^>]+>", " ", text)
text = re.sub(r"\s+", " ", html.unescape(text)).lower()
required = "usgs-authored or produced data and information are considered to be in the u.s. public domain"
if required not in text:
    raise SystemExit("official USGS public-domain statement not found")
print("rights_validation=ok")
PY
then
  exit 1
fi

python3 "$RECIPE_DIR/scripts/geomag.py" make-plan \
  --output "$DOWNLOAD_DIR/download_plan.tsv"
python3 "$RECIPE_DIR/scripts/geomag.py" fetch \
  --download-dir "$DOWNLOAD_DIR" \
  --force "${FORCE_DOWNLOAD:-0}"

python3 "$RECIPE_DIR/scripts/geomag.py" validate-download \
  --download-dir "$DOWNLOAD_DIR" \
  --inventory "$DOWNLOAD_DIR/download_inventory.json"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
