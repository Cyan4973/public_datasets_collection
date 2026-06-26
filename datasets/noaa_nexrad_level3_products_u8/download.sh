#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_nexrad_level3_products_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BUCKET_URL="${NEXRAD_L3_BUCKET_URL:-https://unidata-nexrad-level3.s3.amazonaws.com/}"
STATION="${NEXRAD_L3_STATION:-ABC}"
DATE_YYYYMMDD="${NEXRAD_L3_DATE_YYYYMMDD:-20200408}"
PRODUCT_CODE="${NEXRAD_L3_PRODUCT_CODE:-N0Q}"
FILE_LIMIT="${NEXRAD_L3_FILE_LIMIT:-96}"
MAX_FILE_BYTES="${NEXRAD_L3_MAX_FILE_BYTES:-25000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
YEAR="${DATE_YYYYMMDD:0:4}"
MONTH="${DATE_YYYYMMDD:4:2}"
DAY="${DATE_YYYYMMDD:6:2}"
JDAY="$(date -u -d "${YEAR}-${MONTH}-${DAY}" +%j)"
PREFIX="${NEXRAD_L3_PREFIX:-}"
LISTING="$DOWNLOAD_DIR/listing.xml"
LISTINGS_DIR="$DOWNLOAD_DIR/listings"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
mkdir -p "$LISTINGS_DIR"

if [ -n "${NEXRAD_L3_URLS_FILE:-}" ]; then
  cp "$NEXRAD_L3_URLS_FILE" "$DOWNLOAD_DIR/input_urls.tsv"
  export NEXRAD_L3_URLS_PATH="$DOWNLOAD_DIR/input_urls.tsv"
elif [ -n "${NEXRAD_L3_KEYS_FILE:-}" ]; then
  cp "$NEXRAD_L3_KEYS_FILE" "$DOWNLOAD_DIR/input_keys.txt"
  export NEXRAD_L3_KEYS_PATH="$DOWNLOAD_DIR/input_keys.txt"
else
  : > "$DOWNLOAD_DIR/attempted_prefixes.txt"
  if [ -n "$PREFIX" ]; then
    PREFIXES=("$PREFIX")
  else
    PREFIXES=(
      "${STATION}_${PRODUCT_CODE}_${YEAR}_${MONTH}_${DAY}"
      "${STATION}_${PRODUCT_CODE}_${DATE_YYYYMMDD}"
      "${STATION}_${PRODUCT_CODE}_${YEAR}-${MONTH}-${DAY}"
      "${STATION}-${PRODUCT_CODE}-${YEAR}-${MONTH}-${DAY}"
      "NEXRAD3/${YEAR}/${JDAY}/${STATION}/${PRODUCT_CODE}/"
      "NEXRAD3/${YEAR}/${MONTH}/${DAY}/${STATION}/${PRODUCT_CODE}/"
      "NEXRAD3/${DATE_YYYYMMDD}/${STATION}/${PRODUCT_CODE}/"
      "NEXRAD3/${PRODUCT_CODE}/${STATION}/${YEAR}/${MONTH}/${DAY}/"
      "NEXRAD3/${PRODUCT_CODE}/${STATION}/${DATE_YYYYMMDD}/"
      "${PRODUCT_CODE}/${STATION}/${YEAR}/${MONTH}/${DAY}/"
      "${STATION}/${PRODUCT_CODE}/${YEAR}/${MONTH}/${DAY}/"
      "${YEAR}/${MONTH}/${DAY}/${STATION}/${PRODUCT_CODE}/"
    )
  fi
  for candidate in "${PREFIXES[@]}"; do
    safe="$(printf '%s' "$candidate" | tr '/:' '__')"
    out="$LISTINGS_DIR/${safe}.xml"
    echo "$candidate" >> "$DOWNLOAD_DIR/attempted_prefixes.txt"
    echo "list_prefix prefix=$candidate bucket=$BUCKET_URL"
    if curl --globoff -fL --retry 3 --retry-delay 5 \
      -A "$UA" -o "$out" "${BUCKET_URL}?list-type=2&prefix=${candidate}"; then
      cp "$out" "$LISTING"
    else
      echo "prefix_listing_failed prefix=$candidate"
    fi
  done
fi

export BUCKET_URL STATION DATE_YYYYMMDD PRODUCT_CODE FILE_LIMIT PREFIX PLAN LISTING \
  LISTINGS_DIR DOWNLOAD_DIR NEXRAD_L3_URLS_PATH="${NEXRAD_L3_URLS_PATH:-}" NEXRAD_L3_KEYS_PATH="${NEXRAD_L3_KEYS_PATH:-}"
python3 - <<'PY'
from __future__ import annotations

import csv
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

