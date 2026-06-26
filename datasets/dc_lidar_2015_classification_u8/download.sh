#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dc_lidar_2015_classification_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BUCKET_URL="${DC_LIDAR_BUCKET_URL:-https://dc-lidar-2015.s3.amazonaws.com/}"
PREFIX="${DC_LIDAR_PREFIX:-Classified_LAS/}"
FILE_LIMIT="${DC_LIDAR_FILE_LIMIT:-3}"
MAX_FILE_BYTES="${DC_LIDAR_MAX_FILE_BYTES:-500000000}"
MAX_TOTAL_BYTES="${DC_LIDAR_MAX_TOTAL_BYTES:-800000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
LISTING="$DOWNLOAD_DIR/listing.xml"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

if [ -z "${DC_LIDAR_URLS_FILE:-}" ] && [ -z "${DC_LIDAR_KEYS_FILE:-}" ]; then
  echo "list_prefix bucket=$BUCKET_URL prefix=$PREFIX"
  curl --globoff -fL --retry 3 --retry-delay 5 \
    -A "$UA" -o "$LISTING" \
    "${BUCKET_URL}?list-type=2&prefix=${PREFIX}&max-keys=1000"
fi

if [ -n "${DC_LIDAR_URLS_FILE:-}" ]; then
  cp "$DC_LIDAR_URLS_FILE" "$DOWNLOAD_DIR/input_urls.txt"
  export DC_LIDAR_URLS_PATH="$DOWNLOAD_DIR/input_urls.txt"
fi
if [ -n "${DC_LIDAR_KEYS_FILE:-}" ]; then
  cp "$DC_LIDAR_KEYS_FILE" "$DOWNLOAD_DIR/input_keys.txt"
  export DC_LIDAR_KEYS_PATH="$DOWNLOAD_DIR/input_keys.txt"
fi

export BUCKET_URL PREFIX FILE_LIMIT MAX_FILE_BYTES MAX_TOTAL_BYTES PLAN LISTING DOWNLOAD_DIR \
  DC_LIDAR_URLS_PATH="${DC_LIDAR_URLS_PATH:-}" DC_LIDAR_KEYS_PATH="${DC_LIDAR_KEYS_PATH:-}"
python3 - <<'PY'
from __future__ import annotations

import csv
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlparse

bucket_url = os.environ["BUCKET_URL"].rstrip("/") + "/"
prefix = os.environ["PREFIX"]
limit = int(os.environ["FILE_LIMIT"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
plan = Path(os.environ["PLAN"])
listing = Path(os.environ["LISTING"])
urls_path = os.environ.get("DC_LIDAR_URLS_PATH")
keys_path = os.environ.get("DC_LIDAR_KEYS_PATH")

rows: list[dict[str, object]] = []
if urls_path:
    for raw in Path(urls_path).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        name = Path(urlparse(raw).path).name
        rows.append({"key": "", "url": raw, "name": name, "declared_bytes": ""})
elif keys_path:
    for raw in Path(keys_path).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        key = parts[0]
        declared = parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
        rows.append({"key": key, "url": bucket_url + quote(key), "name": Path(key).name, "declared_bytes": declared})
else:
    if not listing.exists():
        raise SystemExit(f"missing listing: {listing}")
    root = ET.fromstring(listing.read_bytes())
    for content in root.iter():
        if not content.tag.endswith("Contents"):
            continue
        key = ""
        size = 0
        for child in content:
            if child.tag.endswith("Key") and child.text:
                key = child.text
            elif child.tag.endswith("Size") and child.text:
                size = int(child.text)
        if not key.lower().endswith(".las"):
            continue
        if not key.startswith(prefix):
            continue
        rows.append({"key": key, "url": bucket_url + quote(key), "name": Path(key).name, "declared_bytes": str(size)})
    rows.sort(key=lambda r: (int(r["declared_bytes"] or 0), str(r["key"])))

selected: list[dict[str, object]] = []
running = 0
for row in rows:
    declared = int(row["declared_bytes"] or 0)
    if declared and declared > max_file_bytes:
        continue
    if declared and running + declared > max_total_bytes:
        continue
    selected.append(row)
    running += declared
    if len(selected) >= limit:
        break

if not selected:
    raise SystemExit("no bounded uncompressed .las files selected")

with plan.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
    writer.writerow(["name", "key", "url", "declared_bytes", "local_path"])
    for row in selected:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(row["name"]))
        writer.writerow([safe_name, row["key"], row["url"], row["declared_bytes"], f"las/{safe_name}"])
print(
    f"selected_files={len(selected)} declared_bytes={running} "
    f"first={selected[0]['name']} last={selected[-1]['name']}"
)
PY

while IFS=$'\t' read -r name key url declared_bytes local_path; do
  [ "$name" != "name" ] || continue
  [ -n "$name" ] || continue
  target="$DOWNLOAD_DIR/$local_path"
  mkdir -p "$(dirname "$target")"
  if [ -s "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "las cache_hit name=$name bytes=$(wc -c < "$target" | tr -d ' ')"
  else
    echo "fetch_las name=$name declared_bytes=${declared_bytes:-unknown} url=$url"
    curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      --speed-limit 1024 --speed-time 300 \
      -A "$UA" -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
  fi
done < "$PLAN"

export DATASET_ID DOWNLOAD_DIR PLAN MAX_FILE_BYTES MAX_TOTAL_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
import struct
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
records = []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        path = download_dir / row["local_path"]
        if not path.is_file():
            raise SystemExit(f"missing LAS {path}")
        size = path.stat().st_size
        if size > max_file_bytes:
            raise SystemExit(f"{row['name']}: exceeds per-file cap: {size}")
        with path.open("rb") as src:
            header = src.read(375)
        if len(header) < 227 or header[:4] != b"LASF":
            raise SystemExit(f"{row['name']}: not an uncompressed LAS file")
        point_offset = struct.unpack_from("<I", header, 96)[0]
        point_format = header[104] & 0x3F
        record_length = struct.unpack_from("<H", header, 105)[0]
        legacy_count = struct.unpack_from("<I", header, 107)[0]
        point_count = legacy_count
        if len(header) >= 255 and point_count == 0:
            point_count = struct.unpack_from("<Q", header, 247)[0]
        if point_format > 10 or record_length < 20 or point_count <= 0:
            raise SystemExit(f"{row['name']}: unsupported LAS point layout")
        if point_offset + point_count * record_length > size:
            raise SystemExit(f"{row['name']}: point records exceed file size")
        records.append({
            "name": row["name"],
            "key": row["key"],
            "url": row["url"],
            "local_path": row["local_path"],
            "source_bytes": size,
            "sha256": sha256_file(path),
            "point_format": point_format,
            "point_record_length": record_length,
            "point_count": point_count,
        })
inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "record_count": len(records),
    "source_bytes": sum(r["source_bytes"] for r in records),
    "records": records,
}
if inventory["source_bytes"] > max_total_bytes:
    raise SystemExit(f"downloaded bytes exceed cap: {inventory['source_bytes']}")
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
