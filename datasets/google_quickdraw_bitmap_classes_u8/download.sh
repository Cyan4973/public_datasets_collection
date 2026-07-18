#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_quickdraw_bitmap_classes_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${QUICKDRAW_BASE_URL:-https://storage.googleapis.com/quickdraw_dataset/full/numpy_bitmap}"
CLASSES_TEXT="${QUICKDRAW_CLASSES:-airplane cat dog car house tree}"
MAX_FILE_BYTES="${QUICKDRAW_MAX_FILE_BYTES:-200000000}"
MAX_TOTAL_BYTES="${QUICKDRAW_MAX_TOTAL_BYTES:-900000000}"
HARD_MAX_TOTAL_BYTES=1000000000
MIN_TOTAL_VALUES="${QUICKDRAW_MIN_TOTAL_VALUES:-400000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

if (( MAX_TOTAL_BYTES > HARD_MAX_TOTAL_BYTES )); then
  echo "requested total source size $MAX_TOTAL_BYTES exceeds hard cap $HARD_MAX_TOTAL_BYTES; clamping"
  MAX_TOTAL_BYTES="$HARD_MAX_TOTAL_BYTES"
fi
if (( MAX_FILE_BYTES > HARD_MAX_TOTAL_BYTES )); then
  echo "requested per-file source size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_TOTAL_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_TOTAL_BYTES"
fi

printf 'resource_id\turl\tfile\n' > "$PLAN"
for class_name in $CLASSES_TEXT; do
  url="$BASE_URL/$class_name.npy"
  file="$class_name.npy"
  printf 'quickdraw_%s\t%s\t%s\n' "$class_name" "$url" "$file" >> "$PLAN"
  target="$DOWNLOAD_DIR/$file"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit class=$class_name path=$target"
    continue
  fi
  echo "fetch class=$class_name url=$url"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$target.tmp" "$url"
  mv "$target.tmp" "$target"
done

export DOWNLOAD_DIR CLASSES_TEXT MAX_FILE_BYTES MAX_TOTAL_BYTES MIN_TOTAL_VALUES
python3 - <<'PY'
from __future__ import annotations

import ast
import json
import os
import struct
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
classes = os.environ["CLASSES_TEXT"].split()
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
min_total_values = int(os.environ["MIN_TOTAL_VALUES"])


def parse_npy_header(path: Path) -> tuple[dict[str, object], int]:
    with path.open("rb") as fh:
        magic = fh.read(6)
        if magic != b"\x93NUMPY":
            raise SystemExit(f"not a NumPy .npy file: {path}")
        major, minor = fh.read(2)
        if (major, minor) == (1, 0):
            header_len = struct.unpack("<H", fh.read(2))[0]
        elif (major, minor) in {(2, 0), (3, 0)}:
            header_len = struct.unpack("<I", fh.read(4))[0]
        else:
            raise SystemExit(f"unsupported npy version {major}.{minor}: {path}")
        header_offset = fh.tell() + header_len
        header = fh.read(header_len).decode("latin1")
    parsed = ast.literal_eval(header)
    if not isinstance(parsed, dict):
        raise SystemExit(f"bad npy header dict: {path}")
    return parsed, header_offset


total_bytes = 0
total_values = 0
resources: list[dict[str, object]] = []
for class_name in classes:
    path = download_dir / f"{class_name}.npy"
    if not path.is_file():
        raise SystemExit(f"missing download: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise SystemExit(f"empty download: {path}")
    if size > max_file_bytes:
        raise SystemExit(f"download exceeds per-file cap: {path} {size} > {max_file_bytes}")
    head = path.read_bytes()[:512].lstrip().lower()
    if head.startswith(b"<") or b"<html" in head:
        raise SystemExit(f"download looks like HTML, not NPY: {path}")
    header, data_offset = parse_npy_header(path)
    descr = header.get("descr")
    shape = header.get("shape")
    fortran_order = header.get("fortran_order")
    if descr not in {"|u1", "<u1"}:
        raise SystemExit(f"unexpected dtype for {path}: {descr!r}")
    if fortran_order:
        raise SystemExit(f"fortran-order array is unsupported: {path}")
    if not (isinstance(shape, tuple) and len(shape) == 2 and shape[1] == 784):
        raise SystemExit(f"unexpected QuickDraw shape for {path}: {shape!r}")
    rows = int(shape[0])
    payload_bytes = rows * 784
    if size - data_offset != payload_bytes:
        raise SystemExit(f"payload size mismatch for {path}: {size - data_offset} != {payload_bytes}")
    total_bytes += size
    total_values += payload_bytes
    resources.append({
        "class": class_name,
        "file": path.name,
        "bytes": size,
        "rows": rows,
        "values": payload_bytes,
        "npy_header_offset": data_offset,
    })

if total_bytes > max_total_bytes:
    raise SystemExit(f"downloads exceed total cap: {total_bytes} > {max_total_bytes}")
if total_values < min_total_values:
    raise SystemExit(f"too few QuickDraw values: {total_values} < {min_total_values}")

inventory = {
    "dataset_id": "google_quickdraw_bitmap_classes_u8",
    "classes": classes,
    "resources": resources,
    "archive_bytes": total_bytes,
    "pixel_values": total_values,
    "max_file_bytes": max_file_bytes,
    "max_total_bytes": max_total_bytes,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok classes={len(classes)} source_bytes={total_bytes} "
    f"pixel_values={total_values}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