bucket_url = os.environ["BUCKET_URL"].rstrip("/") + "/"
station = os.environ["STATION"].upper()
date = os.environ["DATE_YYYYMMDD"]
product = os.environ["PRODUCT_CODE"].upper()
limit = int(os.environ["FILE_LIMIT"])
prefix = os.environ["PREFIX"]
plan = Path(os.environ["PLAN"])
listing = Path(os.environ["LISTING"])
listings_dir = Path(os.environ["LISTINGS_DIR"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
urls_path = os.environ.get("NEXRAD_L3_URLS_PATH")
keys_path = os.environ.get("NEXRAD_L3_KEYS_PATH")

rows: list[dict[str, str]] = []
if urls_path:
    with Path(urls_path).open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            name = (row.get("name") or Path(row.get("url", "")).name).strip()
            url = (row.get("url") or "").strip()
            row_product = (row.get("product_code") or product).strip().upper()
            if name and url:
                rows.append({"name": name, "key": "", "url": url, "product_code": row_product})
elif keys_path:
    keys = [line.strip() for line in Path(keys_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for key in keys:
        name = Path(key).name
        rows.append({"name": name, "key": key, "url": bucket_url + quote(key), "product_code": product})
else:
    listing_paths = sorted(listings_dir.glob("*.xml"))
    if listing.exists() and listing not in listing_paths:
        listing_paths.append(listing)
    keys = []
    for listing_path in listing_paths:
        root = ET.fromstring(listing_path.read_bytes())
        keys.extend(elem.text for elem in root.iter() if elem.tag.endswith("Key") and elem.text)
    for key in keys:
        name = Path(key).name
        if prefix and not key.startswith(prefix):
            continue
        if station not in key.upper() and station not in name.upper():
            continue
        if product not in key.upper() and product not in name.upper():
            continue
        rows.append({"name": name, "key": key, "url": bucket_url + quote(key), "product_code": product})

date_re = re.compile(re.escape(date))
filtered = []
for row in rows:
    haystack = f"{row['name']} {row['key']} {row['url']}".upper()
    if row["product_code"].upper() != product:
        continue
    if product not in haystack:
        continue
    if station not in haystack:
        continue
    if not date_re.search(haystack.replace("-", "").replace("_", "")):
        # Exact URL lists from some archives omit YYYYMMDD in the file name; keep them
        # only when the user explicitly supplied URLs.
        if not urls_path:
            continue
    filtered.append(row)

filtered = sorted({(r["name"], r["url"]): r for r in filtered}.values(), key=lambda r: (r["name"], r["url"]))[:limit]
if not filtered:
    attempted = []
    attempted_path = download_dir / "attempted_prefixes.txt"
    if attempted_path.exists():
        attempted = [line.strip() for line in attempted_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    raise SystemExit(
        f"no Level-III {product} files selected for station={station} date={date}; "
        f"attempted_prefixes={attempted}; provide NEXRAD_L3_URLS_FILE or NEXRAD_L3_KEYS_FILE"
    )

with plan.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
    writer.writerow(["name", "product_code", "key", "url", "local_path"])
    for row in filtered:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", row["name"])
        writer.writerow([safe_name, row["product_code"].upper(), row["key"], row["url"], f"products/{safe_name}"])
print(f"selected_files={len(filtered)} first={filtered[0]['name']} last={filtered[-1]['name']}")
PY

while IFS=$'\t' read -r name product_code key url local_path; do
  [ "$name" != "name" ] || continue
  [ -n "$name" ] || continue
  target="$DOWNLOAD_DIR/$local_path"
  mkdir -p "$(dirname "$target")"
  if [ -s "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "product cache_hit name=$name bytes=$(wc -c < "$target" | tr -d ' ')"
  else
    echo "fetch_product name=$name product=$product_code url=$url"
    curl --globoff -fL --retry 5 --retry-delay 3 --max-filesize "$MAX_FILE_BYTES" \
      --speed-limit 1024 --speed-time 120 \
      -A "$UA" -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
  fi
done < "$PLAN"

export DOWNLOAD_DIR PLAN MAX_FILE_BYTES DATASET_ID PRODUCT_CODE STATION DATE_YYYYMMDD
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
records = []
with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        path = download_dir / row["local_path"]
        if not path.is_file():
            raise SystemExit(f"missing product {path}")
        data = path.read_bytes()
        size = len(data)
        if size < 1_000:
            raise SystemExit(f"{row['name']}: too small for Level-III product: {size}")
        if size > max_file_bytes:
            raise SystemExit(f"{row['name']}: exceeds per-file cap: {size}")
        if len(set(data[: min(size, 4096)])) <= 1:
            raise SystemExit(f"{row['name']}: degenerate constant prefix")
        records.append({
            "name": row["name"],
            "product_code": row["product_code"],
            "key": row["key"],
            "url": row["url"],
            "local_path": row["local_path"],
            "source_bytes": size,
            "sha256": hashlib.sha256(data).hexdigest(),
        })
inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "station": os.environ["STATION"],
    "date": os.environ["DATE_YYYYMMDD"],
    "product_code": os.environ["PRODUCT_CODE"],
    "record_count": len(records),
    "source_bytes": sum(r["source_bytes"] for r in records),
    "records": records,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
