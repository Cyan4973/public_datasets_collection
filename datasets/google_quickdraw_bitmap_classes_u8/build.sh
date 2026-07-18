#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_quickdraw_bitmap_classes_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

CLASSES_TEXT="${QUICKDRAW_CLASSES:-airplane cat dog car house tree}"
MIN_TOTAL_VALUES="${QUICKDRAW_BUILD_MIN_TOTAL_VALUES:-400000000}"
MAX_PRIMARY_BYTES="${QUICKDRAW_MAX_PRIMARY_BYTES:-950000000}"
HARD_MAX_PRIMARY_BYTES=1000000000
if (( MAX_PRIMARY_BYTES > HARD_MAX_PRIMARY_BYTES )); then
  echo "requested max primary bytes $MAX_PRIMARY_BYTES exceeds hard cap $HARD_MAX_PRIMARY_BYTES; clamping"
  MAX_PRIMARY_BYTES="$HARD_MAX_PRIMARY_BYTES"
fi

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR CLASSES_TEXT MIN_TOTAL_VALUES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import ast
import json
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
classes = os.environ["CLASSES_TEXT"].split()
min_total_values = int(os.environ["MIN_TOTAL_VALUES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "google_quickdraw_bitmap_classes_u8"
FAMILY = "quickdraw_bitmap_28x28_u8"


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


if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

records: list[dict[str, object]] = []
class_stats: list[dict[str, object]] = []
total_bytes = 0
total_values = 0
for class_name in classes:
    source = download_dir / f"{class_name}.npy"
    if not source.is_file():
        raise SystemExit(f"missing source file: {source}")
    header, data_offset = parse_npy_header(source)
    descr = header.get("descr")
    shape = header.get("shape")
    fortran_order = header.get("fortran_order")
    if descr not in {"|u1", "<u1"}:
        raise SystemExit(f"unexpected dtype for {source}: {descr!r}")
    if fortran_order:
        raise SystemExit(f"fortran-order array is unsupported: {source}")
    if not (isinstance(shape, tuple) and len(shape) == 2 and shape[1] == 784):
        raise SystemExit(f"unexpected QuickDraw shape for {source}: {shape!r}")
    rows = int(shape[0])
    payload_bytes = rows * 784
    if source.stat().st_size - data_offset != payload_bytes:
        raise SystemExit(f"payload size mismatch for {source}")
    if total_bytes + payload_bytes > max_primary_bytes:
        break
    sample_path = out_dir / f"{class_name}_bitmap_28x28_u8.bin"
    with source.open("rb") as src, sample_path.open("wb") as dst:
        src.seek(data_offset)
        shutil.copyfileobj(src, dst)
    size = sample_path.stat().st_size
    if size != payload_bytes:
        raise SystemExit(f"sample size mismatch for {sample_path}: {size} != {payload_bytes}")
    total_bytes += size
    total_values += payload_bytes
    class_stats.append({
        "class": class_name,
        "drawings": rows,
        "pixel_values": payload_bytes,
        "source_bytes": source.stat().st_size,
        "sample_bytes": size,
    })
    records.append({
        "dataset_id": DATASET_ID,
        "series_id": f"quickdraw_{class_name}_bitmap_28x28_u8",
        "family": FAMILY,
        "role": "primary",
        "sample_path": sample_path.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": size,
        "value_count": payload_bytes,
        "sample_geometry": "sketch_bitmap_stack",
        "sample_rank": 3,
        "sample_shape": [rows, 28, 28],
        "sample_axes": ["drawing", "y", "x"],
        "source_class": class_name,
        "source_path": source.as_posix(),
        "natural_record_kind": "quickdraw_bitmap_class",
    })

if len(records) < 4:
    raise SystemExit(f"too few class samples: {len(records)}")
if total_values < min_total_values:
    raise SystemExit(f"too few pixel values: {total_values} < {min_total_values}")
if total_bytes > max_primary_bytes:
    raise SystemExit(f"primary output exceeds cap: {total_bytes} > {max_primary_bytes}")

stats = {
    "dataset_id": DATASET_ID,
    "classes": [record["source_class"] for record in records],
    "samples": len(records),
    "class_stats": class_stats,
    "primary_values": total_values,
    "primary_sample_bytes": total_bytes,
    "max_primary_bytes": max_primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for record in records:
        out.write(json.dumps(record, sort_keys=True) + "\n")

print(
    f"built samples={len(records)} values={total_values} bytes={total_bytes} "
    f"classes={','.join(stats['classes'])}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
