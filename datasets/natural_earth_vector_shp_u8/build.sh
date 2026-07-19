#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="natural_earth_vector_shp_u8"
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

import json
import os
import shutil
import struct
import zipfile
from pathlib import Path

DATASET_ID = "natural_earth_vector_shp_u8"
SERIES_ID = "natural_earth_10m_shp_geometry"
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def validate_shp(payload: bytes, name: str) -> dict:
    if len(payload) < 100:
        raise RuntimeError(f"{name}: shapefile shorter than 100-byte header")
    file_code = struct.unpack(">I", payload[:4])[0]
    file_length_words = struct.unpack(">I", payload[24:28])[0]
    version = struct.unpack("<I", payload[28:32])[0]
    shape_type = struct.unpack("<I", payload[32:36])[0]
    if file_code != 9994 or version != 1000:
        raise RuntimeError(f"{name}: invalid shapefile header code={file_code} version={version}")
    expected_bytes = file_length_words * 2
    if expected_bytes != len(payload):
        raise RuntimeError(f"{name}: shapefile header length {expected_bytes} != actual {len(payload)}")
    if shape_type == 0:
        raise RuntimeError(f"{name}: null-only shapefile type")
    return {"shape_type": shape_type}

out_dir = samples_dir / SERIES_ID
reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
for ordinal, zip_path in enumerate(sorted((download_dir / "zips").glob("*.zip")), start=1):
    with zipfile.ZipFile(zip_path) as zf:
        shp_names = [name for name in zf.namelist() if name.lower().endswith(".shp")]
        if len(shp_names) != 1:
            raise RuntimeError(f"{zip_path.name}: expected exactly one .shp member, found {shp_names}")
        shp_name = shp_names[0]
        payload = zf.read(shp_name)
    meta = validate_shp(payload, shp_name)
    if len(set(payload)) < 2:
        raise RuntimeError(f"{shp_name}: degenerate shapefile payload")
    out = out_dir / f"{ordinal:03d}_{Path(shp_name).stem}.bin"
    out.write_bytes(payload)
    index_row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(payload),
        "value_count": len(payload),
    }
    rows.append(index_row)
    records.append({"zip": zip_path.name, "shp_member": shp_name, "sample_path": index_row["sample_path"], "bytes": len(payload), "values": len(payload), "distinct_values": len(set(payload)), **meta})

total = sum(record["bytes"] for record in records)
if total > MAX_PRIMARY_BYTES:
    raise RuntimeError(f"primary payload exceeds 1 GB cap: {total}")
if len(records) < 10:
    raise RuntimeError(f"too few shapefile samples: {len(records)}")
stats = {"dataset_id": DATASET_ID, "records": records, "record_count": len(records), "total_bytes": total, "total_values": total}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
