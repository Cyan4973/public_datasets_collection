#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_fits_sample_image_planes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

DEFAULT_URLS="https://fits.gsfc.nasa.gov/samples/UITfuv2582gc.fits,https://fits.gsfc.nasa.gov/samples/WFPC2u5780205r_c0fx.fits,https://fits.gsfc.nasa.gov/samples/IUElwp25637mxlo.fits"
URLS_CSV="${NASA_FITS_URLS:-$DEFAULT_URLS}"
URLS_FILE="${NASA_FITS_URLS_FILE:-}"
MAX_FILE_BYTES="${NASA_FITS_MAX_FILE_BYTES:-200000000}"
MAX_TOTAL_BYTES="${NASA_FITS_MAX_TOTAL_BYTES:-600000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

export URLS_CSV URLS_FILE PLAN
python3 - <<'PY'
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from urllib.parse import urlparse

urls: list[str] = []
urls_file = os.environ["URLS_FILE"]
if urls_file:
    for raw in Path(urls_file).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#"):
            urls.append(raw)
else:
    urls.extend(token.strip() for token in os.environ["URLS_CSV"].split(",") if token.strip())

deduped: list[str] = []
seen: set[str] = set()
for url in urls:
    if not (url.startswith("https://") or url.startswith("http://")):
        raise SystemExit(f"unsupported URL scheme: {url}")
    if url not in seen:
        deduped.append(url)
        seen.add(url)
if not deduped:
    raise SystemExit("no FITS URLs selected")

with Path(os.environ["PLAN"]).open("w", encoding="utf-8", newline="") as fh:
    writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
    writer.writerow(["sample_id", "url", "local_path"])
    for idx, url in enumerate(deduped, 1):
        name = Path(urlparse(url).path).name or f"fits_{idx}.fits"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        if not safe.lower().endswith((".fits", ".fit", ".fits.gz", ".fit.gz", ".fits.bz2", ".fit.bz2")):
            safe = f"{safe}.fits"
        writer.writerow([f"fits_{idx:03d}", url, f"fits/{idx:03d}_{safe}"])
print(f"selected_files={len(deduped)}")
PY

total=0
while IFS=$'\t' read -r sample_id url local_path; do
  [ "$sample_id" != "sample_id" ] || continue
  [ -n "$sample_id" ] || continue
  target="$DOWNLOAD_DIR/$local_path"
  mkdir -p "$(dirname "$target")"
  if [ -s "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    bytes="$(wc -c < "$target" | tr -d ' ')"
    echo "fits cache_hit sample_id=$sample_id bytes=$bytes"
  else
    echo "fetch_fits sample_id=$sample_id url=$url"
    curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      --speed-limit 1024 --speed-time 180 \
      -A "$UA" -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
    bytes="$(wc -c < "$target" | tr -d ' ')"
  fi
  total=$((total + bytes))
  if [ "$total" -gt "$MAX_TOTAL_BYTES" ]; then
    echo "downloaded bytes exceed cap: $total > $MAX_TOTAL_BYTES" >&2
    exit 1
  fi
done < "$PLAN"

export DATASET_ID DOWNLOAD_DIR PLAN MAX_FILE_BYTES MAX_TOTAL_BYTES
python3 - <<'PY'
from __future__ import annotations

import bz2
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_prefix(path: Path) -> bytes:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            return fh.read(2880)
    if suffixes.endswith(".bz2"):
        with bz2.open(path, "rb") as fh:
            return fh.read(2880)
    with path.open("rb") as fh:
        return fh.read(2880)


records = []
with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        path = download_dir / row["local_path"]
        if not path.is_file():
            raise SystemExit(f"missing FITS file: {path}")
        size = path.stat().st_size
        if size > int(os.environ["MAX_FILE_BYTES"]):
            raise SystemExit(f"{row['sample_id']}: exceeds per-file cap: {size}")
        try:
            prefix = read_prefix(path)
        except Exception as exc:
            raise SystemExit(f"{row['sample_id']}: cannot decompress/read FITS prefix: {exc}") from exc
        if len(prefix) < 80 or not (prefix.startswith(b"SIMPLE  =") or prefix.startswith(b"XTENSION=")):
            raise SystemExit(f"{row['sample_id']}: does not start with a FITS HDU header")
        records.append(
            {
                "sample_id": row["sample_id"],
                "url": row["url"],
                "local_path": row["local_path"],
                "source_bytes": size,
                "sha256": sha256_file(path),
            }
        )

inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "record_count": len(records),
    "source_bytes": sum(record["source_bytes"] for record in records),
    "records": records,
}
if inventory["source_bytes"] > int(os.environ["MAX_TOTAL_BYTES"]):
    raise SystemExit(f"downloaded bytes exceed cap: {inventory['source_bytes']}")
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
