#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_sharad_radargram_f32"
LEGACY_DATASET_ID="nasa_pds_sharad_radargram_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LEGACY_DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$LEGACY_DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR LEGACY_DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import array
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "sharad_radargram_backscatter_f32"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
legacy_download_dir = Path(os.environ["LEGACY_DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])


def pds_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def pointer_file(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("("):
        return value.strip("()").split(",", 1)[0].strip().strip('"')
    if value.startswith('"'):
        return value.strip('"')
    return value


def parse_int(text: str, key: str) -> int:
    raw = pds_value(text, key) or ""
    match = re.search(r"[-+]?\d+", raw)
    if not match:
        raise ValueError(f"missing integer {key}")
    return int(match.group(0))


def sample_stats(payload: bytes) -> tuple[int, float, float, int]:
    if len(payload) % 4 != 0:
        raise ValueError("float32 payload length is not divisible by 4")
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    finite = 0
    min_value = math.inf
    max_value = -math.inf
    for value in values:
        if not math.isfinite(value):
            continue
        finite += 1
        if value < min_value:
            min_value = value
        if value > max_value:
            max_value = value
    if finite != len(values):
        raise ValueError(f"non-finite float32 values: {len(values) - finite}")
    if min_value == max_value:
        raise ValueError("constant radargram payload")
    return len(values), min_value, max_value, finite


source_dir = download_dir if any(download_dir.glob("*.lbl")) else legacy_download_dir
if not any(source_dir.glob("*.lbl")):
    raise SystemExit(f"missing SHARAD labels in {download_dir}; run download.sh first")

series_dir = samples_dir / SERIES_ID
if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows: list[dict] = []
product_stats: list[dict] = []
rejected: list[dict] = []
for label in sorted(source_dir.glob("*.lbl")):
    text = label.read_text(encoding="utf-8", errors="replace")
    product_id = (pds_value(text, "PRODUCT_ID") or label.stem).lower()
    try:
        lines = parse_int(text, "LINES")
        line_samples = parse_int(text, "LINE_SAMPLES")
        record_bytes = parse_int(text, "RECORD_BYTES")
        file_records = parse_int(text, "FILE_RECORDS")
        sample_bits = parse_int(text, "SAMPLE_BITS")
        sample_type = (pds_value(text, "SAMPLE_TYPE") or "").upper()
        image_name = pointer_file(pds_value(text, "^IMAGE")) or label.with_suffix(".img").name
    except Exception as exc:
        rejected.append({"label": label.name, "reason": f"malformed_label:{exc}"})
        continue
    if sample_bits != 32 or sample_type != "PC_REAL":
        rejected.append({"label": label.name, "reason": f"unsupported_sample_type:{sample_type}:{sample_bits}"})
        continue
    expected_record_bytes = line_samples * 4
    if record_bytes != expected_record_bytes or file_records != lines:
        rejected.append({"label": label.name, "reason": "record_geometry_mismatch"})
        continue
    image = source_dir / image_name.lower()
    if not image.exists():
        image = source_dir / image_name
    if not image.exists():
        rejected.append({"label": label.name, "reason": f"missing_image:{image_name}"})
        continue
    payload = image.read_bytes()
    expected_bytes = lines * line_samples * 4
    if len(payload) != expected_bytes:
        rejected.append({"label": label.name, "reason": f"image_size_mismatch:{len(payload)}:{expected_bytes}"})
        continue
    value_count, min_value, max_value, finite_count = sample_stats(payload)
    out = series_dir / f"{product_id}.bin"
    out.write_bytes(payload)
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "source_label": label.name,
        "source_image": image.name,
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": out.stat().st_size,
        "value_count": value_count,
        "sample_format": "raw homogeneous float32 array copied from PDS3 PC_REAL image",
        "sample_geometry": "sharad_radargram_2d",
        "sample_rank": 2,
        "sample_shape": [lines, line_samples],
        "sample_axes": ["along_track_line", "delay_bin"],
        "natural_record_kind": "pds_sharad_radargram_product",
        "container_format": "pds3_detached_label_image",
        "pds_sample_type": sample_type,
        "min": min_value,
        "max": max_value,
    }
    rows.append(row)
    product_stats.append(
        {
            "product_id": product_id,
            "lines": lines,
            "line_samples": line_samples,
            "value_count": value_count,
            "sample_size_bytes": out.stat().st_size,
            "finite_count": finite_count,
            "min": min_value,
            "max": max_value,
        }
    )

if not rows:
    raise SystemExit("no SHARAD PC_REAL float32 radargrams accepted")

primary_values = sum(row["value_count"] for row in rows)
primary_bytes = sum(row["sample_size_bytes"] for row in rows)
if primary_values < 10000 or primary_bytes < 102400:
    raise SystemExit(f"primary output below floor: values={primary_values} bytes={primary_bytes}")

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_download_dir": str(source_dir.relative_to(data_root)),
            "accepted_products": len(rows),
            "rejected_products": len(rejected),
            "primary_values": primary_values,
            "primary_sample_bytes": primary_bytes,
            "min_sample_values": min(row["value_count"] for row in rows),
            "max_sample_values": max(row["value_count"] for row in rows),
            "products": product_stats,
            "rejected": rejected,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)

print(f"accepted_products={len(rows)} primary_values={primary_values} primary_sample_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
