#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_marinecadastre_ais_2024_01_01_f32"
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

import csv
import io
import json
import math
import os
import shutil
import statistics
import struct
import zipfile
from pathlib import Path

DATASET_ID = "noaa_marinecadastre_ais_2024_01_01_f32"
ARCHIVE = "AIS_2024_01_01.zip"
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_VALUES_PER_SAMPLE = 500_000
MIN_SAMPLES = 8
MIN_TOTAL_VALUES = 8_000_000

FIELDS = [
    ("LAT", "latitude"),
    ("LON", "longitude"),
    ("SOG", "speed_over_ground"),
    ("COG", "course_over_ground"),
    ("HEADING", "heading"),
    ("VESSELTYPE", "vessel_type"),
    ("STATUS", "navigation_status"),
    ("LENGTH", "length"),
    ("WIDTH", "width"),
    ("DRAFT", "draft"),
    ("CARGO", "cargo"),
]

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive_path = download_dir / ARCHIVE
if not archive_path.is_file():
    raise SystemExit(f"missing archive: {archive_path}")


def slug(text: str) -> str:
    return "_".join("".join(ch.lower() if ch.isalnum() else "_" for ch in text).split("_"))


def as_f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
with zipfile.ZipFile(archive_path) as zf:
    members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise SystemExit(f"expected exactly one CSV member, found {members}")
    csv_member = members[0]
    with zf.open(csv_member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.DictReader(text)
        if not reader.fieldnames:
            raise SystemExit("AIS CSV has no header")
        raw_fields = list(reader.fieldnames)
        upper_to_raw = {field.strip().upper(): field for field in raw_fields}
        selected = [(upper_to_raw[key], key, meaning) for key, meaning in FIELDS if key in upper_to_raw]
        if len(selected) < MIN_SAMPLES:
            raise SystemExit(f"too few candidate numeric fields: {len(selected)} < {MIN_SAMPLES}")
        values = {key: [] for _, key, _ in selected}
        skipped = {key: 0 for _, key, _ in selected}
        rows_seen = 0
        bad_rows = 0
        for record in reader:
            if set(record) != set(raw_fields):
                bad_rows += 1
                continue
            rows_seen += 1
            for raw_field, key, _meaning in selected:
                raw_value = record.get(raw_field, "")
                if raw_value is None or not str(raw_value).strip():
                    skipped[key] += 1
                    continue
                try:
                    value = float(str(raw_value).strip())
                except ValueError:
                    skipped[key] += 1
                    continue
                if not math.isfinite(value):
                    skipped[key] += 1
                    continue
                values[key].append(as_f32(value))

total_bytes = 0
for _raw_field, key, meaning in selected:
    field_values = values[key]
    if len(field_values) < MIN_VALUES_PER_SAMPLE or len(set(field_values[: min(len(field_values), 200_000)])) <= 1:
        continue
    series_id = f"noaa_ais_20240101_{slug(meaning)}_f32"
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(field_values):08d}.bin"
    out.write_bytes(struct.pack("<" + "f" * len(field_values), *field_values))
    size = out.stat().st_size
    total_bytes += size
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": series_id,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": size,
        "value_count": len(field_values),
        "sample_format": "raw homogeneous float32 NOAA AIS numeric field",
        "sample_geometry": "table_column",
        "sample_rank": 1,
        "sample_shape": [len(field_values)],
        "sample_axes": ["ais_report"],
        "natural_record_kind": "noaa_marinecadastre_ais_numeric_field",
        "source_archive": ARCHIVE,
        "source_csv": csv_member,
        "source_date": "2024-01-01",
        "source_field": key,
        "semantic_meaning": meaning,
        "min": min(field_values),
        "max": max(field_values),
    }
    rows.append(row)
    records.append({
        "series_id": series_id,
        "field": key,
        "meaning": meaning,
        "values": len(field_values),
        "skipped_values": skipped[key],
        "sample_bytes": size,
        "min": min(field_values),
        "max": max(field_values),
    })

if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few accepted samples: {len(rows)} < {MIN_SAMPLES}")
counts = sorted(int(row["value_count"]) for row in rows)
primary_values = sum(counts)
if primary_values < MIN_TOTAL_VALUES:
    raise SystemExit(f"too few primary values: {primary_values} < {MIN_TOTAL_VALUES}")
stats = {
    "dataset_id": DATASET_ID,
    "source_date": "2024-01-01",
    "rows_seen": rows_seen,
    "bad_rows": bad_rows,
    "samples": len(rows),
    "primary_values": primary_values,
    "primary_sample_bytes": total_bytes,
    "median_value_count": statistics.median(counts),
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(rows, key=lambda item: item["series_id"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(rows)} primary_values={primary_values} "
    f"primary_bytes={total_bytes} median_values={stats['median_value_count']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
