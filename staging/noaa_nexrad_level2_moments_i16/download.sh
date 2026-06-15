#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_nexrad_level2_moments_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
BUCKET_URL="${BUCKET_URL:-https://noaa-nexrad-level2.s3.amazonaws.com/}"
STATION="${STATION:-KTLX}"
DATE_YYYYMMDD="${DATE_YYYYMMDD:-20240520}"
FILE_LIMIT="${FILE_LIMIT:-8}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-200000000}"
YEAR="${DATE_YYYYMMDD:0:4}"
MONTH="${DATE_YYYYMMDD:4:2}"
DAY="${DATE_YYYYMMDD:6:2}"
PREFIX="$YEAR/$MONTH/$DAY/$STATION/"
LISTING="$DOWNLOAD_DIR/listing.xml"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
NEXRAD_KEYS_FILE="${NEXRAD_KEYS_FILE:-}"

if [[ -n "$NEXRAD_KEYS_FILE" ]]; then
  cp "$NEXRAD_KEYS_FILE" "$DOWNLOAD_DIR/keys.txt"
  export NEXRAD_KEYS_PATH="$DOWNLOAD_DIR/keys.txt"
else
  if ! curl -fL --retry 3 --retry-delay 5 -o "$LISTING" "${BUCKET_URL}?list-type=2&prefix=${PREFIX}"; then
    cat >&2 <<EOF
NEXRAD prefix listing failed for ${PREFIX}.
This bucket may deny ListBucket from this environment. Provide exact object keys
with NEXRAD_KEYS_FILE=/path/to/keys.txt, one key per line, then rerun.
EOF
    exit 1
  fi
fi

export LISTING PLAN BUCKET_URL PREFIX STATION DATE_YYYYMMDD FILE_LIMIT NEXRAD_KEYS_PATH="${NEXRAD_KEYS_PATH:-}"
python3 - <<'PY'
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

listing = Path(os.environ["LISTING"])
plan = Path(os.environ["PLAN"])
bucket_url = os.environ["BUCKET_URL"]
prefix = os.environ["PREFIX"]
station = os.environ["STATION"]
date = os.environ["DATE_YYYYMMDD"]
limit = int(os.environ["FILE_LIMIT"])
keys = []
keys_path = os.environ.get("NEXRAD_KEYS_PATH")
if keys_path:
    candidates = [line.strip() for line in Path(keys_path).read_text(encoding="utf-8").splitlines()]
else:
    root = ET.fromstring(listing.read_bytes())
    candidates = [elem.text for elem in root.iter() if elem.tag.endswith("Key") and elem.text]
for key in candidates:
    if key:
        name = Path(key).name
        if key.startswith(prefix) and station in name and date in name and "MDM" not in name:
            if re.search(r"_V0[0-9]($|[._])", name):
                keys.append(key)
keys = sorted(set(keys))[:limit]
if not keys:
    raise SystemExit(f"no NEXRAD Level-II volume keys found for prefix {prefix}")
with plan.open("w", encoding="utf-8") as fh:
    for key in keys:
        url = bucket_url.rstrip("/") + "/" + quote(key)
        fh.write(f"{Path(key).name}\t{key}\t{url}\n")
print(f"selected_files={len(keys)} first={Path(keys[0]).name} last={Path(keys[-1]).name}")
PY

while IFS=$'\t' read -r name key url; do
  [[ -n "$name" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -o "$target" "$url"
  fi
done < "$PLAN"

export DOWNLOAD_DIR PLAN MAX_FILE_BYTES STATION DATE_YYYYMMDD
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
records = []
for line in plan.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    name, key, url = line.split("\t")
    path = download_dir / name
    size = path.stat().st_size
    if size < 100_000:
        raise SystemExit(f"{name}: too small for Level-II archive: {size}")
    if size > max_file_bytes:
        raise SystemExit(f"{name}: exceeds per-file cap: {size}")
    prefix = path.read_bytes()[:64]
    if b"AR2V" not in prefix and b"ARCHIVE2" not in prefix:
        raise SystemExit(f"{name}: missing expected NEXRAD archive marker in prefix")
    records.append({"file": name, "key": key, "url": url, "source_bytes": size})
inventory = {
    "dataset_id": "noaa_nexrad_level2_moments_i16",
    "station": os.environ["STATION"],
    "date": os.environ["DATE_YYYYMMDD"],
    "record_count": len(records),
    "source_bytes": sum(row["source_bytes"] for row in records),
    "records": records,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
