#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sentinel2_l2a_scene_classification_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

MAX_FILE_BYTES="${S2_SCL_MAX_FILE_BYTES:-50000000}"
MAX_DOWNLOAD_BYTES="${S2_SCL_MAX_DOWNLOAD_BYTES:-1000000000}"
MIN_TOTAL_BYTES="${S2_SCL_MIN_TOTAL_BYTES:-100000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

cat > "$PLAN" <<'EOF'
local_name	url	scene_id	search_label	datetime	cloud_cover
01_S2B_11SKB_20230812_0_L2A_SCL.tif	https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/S/KB/2023/8/S2B_11SKB_20230812_0_L2A/SCL.tif	S2B_11SKB_20230812_0_L2A	california_sierra_aug2023	2023-08-12T18:57:12.779000Z	low_cloud
02_S2B_19KDP_20230814_0_L2A_SCL.tif	https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/K/DP/2023/8/S2B_19KDP_20230814_0_L2A/SCL.tif	S2B_19KDP_20230814_0_L2A	atacama_aug2023	2023-08-14T14:29:15.835000Z	low_cloud
EOF

downloaded_total=0
tail -n +2 "$PLAN" | while IFS=$'\t' read -r local_name url scene_id search_label datetime cloud_cover; do
  [[ -n "$local_name" ]] || continue
  target="$DOWNLOAD_DIR/$local_name"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit scene=$scene_id path=$target bytes=$(wc -c < "$target" | tr -d ' ')"
  else
    echo "fetch scene=$scene_id url=$url"
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      -A "openzl-public-datasets/1.0 (sentinel2-scl-u8)" \
      -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
  fi
  size="$(wc -c < "$target" | tr -d ' ')"
  if (( size <= 1024 )); then
    echo "$target is too small to be a valid SCL GeoTIFF: $size" >&2
    exit 1
  fi
  if (( size > MAX_FILE_BYTES )); then
    echo "$target exceeds per-file cap: $size > $MAX_FILE_BYTES" >&2
    exit 1
  fi
  downloaded_total=$((downloaded_total + size))
  if (( downloaded_total > MAX_DOWNLOAD_BYTES )); then
    echo "downloaded bytes exceed cap: $downloaded_total > $MAX_DOWNLOAD_BYTES" >&2
    exit 1
  fi
done

export DOWNLOAD_DIR PLAN MIN_TOTAL_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
min_total_bytes = int(os.environ["MIN_TOTAL_BYTES"])


def tiff_scalar(data: bytes, endian: str, field_type: int, count: int, raw_value: int) -> list[int]:
    sizes = {1: 1, 2: 1, 3: 2, 4: 4}
    codes = {1: "B", 2: "c", 3: "H", 4: "I"}
    if field_type not in sizes or field_type not in codes:
        return []
    size = sizes[field_type]
    if count * size <= 4:
        raw = struct.pack(endian + "I", raw_value)[: count * size]
    else:
        raw = data[raw_value : raw_value + count * size]
    if codes[field_type] == "c":
        return [0]
    return list(struct.unpack(endian + codes[field_type] * count, raw))


def inspect_tiff(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise SystemExit(f"{path}: not a TIFF file")
    if struct.unpack_from(endian + "H", data, 2)[0] != 42:
        raise SystemExit(f"{path}: unsupported TIFF magic")
    ifd = struct.unpack_from(endian + "I", data, 4)[0]
    entry_count = struct.unpack_from(endian + "H", data, ifd)[0]
    tags: dict[int, tuple[int, int, int]] = {}
    for idx in range(entry_count):
        off = ifd + 2 + idx * 12
        tag, field_type, count, raw_value = struct.unpack_from(endian + "HHII", data, off)
        tags[tag] = (field_type, count, raw_value)

    def values(tag: int) -> list[int]:
        if tag not in tags:
            return []
        return tiff_scalar(data, endian, *tags[tag])

    width = values(256)[0]
    height = values(257)[0]
    bits = values(258)[0]
    samples_per_pixel = (values(277) or [1])[0]
    compression = (values(259) or [1])[0]
    if bits != 8 or samples_per_pixel != 1:
        raise SystemExit(f"{path}: expected single-band uint8 TIFF, got bits={bits} samples={samples_per_pixel}")
    if compression not in {1, 5, 8, 32946}:
        raise SystemExit(f"{path}: unsupported TIFF compression {compression}")
    return {
        "width": width,
        "height": height,
        "bits_per_sample": bits,
        "samples_per_pixel": samples_per_pixel,
        "compression": compression,
    }


records = []
total_bytes = 0
for line in plan.read_text(encoding="utf-8").splitlines()[1:]:
    if not line.strip():
        continue
    local_name, url, scene_id, search_label, datetime, cloud_cover = line.split("\t")
    path = download_dir / local_name
    if not path.is_file():
        raise SystemExit(f"missing download: {path}")
    info = inspect_tiff(path)
    size = path.stat().st_size
    total_bytes += size
    records.append({
        "file": local_name,
        "url": url,
        "scene_id": scene_id,
        "search_label": search_label,
        "datetime": datetime,
        "cloud_cover": cloud_cover,
        "source_bytes": size,
        **info,
    })
if total_bytes < min_total_bytes:
    raise SystemExit(f"total download too small: {total_bytes} < {min_total_bytes}")
inventory = {
    "dataset_id": "sentinel2_l2a_scene_classification_u8",
    "records": records,
    "source_bytes": total_bytes,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok files={len(records)} source_bytes={total_bytes}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
