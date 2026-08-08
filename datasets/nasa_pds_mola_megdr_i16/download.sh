#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_mola_megdr_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1

BASE_URL="https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg064"
EXPECTED_IMG_BYTES=132710400
EXPECTED_TOTAL_IMG_BYTES=530841600
MAX_FILE_BYTES=140000000
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

printf '%s\t%s\t%s\n' \
  'megt00n000gb' "$BASE_URL/megt00n000gb.lbl" "$BASE_URL/MEGT00N000GB.IMG" \
  'megt00n180gb' "$BASE_URL/megt00n180gb.lbl" "$BASE_URL/MEGT00N180GB.IMG" \
  'megt90n000gb' "$BASE_URL/megt90n000gb.lbl" "$BASE_URL/MEGT90N000GB.IMG" \
  'megt90n180gb' "$BASE_URL/megt90n180gb.lbl" "$BASE_URL/MEGT90N180GB.IMG" \
  > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"
while IFS=$'\t' read -r stem label_url image_url; do
  label="$DOWNLOAD_DIR/$stem.lbl"
  image="$DOWNLOAD_DIR/${stem^^}.IMG"
  if [[ ! -s "$label" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    curl --fail --location --retry 4 --retry-delay 3 --max-time 300 \
      --max-filesize 2000000 --output "$label.part" "$label_url"
    mv "$label.part" "$label"
  else
    echo "cache_hit path=$label"
  fi
  if [[ ! -s "$image" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
    curl --fail --location --retry 4 --retry-delay 5 --max-time 3600 \
      --max-filesize "$MAX_FILE_BYTES" --output "$image.part" "$image_url"
    mv "$image.part" "$image"
  else
    echo "cache_hit path=$image"
  fi
  size="$(wc -c < "$image")"
  if (( size != EXPECTED_IMG_BYTES )); then
    echo "unexpected IMG size path=$image expected=$EXPECTED_IMG_BYTES actual=$size" >&2
    exit 1
  fi
done < "$PLAN"

export DOWNLOAD_DIR EXPECTED_IMG_BYTES EXPECTED_TOTAL_IMG_BYTES
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

download_dir = Path(os.environ["DOWNLOAD_DIR"])
expected_file = int(os.environ["EXPECTED_IMG_BYTES"])
expected_total = int(os.environ["EXPECTED_TOTAL_IMG_BYTES"])
records = []
for label in sorted(download_dir.glob("*.lbl")):
    image = download_dir / f"{label.stem.upper()}.IMG"
    if not image.is_file():
        raise SystemExit(f"missing paired image for {label.name}")
    if image.stat().st_size != expected_file:
        raise SystemExit(f"unexpected image size: {image}")
    text = label.read_text(encoding="ascii", errors="replace").upper()
    required = {
        "IMAGE object": r"(?m)^\s*OBJECT\s*=\s*IMAGE\s*$",
        "5760 lines": r"(?m)^\s*LINES\s*=\s*5760\s*$",
        "11520 line samples": r"(?m)^\s*LINE_SAMPLES\s*=\s*11520\s*$",
        "MSB integer samples": r"(?m)^\s*SAMPLE_TYPE\s*=\s*MSB_INTEGER\s*$",
        "16-bit samples": r"(?m)^\s*SAMPLE_BITS\s*=\s*16\s*$",
    }
    missing = [name for name, pattern in required.items() if not re.search(pattern, text)]
    if missing:
        raise SystemExit(f"{label.name}: missing expected PDS fields: {missing}")
    product = label.stem.upper()
    if not product.startswith("MEGT") or not product.endswith("GB"):
        raise SystemExit(f"not a 64-pixel/degree topography product: {product}")
    digest = hashlib.sha256()
    with image.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    records.append({
        "product": product,
        "label_file": label.name,
        "image_file": image.name,
        "image_bytes": image.stat().st_size,
        "source_sha256": digest.hexdigest(),
    })
if len(records) != 4:
    raise SystemExit(f"expected four selected products, found {len(records)}")
total = sum(row["image_bytes"] for row in records)
if total != expected_total:
    raise SystemExit(f"unexpected total IMG bytes: {total}")
inventory = {"dataset_id": "nasa_pds_mola_megdr_i16", "image_bytes": total, "records": records}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"semantic_validation=ok files={len(records)} image_bytes={total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
