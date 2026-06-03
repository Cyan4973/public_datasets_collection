#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openf1_belgium_2023_car_data_native"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
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

SESSION_KEY = 9135
SERIES = [
    ("openf1_speed", "speed", "uint", 16, "<H", 0, 65535),
    ("openf1_rpm", "rpm", "uint", 16, "<H", 0, 65535),
    ("openf1_throttle", "throttle", "uint", 8, "<B", 0, 255),
    ("openf1_brake", "brake", "uint", 8, "<B", 0, 255),
    ("openf1_n_gear", "n_gear", "uint", 8, "<B", 0, 255),
    ("openf1_drs", "drs", "uint", 8, "<B", 0, 255),
]


def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


for series_id, *_ in SERIES:
    series_dir = samples_dir / series_id
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

raw_files = sorted(download_dir.glob(f"car_data_s{SESSION_KEY}_d*.json"), key=lambda p: int(p.stem.rsplit("_d", 1)[-1]))
if not raw_files:
    raise SystemExit(f"no car_data_s{SESSION_KEY}_d*.json found in {download_dir}")

stats = {"dataset_id": "openf1_belgium_2023_car_data_native", "session_key": SESSION_KEY, "drivers": [], "series": {}}
sample_rows = []
for series_id, _, numeric_kind, bit_width, _, _, _ in SERIES:
    stats["series"][series_id] = {"files": 0, "values": 0, "bytes": 0}

for raw_file in raw_files:
    driver = int(raw_file.stem.rsplit("_d", 1)[-1])
    payload = json.loads(raw_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"{raw_file}: expected non-empty JSON array")
    payload.sort(key=lambda sample: (sample.get("date", ""), sample.get("driver_number", 0)))
    driver_record = {
        "driver_number": driver,
        "source_file": rel_data(raw_file),
        "source_sha256": sha256_file(raw_file),
        "samples": len(payload),
        "first_date": payload[0].get("date"),
        "last_date": payload[-1].get("date"),
        "series": {},
    }
    for series_id, field_name, numeric_kind, bit_width, struct_fmt, min_value, max_value in SERIES:
        values = []
        for idx, sample in enumerate(payload, start=1):
            if field_name not in sample:
                raise RuntimeError(f"{raw_file}:{idx}: missing field {field_name}")
            raw_value = sample[field_name]
            if isinstance(raw_value, bool):
                value = int(raw_value)
            elif isinstance(raw_value, (int, float)):
                value = int(raw_value)
            else:
                raise RuntimeError(f"{raw_file}:{idx}: non-numeric field {field_name}={raw_value!r}")
            if value < min_value or value > max_value:
                raise RuntimeError(f"{raw_file}:{idx}: {field_name} value {value} out of range [{min_value}, {max_value}]")
            values.append(value)

        element_size = 2 if bit_width == 16 else 1
        out_path = samples_dir / series_id / f"openf1_{series_id}_d{driver}_n{len(values):06d}.bin"
        if bit_width == 16:
            out_path.write_bytes(struct.pack("<" + "H" * len(values), *values))
        else:
            out_path.write_bytes(struct.pack("<" + "B" * len(values), *values))
        sample_rows.append({
            "dataset_id": "openf1_belgium_2023_car_data_native",
            "series_id": series_id,
            "sample_path": rel_data(out_path),
            "numeric_kind": numeric_kind,
            "bit_width": bit_width,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out_path.stat().st_size,
            "value_count": len(values),
        })
        driver_record["series"][series_id] = {
            "file": rel_data(out_path),
            "sha256": sha256_file(out_path),
            "values": len(values),
            "bytes": out_path.stat().st_size,
            "min": min(values) if values else 0,
            "max": max(values) if values else 0,
        }
        stats["series"][series_id]["files"] += 1
        stats["series"][series_id]["values"] += len(values)
        stats["series"][series_id]["bytes"] += out_path.stat().st_size
    stats["drivers"].append(driver_record)

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
