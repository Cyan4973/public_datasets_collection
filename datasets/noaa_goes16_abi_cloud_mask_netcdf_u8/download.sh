#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_goes16_abi_cloud_mask_netcdf_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BUCKET_URL="${GOES_GCS_BUCKET_URL:-https://storage.googleapis.com/gcp-public-data-goes-16}"
PRODUCT="${GOES_PRODUCT:-ABI-L2-ACMF}"
YEAR="${GOES_YEAR:-2024}"
DAY="${GOES_DAY:-001}"
HOURS="${GOES_HOURS:-00 01 02 03}"
MAX_FILES="${GOES_MAX_FILES:-24}"
MIN_FILES="${GOES_MIN_FILES:-12}"
MIN_TOTAL_BYTES="${GOES_MIN_TOTAL_BYTES:-250000000}"
MAX_TOTAL_BYTES="${GOES_MAX_TOTAL_BYTES:-850000000}"
MAX_FILE_BYTES="${GOES_MAX_FILE_BYTES:-50000000}"
HARD_MAX_TOTAL_BYTES=1000000000
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
LISTING_DIR="$DOWNLOAD_DIR/listings"
mkdir -p "$LISTING_DIR"

if (( MAX_TOTAL_BYTES > HARD_MAX_TOTAL_BYTES )); then
  echo "requested total source size $MAX_TOTAL_BYTES exceeds hard cap $HARD_MAX_TOTAL_BYTES; clamping"
  MAX_TOTAL_BYTES="$HARD_MAX_TOTAL_BYTES"
fi

: > "$FAILURES"
export BUCKET_URL PRODUCT YEAR DAY HOURS MAX_FILES MIN_FILES MIN_TOTAL_BYTES MAX_TOTAL_BYTES MAX_FILE_BYTES PLAN LISTING_DIR
python3 - <<'PY'
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


