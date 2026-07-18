#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_localized_narratives_ade20k_traces_f32"
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

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import array
import json
import math
import os
import shutil
import sys
from pathlib import Path

DATASET_ID = "google_localized_narratives_ade20k_traces_f32"
FAMILY = "localized_narratives_ade20k_trace_fields"
SOURCE_FILE = "ade20k_train_localized_narratives.jsonl"
MIN_RECORDS = 10_000
MIN_TRACE_RECORDS = 8_000
MIN_TRACE_POINTS = 2_000_000
MIN_PRIMARY_BYTES = 32_000_000
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source_path = download_dir / SOURCE_FILE


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def normalize_point(values: list[object]) -> tuple[float, float, float] | None:
    if len(values) < 3 or not all(is_number(value) for value in values[:3]):
        return None
    a, b, c = (float(values[0]), float(values[1]), float(values[2]))
    if 0.0 <= a <= 1.0 and 0.0 <= b <= 1.0 and 0.0 <= c <= 86400.0:
        return a, b, c
    if 0.0 <= b <= 1.0 and 0.0 <= c <= 1.0 and 0.0 <= a <= 86400.0:
        return b, c, a
    return None


def collect_points(value: object) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            point = normalize_point(item)
            if point is not None:
                points.append(point)
            else:
                stack.extend(reversed(item))
        elif isinstance(item, dict):
            if all(key in item for key in ("x", "y")):
                time_value = item.get("t", item.get("time", item.get("timestamp")))
                if is_number(item["x"]) and is_number(item["y"]) and is_number(time_value):
                    x = float(item["x"])
                    y = float(item["y"])
                    t = float(time_value)
                    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= t <= 86400.0:
                        points.append((x, y, t))
                        continue
            for x_key in ("x", "xs", "trace_x", "traceX"):
                for y_key in ("y", "ys", "trace_y", "traceY"):
                    for t_key in ("t", "time", "timestamp", "ts"):
                        xs = item.get(x_key)
                        ys = item.get(y_key)
                        ts = item.get(t_key)
                        if isinstance(xs, list) and isinstance(ys, list) and isinstance(ts, list):
                            if len(xs) == len(ys) == len(ts):
                                for x_raw, y_raw, t_raw in zip(xs, ys, ts):
                                    if is_number(x_raw) and is_number(y_raw) and is_number(t_raw):
                                        x = float(x_raw)
                                        y = float(y_raw)
                                        t = float(t_raw)
                                        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= t <= 86400.0:
                                            points.append((x, y, t))
                                if points:
                                    return points
            stack.extend(reversed(list(item.values())))
    return points


def trace_roots(obj: dict[str, object]) -> list[object]:
    roots = []
    for key, value in obj.items():
        lowered = str(key).lower()
        if "trace" in lowered or "mouse" in lowered:
            roots.append(value)
    if not roots and "traces" in obj:
        roots.append(obj["traces"])
    return roots


def flush_array(fh, values: array.array) -> None:
    if not values:
        return
    if sys.byteorder != "little":
        values.byteswap()
    fh.write(values.tobytes())
    del values[:]


def caption_text(obj: dict[str, object]) -> str:
    for key in ("caption", "text", "narration"):
        value = obj.get(key)
        if isinstance(value, str):
            return value
    return ""


if not source_path.is_file():
    raise SystemExit(f"missing source JSONL: {source_path}")

out_dir = samples_dir / FAMILY
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

paths = {
    "trace_x": out_dir / "trace_x_f32.bin",
    "trace_y": out_dir / "trace_y_f32.bin",
    "trace_t": out_dir / "trace_t_f32.bin",
    "points_per_record": out_dir / "points_per_record_u32.bin",
    "caption_chars": out_dir / "caption_chars_u32.bin",
}

records = 0
trace_records = 0
trace_points = 0
caption_records = 0
min_x = math.inf
max_x = -math.inf
min_y = math.inf
max_y = -math.inf
min_t = math.inf
max_t = -math.inf
max_points_per_record = 0
max_caption_chars = 0
xb = array.array("f")
yb = array.array("f")
tb = array.array("f")
cb = array.array("I")
captionb = array.array("I")

