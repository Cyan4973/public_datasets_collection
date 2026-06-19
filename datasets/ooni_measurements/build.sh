#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ooni_measurements"
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
export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import calendar
import json
import os
import shutil
import statistics
import struct
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_files = sorted(download_dir.glob("ooni_measurements_page_*.json"))
legacy_file = download_dir / "ooni_measurements.json"
if not page_files and legacy_file.exists():
    page_files = [legacy_file]
if not page_files:
    raise SystemExit(f"missing OONI JSON pages under {download_dir}; run download.sh first")

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def parse_timestamp(value: object) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())

def parse_asn(value: object) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if text.startswith("AS"):
        text = text[2:]
    try:
        asn = int(text)
    except ValueError:
        return None
    if not 0 <= asn <= 0xFFFFFFFF:
        return None
    return asn

series = {
    "ooni_measurement_unix_u32": ("uint", 32, "I"),
    "ooni_probe_asn_u32": ("uint", 32, "I"),
    "ooni_blocking_general_score_f32": ("float", 32, "f"),
}
values = {sid: [] for sid in series}
seen_measurements: set[str] = set()
rows_total = 0
rows_skipped = 0
duplicate_measurements = 0
missing_measurement_ids = 0
unexpected_tests: dict[str, int] = {}
test_name = None

for page_path in page_files:
    obj = json.loads(page_path.read_text(encoding="utf-8"))
    results = obj.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"{page_path.name}: missing results list")
    for row in results:
        if not isinstance(row, dict):
            rows_skipped += 1
            continue
        rows_total += 1
        row_test = str(row.get("test_name") or "")
        if test_name is None and row_test:
            test_name = row_test
        if row_test and test_name and row_test != test_name:
            unexpected_tests[row_test] = unexpected_tests.get(row_test, 0) + 1
            rows_skipped += 1
            continue
        measurement_id = str(row.get("measurement_uid") or row.get("report_id") or "")
        if measurement_id:
            if measurement_id in seen_measurements:
                duplicate_measurements += 1
                continue
            seen_measurements.add(measurement_id)
        else:
            missing_measurement_ids += 1

        ts = parse_timestamp(row.get("measurement_start_time"))
        asn = parse_asn(row.get("probe_asn"))
        scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
        try:
            score = float(scores["blocking_general"])
        except Exception:
            score = None
        if ts is None or asn is None or score is None:
            rows_skipped += 1
            continue
        if not 0.0 <= score <= 3.0:
            raise SystemExit(f"{page_path.name}: blocking_general score outside 0..3: {score}")

        values["ooni_measurement_unix_u32"].append(ts)
        values["ooni_probe_asn_u32"].append(asn)
        values["ooni_blocking_general_score_f32"].append(score)

sample_rows = []
for series_id, (kind, bits, code) in series.items():
    vals = values[series_id]
    if not vals:
        continue
    out = samples_dir / series_id / f"{series_id}_n{len(vals):08d}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(vals), *vals))
    sample_rows.append(
        {
            "dataset_id": dataset_id,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "ooni_web_connectivity_measurement_field",
            "sample_rank": 1,
            "sample_shape": [len(vals)],
            "sample_axes": ["measurement"],
            "source_name": "ooni_measurements_web_connectivity_2024_01",
        }
    )

primary_counts = [int(row["value_count"]) for row in sample_rows if row["role"] == "primary"]
primary_sizes = [int(row["sample_size_bytes"]) for row in sample_rows if row["role"] == "primary"]
stats = {
    "dataset_id": dataset_id,
    "test_name": test_name or "unknown",
    "page_files": len(page_files),
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "retained_measurements": len(values["ooni_measurement_unix_u32"]),
    "unique_measurement_ids": len(seen_measurements),
    "missing_measurement_ids": missing_measurement_ids,
    "duplicate_measurements": duplicate_measurements,
    "unexpected_tests": unexpected_tests,
    "primary_samples": len(primary_counts),
    "primary_values": sum(primary_counts),
    "primary_bytes": sum(primary_sizes),
    "median_primary_values": statistics.median(primary_counts) if primary_counts else 0,
    "min_primary_values": min(primary_counts) if primary_counts else 0,
    "max_primary_values": max(primary_counts) if primary_counts else 0,
    "source_bytes": sum(path.stat().st_size for path in page_files),
}
if stats["retained_measurements"] < 10_000:
    raise SystemExit(f"retained measurements below repair floor: {stats['retained_measurements']}")
if stats["primary_values"] < 10_000:
    raise SystemExit(f"primary values below floor: {stats['primary_values']}")
if stats["primary_bytes"] < 100 * 1024:
    raise SystemExit(f"primary bytes below floor: {stats['primary_bytes']}")
if stats["median_primary_values"] < 1_000:
    raise SystemExit(f"median primary sample values below floor: {stats['median_primary_values']}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(sample_rows)} retained_measurements={stats['retained_measurements']} "
    f"primary_values={stats['primary_values']} primary_bytes={stats['primary_bytes']} "
    f"median_values={stats['median_primary_values']} source_bytes={stats['source_bytes']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
