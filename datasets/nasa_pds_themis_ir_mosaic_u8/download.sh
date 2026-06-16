#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_themis_ir_mosaic_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-750000000}"
MAX_TOTAL_BYTES="${MAX_DOWNLOAD_BYTES:-1000000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

cat > "$PLAN" <<'EOF'
THEMIS_DayIR_ControlledMosaic_Arabia_000N000E_100mpp.tif	https://planetarymaps.usgs.gov/mosaic/Mars/THEMIS_controlled_mosaics/Arabia_DayIR_30April2015/THEMIS_DayIR_ControlledMosaic_Arabia_000N000E_100mpp.tif
THEMIS_DayIR_ControlledMosaic_Elysium_00N135E_100mpp.tif	https://planetarymaps.usgs.gov/mosaic/Mars/THEMIS_controlled_mosaics/Elysium_DayIR_31July2014/THEMIS_DayIR_ControlledMosaic_Elysium_00N135E_100mpp.tif
EOF

downloaded_total=0
while IFS=$'\t' read -r name url; do
  [[ -n "$name" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -o "$target" "$url"
  fi
  size="$(wc -c < "$target")"
  if (( size > MAX_FILE_BYTES )); then
    echo "$target exceeds per-file cap: $size" >&2
    exit 1
  fi
  downloaded_total=$((downloaded_total + size))
  if (( downloaded_total > MAX_TOTAL_BYTES )); then
    echo "downloaded bytes exceed cap: $downloaded_total" >&2
    exit 1
  fi
done < "$PLAN"

export DOWNLOAD_DIR PLAN
python3 - <<'PY'
from __future__ import annotations

import json
import os
import struct
from pathlib import Path


def tiff_values(data: bytes, endian: str, field_type: int, count: int, raw_value: int) -> list[int]:
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4}
    type_codes = {1: "B", 2: "c", 3: "H", 4: "I"}
    size = type_sizes.get(field_type)
    code = type_codes.get(field_type)
    if size is None or code is None:
        raise ValueError(f"unsupported TIFF field type: {field_type}")
    if count * size <= 4:
        value_bytes = struct.pack(endian + "I", raw_value)[: count * size]
    else:
        value_bytes = data[raw_value : raw_value + count * size]
    if code == "c":
        return [0]
    return list(struct.unpack(endian + code * count, value_bytes))


def validate_tiff(path: Path) -> dict:
    data = path.read_bytes()[:1024 * 1024]
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError(f"{path.name}: not a TIFF file")
    if struct.unpack_from(endian + "H", data, 2)[0] != 42:
        raise ValueError(f"{path.name}: unsupported TIFF magic")
    ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
    entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
    tags = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, field_type, count, raw_value = struct.unpack_from(endian + "HHII", data, offset)
        tags[tag] = (field_type, count, raw_value)

    def values(tag: int) -> list[int]:
        field_type, count, raw_value = tags[tag]
        return tiff_values(data, endian, field_type, count, raw_value)

    width = values(256)[0]
    height = values(257)[0]
    bits = values(258)[0]
    compression = (values(259) or [1])[0]
    samples_per_pixel = (values(277) or [1])[0]
    sample_format = values(339)[0] if 339 in tags else 1
    offsets = values(273)
    counts = values(279)
    expected_pixels = width * height
    if bits != 8 or compression != 1 or samples_per_pixel != 1 or sample_format != 1:
        raise ValueError(
            f"{path.name}: not native uncompressed single-band uint8 "
            f"bits={bits} compression={compression} samples={samples_per_pixel} sample_format={sample_format}"
        )
    if len(offsets) != len(counts) or sum(counts) != expected_pixels:
        raise ValueError(f"{path.name}: invalid strip table")
    return {
        "file": path.name,
        "source_bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "value_count": expected_pixels,
        "pixel_bytes": expected_pixels,
    }


download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
records = []
for line in plan.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    name, url = line.split("\t")
    record = validate_tiff(download_dir / name)
    record["url"] = url
    records.append(record)
inventory = {
    "dataset_id": "nasa_pds_themis_ir_mosaic_u8",
    "record_count": len(records),
    "source_bytes": sum(row["source_bytes"] for row in records),
    "pixel_bytes": sum(row["pixel_bytes"] for row in records),
    "records": records,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']} "
    f"pixel_bytes={inventory['pixel_bytes']}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
