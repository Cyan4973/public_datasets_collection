#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_localized_narratives_ade20k_traces_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${LOCALIZED_NARRATIVES_URL:-https://storage.googleapis.com/localized-narratives/annotations/ade20k_train_localized_narratives.jsonl}"
TARGET="$DOWNLOAD_DIR/ade20k_train_localized_narratives.jsonl"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
EXPECTED_BYTES="${LOCALIZED_NARRATIVES_EXPECTED_BYTES:-802749301}"
MIN_SOURCE_BYTES="${LOCALIZED_NARRATIVES_MIN_SOURCE_BYTES:-700000000}"
MAX_SOURCE_BYTES="${LOCALIZED_NARRATIVES_MAX_SOURCE_BYTES:-900000000}"
HARD_MAX_SOURCE_BYTES=1000000000

if (( MAX_SOURCE_BYTES > HARD_MAX_SOURCE_BYTES )); then
  echo "requested max source size $MAX_SOURCE_BYTES exceeds hard cap $HARD_MAX_SOURCE_BYTES; clamping"
  MAX_SOURCE_BYTES="$HARD_MAX_SOURCE_BYTES"
fi

printf 'resource_id\turl\tfile\texpected_bytes\nlocalized_narratives_ade20k_train\t%s\t%s\t%s\n' \
  "$URL" "$(basename "$TARGET")" "$EXPECTED_BYTES" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_SOURCE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL EXPECTED_BYTES MIN_SOURCE_BYTES MAX_SOURCE_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
expected_bytes = int(os.environ["EXPECTED_BYTES"])
min_source_bytes = int(os.environ["MIN_SOURCE_BYTES"])
max_source_bytes = int(os.environ["MAX_SOURCE_BYTES"])


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def looks_like_point(seq: object) -> tuple[float, float, float] | None:
    if not isinstance(seq, list) or len(seq) < 3:
        return None
    if not all(is_number(value) for value in seq[:3]):
        return None
    a, b, c = (float(seq[0]), float(seq[1]), float(seq[2]))
    if 0.0 <= a <= 1.0 and 0.0 <= b <= 1.0 and 0.0 <= c <= 86400.0:
        return a, b, c
    if 0.0 <= b <= 1.0 and 0.0 <= c <= 1.0 and 0.0 <= a <= 86400.0:
        return b, c, a
    return None


def count_trace_points(value: object, limit: int = 1000000) -> int:
    count = 0
    stack = [value]
    while stack and count < limit:
        item = stack.pop()
        if isinstance(item, list):
            point = looks_like_point(item)
            if point is not None:
                count += 1
                continue
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            if all(key in item for key in ("x", "y")):
                time_value = item.get("t", item.get("time", item.get("timestamp")))
                if is_number(item["x"]) and is_number(item["y"]) and is_number(time_value):
                    x = float(item["x"])
                    y = float(item["y"])
                    t = float(time_value)
                    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= t <= 86400.0:
                        count += 1
                        continue
            stack.extend(reversed(list(item.values())))
    return count


if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size < min_source_bytes:
    raise SystemExit(f"source file below floor: {size} < {min_source_bytes}")
if size > max_source_bytes:
    raise SystemExit(f"source file exceeds cap: {size} > {max_source_bytes}")
if expected_bytes and size != expected_bytes:
    raise SystemExit(f"source size mismatch: {size} != expected {expected_bytes}")
with target.open("rb") as fh:
    head = fh.read(512).lstrip()
if head.startswith(b"<") or b"<html" in head.lower():
    raise SystemExit(f"download looks like HTML, not JSONL: {target}")

sampled_records = 0
sampled_trace_records = 0
sampled_trace_points = 0
line_count_estimate = 0
with target.open("rb") as fh:
    for raw in fh:
        line_count_estimate += 1
        if sampled_records >= 200:
            continue
        if not raw.strip():
            continue
        obj = json.loads(raw)
        sampled_records += 1
        if not isinstance(obj, dict):
            raise SystemExit(f"sampled JSONL row is not an object near record {sampled_records}")
        roots = []
        for key, value in obj.items():
            lowered = str(key).lower()
            if "trace" in lowered or "mouse" in lowered:
                roots.append(value)
        if not roots and "traces" in obj:
            roots.append(obj["traces"])
        points = sum(count_trace_points(root) for root in roots)
        if points:
            sampled_trace_records += 1
            sampled_trace_points += points

if sampled_records < 100:
    raise SystemExit(f"too few sampled JSONL records: {sampled_records}")
if sampled_trace_records < 50 or sampled_trace_points < 1000:
    raise SystemExit(
        f"too few sampled trace records/points: records={sampled_trace_records} points={sampled_trace_points}"
    )

inventory = {
    "dataset_id": "google_localized_narratives_ade20k_traces_f32",
    "url": os.environ["URL"],
    "file": target.name,
    "source_bytes": size,
    "line_count": line_count_estimate,
    "sampled_records": sampled_records,
    "sampled_trace_records": sampled_trace_records,
    "sampled_trace_points": sampled_trace_points,
    "expected_bytes": expected_bytes,
    "max_source_bytes": max_source_bytes,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok source_bytes={size} lines={line_count_estimate} "
    f"sampled_trace_records={sampled_trace_records} sampled_trace_points={sampled_trace_points}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
