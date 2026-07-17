#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openimages_v6_train_bbox_annotations_f32"
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

MIN_ROWS="${OPENIMAGES_BBOX_BUILD_MIN_ROWS:-3000000}"
MAX_PRIMARY_BYTES="${OPENIMAGES_BBOX_MAX_PRIMARY_BYTES:-1000000000}"
HARD_MAX_PRIMARY_BYTES=1000000000
if (( MAX_PRIMARY_BYTES > HARD_MAX_PRIMARY_BYTES )); then
  echo "requested max primary bytes $MAX_PRIMARY_BYTES exceeds hard cap $HARD_MAX_PRIMARY_BYTES; clamping"
  MAX_PRIMARY_BYTES="$HARD_MAX_PRIMARY_BYTES"
fi

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_ROWS MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from array import array
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_rows = int(os.environ["MIN_ROWS"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "openimages_v6_train_bbox_annotations_f32"
FAMILY = "openimages_v6_train_bbox_numeric_fields"
SOURCE = download_dir / "oidv6-train-annotations-bbox.range.csv"
EXPECTED_HEADER = [
    "ImageID",
    "Source",
    "LabelName",
    "Confidence",
    "XMin",
    "XMax",
    "YMin",
    "YMax",
    "IsOccluded",
    "IsTruncated",
    "IsGroupOf",
    "IsDepiction",
    "IsInside",
    "XClick1X",
    "XClick2X",
    "XClick3X",
    "XClick4X",
    "XClick1Y",
    "XClick2Y",
    "XClick3Y",
    "XClick4Y",
]
FLOAT_FIELDS = [
    (3, "confidence_f32"),
    (4, "xmin_f32"),
    (5, "xmax_f32"),
    (6, "ymin_f32"),
    (7, "ymax_f32"),
    (13, "xclick1x_f32"),
    (14, "xclick2x_f32"),
    (15, "xclick3x_f32"),
    (16, "xclick4x_f32"),
    (17, "xclick1y_f32"),
    (18, "xclick2y_f32"),
    (19, "xclick3y_f32"),
    (20, "xclick4y_f32"),
]
FLAG_FIELDS = [
    (8, "is_occluded_i8"),
    (9, "is_truncated_i8"),
    (10, "is_group_of_i8"),
    (11, "is_depiction_i8"),
    (12, "is_inside_i8"),
]
CHUNK_ROWS = 100000

if not SOURCE.is_file():
    raise SystemExit(f"missing source file: {SOURCE}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

little = sys.byteorder == "little"
float_buffers = {name: array("f") for _, name in FLOAT_FIELDS}
flag_buffers = {name: array("b") for _, name in FLAG_FIELDS}
float_paths = {name: out_dir / f"{name}.bin" for _, name in FLOAT_FIELDS}
flag_paths = {name: out_dir / f"{name}.bin" for _, name in FLAG_FIELDS}
float_files = {name: float_paths[name].open("wb") for _, name in FLOAT_FIELDS}
flag_files = {name: flag_paths[name].open("wb") for _, name in FLAG_FIELDS}
mins = {name: float("inf") for _, name in FLOAT_FIELDS + FLAG_FIELDS}
maxs = {name: float("-inf") for _, name in FLOAT_FIELDS + FLAG_FIELDS}
rows = 0
skipped_partial_tail = 0

def flush() -> None:
    for name, buf in float_buffers.items():
        if not buf:
            continue
        if little:
            buf.tofile(float_files[name])
        else:
            copy = array("f", buf)
            copy.byteswap()
            copy.tofile(float_files[name])
        float_buffers[name] = array("f")
    for name, buf in flag_buffers.items():
        if not buf:
            continue
        buf.tofile(flag_files[name])
        flag_buffers[name] = array("b")

try:
    with SOURCE.open("rb") as raw:
        header_line = raw.readline()
        header = next(csv.reader([header_line.decode("utf-8-sig", errors="strict").rstrip("\r\n")]))
        if header != EXPECTED_HEADER:
            raise SystemExit(f"unexpected header: {header}")
        for raw_line in raw:
            if not raw_line.endswith(b"\n"):
                skipped_partial_tail += 1
                continue
            line = raw_line.decode("utf-8", errors="strict").rstrip("\r\n")
            if not line:
                continue
            row = next(csv.reader([line]))
            if len(row) != len(EXPECTED_HEADER):
                raise SystemExit(f"unexpected row width near row {rows + 2}: {len(row)}")
            coords = [float(row[idx]) for idx, _ in FLOAT_FIELDS]
            bbox_values = coords[:5]
            click_values = coords[5:]
            if not all(0.0 <= value <= 1.0 for value in bbox_values):
                raise SystemExit(f"bbox float outside [0,1] near row {rows + 2}: {bbox_values}")
            if not all(-1.0 <= value <= 1.0 for value in click_values):
                raise SystemExit(
                    f"click float outside sentinel/normalized range near row {rows + 2}: {click_values}"
                )
            if coords[2] < coords[1] or coords[4] < coords[3]:
                raise SystemExit(f"invalid bbox ordering near row {rows + 2}: {coords}")
            for value, (_, name) in zip(coords, FLOAT_FIELDS):
                float_buffers[name].append(value)
                mins[name] = min(mins[name], value)
                maxs[name] = max(maxs[name], value)
            for idx, name in FLAG_FIELDS:
                if row[idx] not in {"-1", "0", "1"}:
                    raise SystemExit(f"unexpected flag sentinel/value near row {rows + 2}: {row[idx]!r}")
                value = int(row[idx])
                flag_buffers[name].append(value)
                mins[name] = min(mins[name], value)
                maxs[name] = max(maxs[name], value)
            rows += 1
            if rows % CHUNK_ROWS == 0:
                flush()
    flush()
finally:
    for fh in [*float_files.values(), *flag_files.values()]:
        fh.close()

if rows < min_rows:
    raise SystemExit(f"too few rows after build: {rows} < {min_rows}")
if skipped_partial_tail > 1:
    raise SystemExit(f"too many partial tail rows: {skipped_partial_tail}")

records: list[dict[str, object]] = []
total_bytes = 0
skipped_constant: list[str] = []
for _, name in FLOAT_FIELDS:
    path = float_paths[name]
    size = path.stat().st_size
    if size != rows * 4:
        raise SystemExit(f"size mismatch for {name}: {size} != {rows * 4}")
    if mins[name] == maxs[name]:
        path.unlink(missing_ok=True)
        skipped_constant.append(name)
        continue
    total_bytes += size
    records.append({
        "dataset_id": DATASET_ID,
        "series_id": f"openimages_v6_train_bbox_{name}",
        "family": FAMILY,
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": size,
        "value_count": rows,
        "sample_geometry": "annotation_field",
        "sample_rank": 1,
        "sample_shape": [rows],
        "sample_axes": ["bounding_box_annotation"],
        "source_field_name": name.removesuffix("_f32"),
        "source_path": SOURCE.as_posix(),
        "min_value": mins[name],
        "max_value": maxs[name],
        "natural_record_kind": "openimages_bounding_box_annotation",
    })
for _, name in FLAG_FIELDS:
    path = flag_paths[name]
    size = path.stat().st_size
    if size != rows:
        raise SystemExit(f"size mismatch for {name}: {size} != {rows}")
    if mins[name] == maxs[name]:
        path.unlink(missing_ok=True)
        skipped_constant.append(name)
        continue
    total_bytes += size
    records.append({
        "dataset_id": DATASET_ID,
        "series_id": f"openimages_v6_train_bbox_{name}",
        "family": FAMILY,
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": "int",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": size,
        "value_count": rows,
        "sample_geometry": "annotation_field",
        "sample_rank": 1,
        "sample_shape": [rows],
        "sample_axes": ["bounding_box_annotation"],
            "source_field_name": name.removesuffix("_i8"),
        "source_path": SOURCE.as_posix(),
        "min_value": mins[name],
        "max_value": maxs[name],
        "natural_record_kind": "openimages_bounding_box_annotation",
    })

if total_bytes > max_primary_bytes:
    raise SystemExit(f"primary output exceeds cap: {total_bytes} > {max_primary_bytes}")
if len(records) < 8:
    raise SystemExit(f"too few nonconstant samples: {len(records)}")

stats = {
    "dataset_id": DATASET_ID,
    "source_file": SOURCE.name,
    "source_bytes": SOURCE.stat().st_size,
    "complete_rows": rows,
    "skipped_partial_tail": skipped_partial_tail,
    "samples": len(records),
    "skipped_constant_fields": skipped_constant,
    "primary_values": sum(record["value_count"] for record in records),
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
    f"built samples={len(records)} rows={rows} values={stats['primary_values']} "
    f"bytes={total_bytes} skipped_constant={len(skipped_constant)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
