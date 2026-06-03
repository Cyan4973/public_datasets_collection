#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="citibike_2024_01_station_ids_u16"
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

import csv
import hashlib
import io
import json
import os
import shutil
import struct
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

archive = download_dir / "202401-citibike-tripdata.zip"
shard_lengths = [104742, 149385, 211815, 23608, 454662, 88962, 337379, 517532]
families = [("start_station_id", "citibike_start_station_id"), ("end_station_id", "citibike_end_station_id")]

def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

for _, family_name in families:
    family_dir = samples_dir / family_name
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True, exist_ok=True)

global_dict = {}
first_seen = {}
states = {}
for family_key, family_name in families:
    states[family_key] = {
        "family_name": family_name,
        "counts": Counter(),
        "outputs": [],
        "total_values": 0,
        "total_zero_values": 0,
        "buffer": bytearray(),
        "shard_index": 0,
        "shard_values": 0,
        "shard_zero_values": 0,
        "shard_start_member": None,
        "shard_start_row": None,
        "shard_min_code": None,
        "shard_max_code": None,
    }

def assign_code(raw_value: str, member_name: str, row_number: int, counts: Counter[str]) -> int:
    if not raw_value:
        return 0
    code = global_dict.get(raw_value)
    if code is None:
        code = len(global_dict) + 1
        if code > 0xFFFF:
            raise RuntimeError(f"dictionary exceeds uint16 capacity: {code}")
        global_dict[raw_value] = code
        first_seen[raw_value] = (member_name, row_number)
    counts[raw_value] += 1
    return code

def flush_shard(state, member_end: str, row_end: int, expected_values: int):
    if state["shard_values"] != expected_values:
        raise RuntimeError(f"unexpected shard length for {state['family_name']}: got {state['shard_values']} expected {expected_values}")
    family_dir = samples_dir / state["family_name"]
    filename = f"part{state['shard_index']:03d}.bin"
    out_path = family_dir / filename
    out_path.write_bytes(state["buffer"])
    record = {
        "family": state["family_name"],
        "file": rel_data(out_path),
        "part": state["shard_index"],
        "values": state["shard_values"],
        "bytes": len(state["buffer"]),
        "zero_values": state["shard_zero_values"],
        "min_code": state["shard_min_code"] if state["shard_min_code"] is not None else 0,
        "max_code": state["shard_max_code"] if state["shard_max_code"] is not None else 0,
        "offset_values": sum(output["values"] for output in state["outputs"]),
        "source_member_start": state["shard_start_member"],
        "source_row_start": state["shard_start_row"],
        "source_member_end": member_end,
        "source_row_end": row_end,
        "sha256": sha256_file(out_path),
    }
    state["outputs"].append(record)
    state["shard_index"] += 1
    state["buffer"] = bytearray()
    state["shard_values"] = 0
    state["shard_zero_values"] = 0
    state["shard_start_member"] = None
    state["shard_start_row"] = None
    state["shard_min_code"] = None
    state["shard_max_code"] = None

archive_members = []
with ZipFile(archive) as zf:
    infos = zf.infolist()
    total_rows = 0
    member_row_counts = {}
    for info in infos:
        row_count = 0
        with zf.open(info) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for _ in csv.DictReader(text):
                row_count += 1
                total_rows += 1
        member_row_counts[info.filename] = row_count
        archive_members.append({"member": info.filename, "rows": row_count, "uncompressed_bytes": info.file_size})
    if sum(shard_lengths) != total_rows:
        raise RuntimeError(f"shard lengths sum {sum(shard_lengths)} does not match total rows {total_rows}")

    shard_index = 0
    current_target = shard_lengths[shard_index]
    primary_key = families[0][0]
    for info in infos:
        member_name = info.filename
        with zf.open(info) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.DictReader(text)
            for row_number, row in enumerate(reader, start=1):
                for family_key, _ in families:
                    state = states[family_key]
                    code = assign_code((row.get(family_key) or "").strip(), member_name, row_number, state["counts"])
                    if state["shard_values"] == 0:
                        state["shard_start_member"] = member_name
                        state["shard_start_row"] = row_number
                    state["buffer"].extend(struct.pack("<H", code))
                    state["shard_values"] += 1
                    state["total_values"] += 1
                    if code == 0:
                        state["shard_zero_values"] += 1
                        state["total_zero_values"] += 1
                    else:
                        if state["shard_min_code"] is None or code < state["shard_min_code"]:
                            state["shard_min_code"] = code
                        if state["shard_max_code"] is None or code > state["shard_max_code"]:
                            state["shard_max_code"] = code
                if states[primary_key]["shard_values"] == current_target:
                    for family_key, _ in families:
                        flush_shard(states[family_key], member_name, row_number, current_target)
                    shard_index += 1
                    if shard_index < len(shard_lengths):
                        current_target = shard_lengths[shard_index]

for family_key, family_name in families:
    state = states[family_key]
    if state["shard_values"] != 0:
        raise RuntimeError(f"non-empty shard buffer remained for {family_name}")

family_summary = {}
sample_rows = []
outputs = []
for family_key, family_name in families:
    state = states[family_key]
    family_summary[family_name] = {
        "files": len(state["outputs"]),
        "values": state["total_values"],
        "bytes": state["total_values"] * 2,
        "zero_values": state["total_zero_values"],
        "distinct_nonzero_codes": sum(1 for raw in global_dict if state["counts"].get(raw, 0) > 0),
        "min_code": min((record["min_code"] for record in state["outputs"] if record["min_code"] > 0), default=0),
        "max_code": max(global_dict.values(), default=0),
    }
    for record in state["outputs"]:
        outputs.append(record)
        sample_rows.append({
            "dataset_id": "citibike_2024_01_station_ids_u16",
            "series_id": family_name,
            "sample_path": record["file"],
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": record["bytes"],
            "value_count": record["values"],
        })

stats = {
    "dataset_id": "citibike_2024_01_station_ids_u16",
    "context": "16bit",
    "source_zip": rel_data(archive),
    "archive_members": archive_members,
    "rows_total": sum(member["rows"] for member in archive_members),
    "output_encoding": "little-endian unsigned 16-bit integer",
    "families": [family_name for _, family_name in families],
    "family_summary": family_summary,
    "sharding": {
        "policy": "fixed aligned deterministic contiguous shards matching the accepted sibling recipe",
        "filename_pattern": "partNNN.bin",
        "seed_material": "20260528:citibike_2024_01_station_ids_num16:aligned_num16:v2",
        "shard_lengths_values": shard_lengths,
        "element_size_bytes": 2,
    },
    "outputs": outputs,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
