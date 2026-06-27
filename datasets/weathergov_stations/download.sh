#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="weathergov_stations"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${WEATHERGOV_STATIONS_URL:-https://api.weather.gov/stations?limit=500}"
MAX_PAGES="${WEATHERGOV_MAX_PAGES:-100}"
MAX_FEATURES="${WEATHERGOV_MAX_FEATURES:-50000}"
MIN_FEATURES="${WEATHERGOV_MIN_FEATURES:-1000}"
MAX_TOTAL_BYTES="${WEATHERGOV_MAX_TOTAL_BYTES:-200000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"

if [ -s "$INVENTORY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_FEATURES"
import json
import sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
features = int(obj.get("feature_count", 0))
if features < int(sys.argv[2]):
    raise SystemExit(1)
print(f"inventory cache_hit feature_count={features} page_count={obj.get('page_count')}")
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

rm -rf "$PAGE_DIR.tmp"
mkdir -p "$PAGE_DIR.tmp"

export BASE_URL MAX_PAGES MAX_FEATURES MIN_FEATURES MAX_TOTAL_BYTES PAGE_DIR_TMP="$PAGE_DIR.tmp" UA
python3 - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

url = os.environ["BASE_URL"]
max_pages = int(os.environ["MAX_PAGES"])
max_features = int(os.environ["MAX_FEATURES"])
min_features = int(os.environ["MIN_FEATURES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
page_dir = Path(os.environ["PAGE_DIR_TMP"])
ua = os.environ["UA"]

feature_count = 0
total_bytes = 0
pages = []
seen_urls: set[str] = set()

for page_idx in range(1, max_pages + 1):
    if url in seen_urls:
        raise SystemExit(f"pagination loop detected at {url}")
    seen_urls.add(url)
    out = page_dir / f"page_{page_idx:05d}.json"
    print(f"fetch_page page={page_idx} url={url}")
    subprocess.run(
        [
            "curl",
            "--globoff",
            "-fL",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "-A",
            ua,
            "-H",
            "Accept: application/geo+json",
            "-o",
            str(out),
            url,
        ],
        check=True,
    )
    size = out.stat().st_size
    total_bytes += size
    if total_bytes > max_total_bytes:
        raise SystemExit(f"downloaded bytes exceed cap: {total_bytes} > {max_total_bytes}")
    obj = json.loads(out.read_text(encoding="utf-8"))
    features = obj.get("features")
    if not isinstance(features, list):
        raise SystemExit(f"page {page_idx}: missing features list")
    page_features = len(features)
    feature_count += page_features
    pages.append({"page": page_idx, "local_path": out.name, "feature_count": page_features, "bytes": size, "url": url})
    print(f"page_ok page={page_idx} features={page_features} total_features={feature_count}")
    if feature_count >= max_features:
        break
    next_url = (obj.get("pagination") or {}).get("next")
    if not next_url:
        break
    url = str(next_url)

if feature_count < min_features:
    raise SystemExit(f"only {feature_count} features < WEATHERGOV_MIN_FEATURES={min_features}")

inventory = {
    "dataset_id": "weathergov_stations",
    "base_url": os.environ["BASE_URL"],
    "page_count": len(pages),
    "feature_count": feature_count,
    "source_bytes": total_bytes,
    "pages": pages,
}
(page_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok pages={len(pages)} features={feature_count} source_bytes={total_bytes}")
PY

rm -rf "$PAGE_DIR"
mv "$PAGE_DIR.tmp" "$PAGE_DIR"
cp "$PAGE_DIR/download_inventory.json" "$INVENTORY"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
