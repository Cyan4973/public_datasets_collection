#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="statsbomb_open_events_numeric"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLES_DIR="$DATA_ROOT/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import statistics
import struct
import sys
from array import array
from pathlib import Path

DATASET_ID = "statsbomb_open_events_numeric"
MIN_VALUES_PER_SAMPLE = int(os.environ.get("STATSBOMB_MIN_VALUES_PER_SAMPLE", "200"))
MIN_SAMPLE_COUNT = int(os.environ.get("STATSBOMB_MIN_SAMPLE_COUNT", "30"))
MIN_PRIMARY_VALUES = int(os.environ.get("STATSBOMB_MIN_PRIMARY_VALUES", "10000"))
MIN_PRIMARY_BYTES = int(os.environ.get("STATSBOMB_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_MEDIAN_VALUES = int(os.environ.get("STATSBOMB_MIN_MEDIAN_VALUES", "1000"))
MAX_PRIMARY_BYTES = int(os.environ.get("STATSBOMB_MAX_PRIMARY_BYTES", "1000000000"))

data_root = Path(os.environ["DATA_ROOT"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

# series_id -> (role, numeric_kind, bit_width, struct_code, int_range_or_None)
SPECS = {
    "statsbomb_event_location_x": ("primary", "float", 32, "f", None),
    "statsbomb_event_location_y": ("primary", "float", 32, "f", None),
    "statsbomb_event_duration": ("primary", "float", 32, "f", None),
    "statsbomb_event_minute": ("auxiliary", "uint", 16, "H", (0, 65535)),
    "statsbomb_event_second": ("auxiliary", "uint", 8, "B", (0, 255)),
    "statsbomb_event_possession": ("auxiliary", "uint", 16, "H", (0, 65535)),
}


def read_plan() -> list[dict]:
    plan = download_dir / "download_plan.tsv"
    if not plan.exists():
        raise SystemExit(f"missing download plan: {plan}; run download.sh first")
    with plan.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def extract(events: list) -> dict[str, list]:
    out: dict[str, list] = {sid: [] for sid in SPECS}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        loc = ev.get("location")
        if isinstance(loc, list) and len(loc) >= 2 and all(isinstance(c, (int, float)) for c in loc[:2]):
            x, y = float(loc[0]), float(loc[1])
            if math.isfinite(x) and math.isfinite(y):
                out["statsbomb_event_location_x"].append(x)
                out["statsbomb_event_location_y"].append(y)
        dur = ev.get("duration")
        if isinstance(dur, (int, float)) and math.isfinite(float(dur)):
            out["statsbomb_event_duration"].append(float(dur))
        for sid, key in (
            ("statsbomb_event_minute", "minute"),
            ("statsbomb_event_second", "second"),
            ("statsbomb_event_possession", "possession"),
        ):
            val = ev.get(key)
            lo, hi = SPECS[sid][4]
            if isinstance(val, int) and lo <= val <= hi:
                out[sid].append(val)
    return out


for sid in SPECS:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

plan = read_plan()
if not plan:
    raise SystemExit("empty download plan")

rows: list[dict] = []
skip_counts: dict[str, int] = {}
match_count = 0
total_primary_bytes = 0
for plan_row in plan:
    match_id = str(plan_row.get("match_id") or "").strip()
    local_name = str(plan_row.get("local_name") or f"events_{match_id}.json")
    source = download_dir / local_name
    if not source.exists():
        skip_counts["missing_file"] = skip_counts.get("missing_file", 0) + 1
        continue
    try:
        events = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        skip_counts["parse_error"] = skip_counts.get("parse_error", 0) + 1
        continue
    if not isinstance(events, list) or not events:
        skip_counts["not_event_list"] = skip_counts.get("not_event_list", 0) + 1
        continue
    match_count += 1
    series_values = extract(events)
    for sid, (role, kind, bits, code, _rng) in SPECS.items():
        values = series_values[sid]
        if len(values) < MIN_VALUES_PER_SAMPLE:
            skip_counts[f"{sid}:below_min_values"] = skip_counts.get(f"{sid}:below_min_values", 0) + 1
            continue
        if len(set(values)) <= 1:
            skip_counts[f"{sid}:constant"] = skip_counts.get(f"{sid}:constant", 0) + 1
            continue
        out = samples_dir / sid / f"{match_id}_{sid}.bin"
        packed = struct.pack("<" + code * len(values), *values)
        out.write_bytes(packed)
        size = out.stat().st_size
        # Record min/max of the values AS STORED (float32 rounding applied), so
        # the index matches what a reader recomputes from the little-endian bytes.
        stored = array(code, packed)
        if sys.byteorder == "big":
            stored.byteswap()
        stored_min, stored_max = min(stored), max(stored)
        if role == "primary":
            total_primary_bytes += size
            if total_primary_bytes > MAX_PRIMARY_BYTES:
                raise SystemExit(f"primary output exceeds cap: {total_primary_bytes}")
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": sid,
            "role": role,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": size,
            "value_count": len(values),
            "min": stored_min,
            "max": stored_max,
            "sample_geometry": "1d_sequence",
            "sample_rank": 1,
            "sample_axes": ["event"],
            "natural_record_kind": "statsbomb_match_event_stream",
            "match_id": match_id,
            "competition_id": plan_row.get("competition_id", ""),
            "season_id": plan_row.get("season_id", ""),
        })

# ---- Acceptance floors (primary payload only) --------------------------------
primary = [r for r in rows if r["role"] == "primary"]
primary_series_counts: dict[str, int] = {}
for r in primary:
    primary_series_counts[r["series_id"]] = primary_series_counts.get(r["series_id"], 0) + 1

if not primary:
    raise SystemExit("no primary samples produced")
short = {sid: n for sid, n in primary_series_counts.items() if n < MIN_SAMPLE_COUNT}
missing = [sid for sid, (role, *_rest) in SPECS.items() if role == "primary" and sid not in primary_series_counts]
if missing or short:
    raise SystemExit(f"primary series below sample-count floor: missing={missing} short={short} (need >= {MIN_SAMPLE_COUNT})")

primary_values = sum(int(r["value_count"]) for r in primary)
primary_bytes = sum(int(r["sample_size_bytes"]) for r in primary)
median_primary_values = statistics.median(int(r["value_count"]) for r in primary)
if primary_values < MIN_PRIMARY_VALUES and primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"below aggregate floor: values={primary_values} bytes={primary_bytes}")
if median_primary_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median primary sample below floor: {median_primary_values}")

series_stats: dict[str, dict[str, int]] = {}
for r in rows:
    st = series_stats.setdefault(r["series_id"], {"role": r["role"], "sample_count": 0, "total_values": 0, "total_bytes": 0})
    st["sample_count"] += 1
    st["total_values"] += int(r["value_count"])
    st["total_bytes"] += int(r["sample_size_bytes"])

stats = {
    "dataset_id": DATASET_ID,
    "matches_used": match_count,
    "sample_count": len(rows),
    "primary_sample_count": len(primary),
    "primary_values": primary_values,
    "primary_bytes": primary_bytes,
    "median_primary_values": median_primary_values,
    "series": series_stats,
    "skip_counts": skip_counts,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")

print(
    f"built matches={match_count} samples={len(rows)} primary_samples={len(primary)} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_primary_values={int(median_primary_values)} series={ {k: v['sample_count'] for k, v in series_stats.items()} }"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
