#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="snap_roadnet_edges_i32"
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

import gzip
import json
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "snap_roadnet_edges_i32"
SPECS = [
    ("CA", "roadNet-CA.txt.gz"),
    ("PA", "roadNet-PA.txt.gz"),
    ("TX", "roadNet-TX.txt.gz"),
]
MAX_I32 = 2_147_483_647
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_VALUES_PER_SAMPLE = 1_000_000
MIN_SAMPLES = 6

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
total_bytes = 0
for state, filename in SPECS:
    path = download_dir / filename
    if not path.is_file():
        raise SystemExit(f"missing source file: {path}")
    src_values: list[int] = []
    dst_values: list[int] = []
    comments = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                comments += 1
                continue
            parts = line.split()
            if len(parts) != 2:
                raise SystemExit(f"bad edge width in {filename}: {line[:80]}")
            src = int(parts[0])
            dst = int(parts[1])
            if src < 0 or dst < 0 or src > MAX_I32 or dst > MAX_I32 or src == dst:
                raise SystemExit(f"invalid edge in {filename}: {line[:80]}")
            src_values.append(src)
            dst_values.append(dst)
    if len(src_values) != len(dst_values):
        raise SystemExit(f"endpoint length mismatch for {state}")
    for endpoint_name, values in (("src", src_values), ("dst", dst_values)):
        if len(values) < MIN_VALUES_PER_SAMPLE:
            raise SystemExit(f"too few values for {state} {endpoint_name}: {len(values)}")
        if len(set(values[: min(len(values), 200_000)])) <= 1:
            raise SystemExit(f"constant endpoint prefix for {state} {endpoint_name}")
        series_id = f"snap_roadnet_{state.lower()}_{endpoint_name}_node_i32"
        out_dir = samples_dir / series_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{series_id}_n{len(values):08d}.bin"
        out.write_bytes(struct.pack("<" + "i" * len(values), *values))
        size = out.stat().st_size
        total_bytes += size
        if total_bytes > MAX_PRIMARY_BYTES:
            raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
        row = {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": len(values),
            "sample_format": "raw homogeneous int32 SNAP road-network edge endpoint column",
            "sample_geometry": "graph_edge_endpoint_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["edge"],
            "natural_record_kind": "snap_roadnet_edge_endpoint_column",
            "source_file": filename,
            "source_state": state,
            "source_field": endpoint_name,
            "source_edge_count": len(values),
            "min": min(values),
            "max": max(values),
        }
        rows.append(row)
        records.append({
            "series_id": series_id,
            "state": state,
            "endpoint": endpoint_name,
            "edges": len(values),
            "comments": comments,
            "sample_bytes": size,
            "min": min(values),
            "max": max(values),
        })

if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few samples: {len(rows)} < {MIN_SAMPLES}")
counts = sorted(int(row["value_count"]) for row in rows)
stats = {
    "dataset_id": DATASET_ID,
    "states": [state for state, _ in SPECS],
    "samples": len(rows),
    "primary_values": sum(counts),
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
    f"built samples={len(rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={total_bytes} median_values={stats['median_value_count']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