with (
    source_path.open("rb") as src,
    paths["trace_x"].open("wb") as xfh,
    paths["trace_y"].open("wb") as yfh,
    paths["trace_t"].open("wb") as tfh,
    paths["points_per_record"].open("wb") as cfh,
    paths["caption_chars"].open("wb") as captionfh,
):
    for raw in src:
        if not raw.strip():
            continue
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise SystemExit(f"JSONL record {records + 1} is not an object")
        records += 1
        points: list[tuple[float, float, float]] = []
        for root in trace_roots(obj):
            points.extend(collect_points(root))
        point_count = len(points)
        if point_count:
            trace_records += 1
            max_points_per_record = max(max_points_per_record, point_count)
        cb.append(point_count)
        text = caption_text(obj)
        caption_len = len(text)
        if text:
            caption_records += 1
        max_caption_chars = max(max_caption_chars, caption_len)
        captionb.append(caption_len)
        for x, y, t in points:
            xb.append(x)
            yb.append(y)
            tb.append(t)
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            min_t = min(min_t, t)
            max_t = max(max_t, t)
        trace_points += point_count
        if len(xb) >= 262144:
            flush_array(xfh, xb)
            flush_array(yfh, yb)
            flush_array(tfh, tb)
        if len(cb) >= 262144:
            flush_array(cfh, cb)
            flush_array(captionfh, captionb)
    flush_array(xfh, xb)
    flush_array(yfh, yb)
    flush_array(tfh, tb)
    flush_array(cfh, cb)
    flush_array(captionfh, captionb)

if records < MIN_RECORDS:
    raise SystemExit(f"too few annotation records: {records} < {MIN_RECORDS}")
if trace_records < MIN_TRACE_RECORDS:
    raise SystemExit(f"too few records with traces: {trace_records} < {MIN_TRACE_RECORDS}")
if trace_points < MIN_TRACE_POINTS:
    raise SystemExit(f"too few trace points: {trace_points} < {MIN_TRACE_POINTS}")

sizes = {name: path.stat().st_size for name, path in paths.items()}
primary_bytes = sum(sizes.values())
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {primary_bytes} < {MIN_PRIMARY_BYTES}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes} > {MAX_PRIMARY_BYTES}")

series_specs = [
    ("trace_x", "localized_narratives_trace_x_f32", "float", 32, trace_points, min_x, max_x, "Normalized mouse trace x coordinate."),
    ("trace_y", "localized_narratives_trace_y_f32", "float", 32, trace_points, min_y, max_y, "Normalized mouse trace y coordinate."),
    ("trace_t", "localized_narratives_trace_time_f32", "float", 32, trace_points, min_t, max_t, "Mouse trace timestamp or elapsed-time value."),
    ("points_per_record", "localized_narratives_points_per_record_u32", "uint", 32, records, 0, max_points_per_record, "Number of accepted trace points in each annotation record."),
    ("caption_chars", "localized_narratives_caption_chars_u32", "uint", 32, records, 0, max_caption_chars, "Caption character count for each annotation record."),
]

rows = []
for name, series_id, kind, bit_width, value_count, min_value, max_value, meaning in series_specs:
    sample_path = paths[name]
    row = {
        "dataset_id": DATASET_ID,
        "series_id": series_id,
        "family": FAMILY,
        "role": "primary",
        "sample_path": rel(sample_path),
        "numeric_kind": kind,
        "bit_width": bit_width,
        "endianness": "little",
        "element_size_bytes": bit_width // 8,
        "sample_size_bytes": sample_path.stat().st_size,
        "value_count": value_count,
        "sample_format": f"raw homogeneous {kind}{bit_width} annotation stream",
        "sample_geometry": "human_annotation_trace_stream",
        "sample_rank": 1,
        "sample_shape": [value_count],
        "sample_axes": ["annotation_point" if name.startswith("trace_") else "record"],
        "natural_record_kind": "localized_narratives_ade20k_annotation_field",
        "source_file": SOURCE_FILE,
        "semantic_meaning": meaning,
        "min": min_value,
        "max": max_value,
    }
    rows.append(row)

stats = {
    "dataset_id": DATASET_ID,
    "source_file": SOURCE_FILE,
    "source_bytes": source_path.stat().st_size,
    "annotation_records": records,
    "trace_records": trace_records,
    "caption_records": caption_records,
    "trace_points": trace_points,
    "primary_values": sum(int(row["value_count"]) for row in rows),
    "primary_sample_bytes": primary_bytes,
    "max_points_per_record": max_points_per_record,
    "max_caption_chars": max_caption_chars,
    "trace_coordinate_range": {"x": [min_x, max_x], "y": [min_y, max_y], "time": [min_t, max_t]},
    "series": [
        {
            "series_id": row["series_id"],
            "values": row["value_count"],
            "bytes": row["sample_size_bytes"],
            "min": row["min"],
            "max": row["max"],
        }
        for row in rows
    ],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(rows)} records={records} trace_records={trace_records} "
    f"trace_points={trace_points} primary_bytes={primary_bytes}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