def apply_curlrc_proxy_fallback() -> None:
    """urllib ignores ~/.curlrc; use its proxy when no proxy env is set."""
    if any(os.environ.get(name) for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        return
    curlrc = Path.home() / ".curlrc"
    if not curlrc.exists():
        return
    for raw in curlrc.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("proxy="):
            proxy = line.split("=", 1)[1].strip().strip('"')
            if proxy:
                os.environ["http_proxy"] = proxy
                os.environ["https_proxy"] = proxy
        elif line.startswith("noproxy="):
            no_proxy = line.split("=", 1)[1].strip().strip('"')
            if no_proxy:
                os.environ.setdefault("no_proxy", no_proxy)


apply_curlrc_proxy_fallback()
bucket = os.environ["BUCKET_URL"].rstrip("/")
product = os.environ["PRODUCT"]
year = os.environ["YEAR"]
day = os.environ["DAY"]
hours = os.environ["HOURS"].split()
max_files = int(os.environ["MAX_FILES"])
min_files = int(os.environ["MIN_FILES"])
min_total_bytes = int(os.environ["MIN_TOTAL_BYTES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
plan = Path(os.environ["PLAN"])
listing_dir = Path(os.environ["LISTING_DIR"])

objects: list[tuple[str, int, str]] = []
namespace = "{http://doc.s3.amazonaws.com/2006-03-01}"
for hour in hours:
    prefix = f"{product}/{year}/{day}/{hour}/"
    query = urllib.parse.urlencode({"list-type": "2", "prefix": prefix, "max-keys": "1000"})
    url = f"{bucket}?{query}"
    print(f"list_prefix prefix={prefix} url={url}")
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        body = response.read()
    (listing_dir / f"{product}_{year}_{day}_{hour}.xml").write_bytes(body)
    root = ET.fromstring(body)
    if not root.tag.startswith(namespace):
        namespace = ""
    for item in root.findall(f"{namespace}Contents"):
        key_el = item.find(f"{namespace}Key")
        size_el = item.find(f"{namespace}Size")
        etag_el = item.find(f"{namespace}ETag")
        if key_el is None or size_el is None or not key_el.text:
            continue
        key = key_el.text
        if not key.endswith(".nc"):
            continue
        size = int(size_el.text or "0")
        if size <= 0 or size > max_file_bytes:
            continue
        etag = (etag_el.text or "").strip('"') if etag_el is not None else ""
        objects.append((key, size, etag))

objects = sorted(dict((key, (size, etag)) for key, size, etag in objects).items())
selected: list[tuple[str, int, str]] = []
total = 0
for key, (size, etag) in objects:
    if len(selected) >= max_files:
        break
    if total + size > max_total_bytes:
        break
    selected.append((key, size, etag))
    total += size

if len(selected) < min_files:
    raise SystemExit(f"too few GOES NetCDF objects selected: {len(selected)} < {min_files}")
if total < min_total_bytes:
    raise SystemExit(f"selected GOES bytes below floor: {total} < {min_total_bytes}")
if total > max_total_bytes:
    raise SystemExit(f"selected GOES bytes exceed cap: {total} > {max_total_bytes}")

with plan.open("w", encoding="utf-8") as fh:
    fh.write("source_id\turl\tkey\texpected_bytes\tetag\n")
    for key, size, etag in selected:
        source_id = Path(key).stem
        url = f"{bucket}/{urllib.parse.quote(key, safe='/')}"
        fh.write(f"{source_id}\t{url}\t{key}\t{size}\t{etag}\n")
print(f"planned_files={len(selected)} planned_bytes={total}")
PY

failure_count=0
while IFS=$'\t' read -r source_id url key expected_bytes etag; do
  [[ "$source_id" != "source_id" ]] || continue
  target="$DOWNLOAD_DIR/${source_id}.nc"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit source=$source_id bytes=$(wc -c < "$target" | tr -d ' ')"
  else
    echo "fetch source=$source_id url=$url"
    if ! curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
      -o "$target.tmp" "$url"; then
      rm -f "$target.tmp"
      printf '%s\t%s\tcurl_failed\n' "$source_id" "$url" >> "$FAILURES"
      failure_count=$((failure_count + 1))
      continue
    fi
    mv "$target.tmp" "$target"
  fi
  actual_bytes="$(wc -c < "$target" | tr -d ' ')"
  if [[ "$actual_bytes" != "$expected_bytes" ]]; then
    printf '%s\t%s\tsize_mismatch:%s:%s\n' "$source_id" "$url" "$actual_bytes" "$expected_bytes" >> "$FAILURES"
    failure_count=$((failure_count + 1))
    continue
  fi
done < "$PLAN"

if (( failure_count != 0 )); then
  echo "download failures recorded in $FAILURES" >&2
  exit 1
fi

export DOWNLOAD_DIR PLAN MIN_FILES MIN_TOTAL_BYTES MAX_TOTAL_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
min_files = int(os.environ["MIN_FILES"])
min_total_bytes = int(os.environ["MIN_TOTAL_BYTES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
records = []
total_bytes = 0

for line in plan.read_text(encoding="utf-8").splitlines()[1:]:
    if not line.strip():
        continue
    source_id, url, key, expected_bytes, etag = line.split("\t")
    path = download_dir / f"{source_id}.nc"
    if not path.is_file():
        raise SystemExit(f"missing downloaded NetCDF file: {path}")
    size = path.stat().st_size
    if size != int(expected_bytes):
        raise SystemExit(f"{path}: size mismatch {size} != {expected_bytes}")
    with path.open("rb") as fh:
        head = fh.read(8)
    if not (head.startswith(b"CDF") or head == b"\x89HDF\r\n\x1a\n"):
        raise SystemExit(f"{path}: not NetCDF classic or NetCDF4/HDF5")
    records.append({
        "source_id": source_id,
        "url": url,
        "key": key,
        "bytes": size,
        "etag": etag,
        "container_header": "hdf5" if head == b"\x89HDF\r\n\x1a\n" else "netcdf_classic",
    })
    total_bytes += size

if len(records) < min_files:
    raise SystemExit(f"too few downloaded GOES files: {len(records)} < {min_files}")
if total_bytes < min_total_bytes:
    raise SystemExit(f"downloaded bytes below floor: {total_bytes} < {min_total_bytes}")
if total_bytes > max_total_bytes:
    raise SystemExit(f"downloaded bytes exceed cap: {total_bytes} > {max_total_bytes}")

inventory = {
    "dataset_id": "noaa_goes16_abi_cloud_mask_netcdf_u8",
    "bucket_url": os.environ["BUCKET_URL"],
    "product": os.environ["PRODUCT"],
    "year": os.environ["YEAR"],
    "day": os.environ["DAY"],
    "hours": os.environ["HOURS"].split(),
    "file_count": len(records),
    "downloaded_bytes": total_bytes,
    "records": records,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok files={len(records)} downloaded_bytes={total_bytes}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
