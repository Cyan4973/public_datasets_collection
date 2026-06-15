#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="hf_smolllm2_135m_safetensors_f16"
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

import json
import os
import re
import shutil
import statistics
import struct
from collections import Counter
from pathlib import Path

DATASET_ID = "hf_smolllm2_135m_safetensors_f16"
SERIES_ID = "smolllm2_135m_tensor_f16"
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source = download_dir / "model.safetensors"
if not source.exists():
    raise SystemExit(f"missing checkpoint: {source}")

out_dir = samples_dir / SERIES_ID
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

with source.open("rb") as fh:
    header_len = struct.unpack("<Q", fh.read(8))[0]
    header = json.loads(fh.read(header_len))
    payload_start = 8 + header_len
    rows = []
    records = []
    for tensor_index, (name, meta) in enumerate(header.items(), start=1):
        if name == "__metadata__":
            continue
        dtype = str(meta.get("dtype", ""))
        if dtype not in {"F16", "BF16"}:
            raise SystemExit(f"{name}: unsupported dtype {dtype}")
        offsets = meta.get("data_offsets")
        shape = [int(value) for value in meta.get("shape", [])]
        if not isinstance(offsets, list) or len(offsets) != 2:
            raise SystemExit(f"{name}: invalid data_offsets")
        start, end = int(offsets[0]), int(offsets[1])
        byte_count = end - start
        if byte_count <= 0 or byte_count % 2:
            raise SystemExit(f"{name}: invalid 16-bit payload byte count {byte_count}")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
        out = out_dir / f"{tensor_index:04d}_{safe}.bin"
        fh.seek(payload_start + start)
        payload = fh.read(byte_count)
        if len(payload) != byte_count:
            raise SystemExit(f"{name}: truncated tensor payload")
        out.write_bytes(payload)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": byte_count,
            "value_count": byte_count // 2,
            "sample_geometry": "tensor",
            "sample_rank": len(shape),
            "sample_shape": shape,
            "sample_axes": [f"dim_{index}" for index in range(len(shape))],
            "tensor_name": name,
            "tensor_dtype": dtype,
        }
        rows.append(row)
        records.append({"tensor_name": name, "tensor_dtype": dtype, "shape": shape, "bytes": byte_count})

sizes = [row["sample_size_bytes"] for row in rows]
total = sum(sizes)
if total > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {total}")
if len(rows) < 8:
    raise SystemExit(f"too few tensor samples: {len(rows)}")
stats = {
    "dataset_id": DATASET_ID,
    "sample_count": len(rows),
    "primary_values": sum(row["value_count"] for row in rows),
    "primary_bytes": total,
    "same_size_fraction": max(Counter(sizes).values()) / len(sizes),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_bytes={total} size_range={min(sizes)}/{statistics.median(sizes)}/{max(sizes)}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
