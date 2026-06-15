#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="hf_smolllm2_135m_safetensors_f16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
mkdir -p "$LOG_DIR" "$INDEX_DIR" "$FILTER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR INDEX_DIR FILTER_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from collections import Counter
from pathlib import Path

DATASET_ID = "hf_smolllm2_135m_safetensors_f16"
SERIES_ID = "smolllm2_135m_tensor_f16"
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists() or not stats_path.exists():
    raise SystemExit("missing index or ingest stats")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) < 8:
    raise SystemExit(f"too few tensor samples: {len(rows)}")
sizes = []
values = []
dtypes = Counter()
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
        raise SystemExit(f"unexpected row identity: {row}")
    if row["numeric_kind"] != "float" or int(row["bit_width"]) != 16 or row["endianness"] != "little":
        raise SystemExit(f"unexpected numeric representation: {row}")
    if row.get("sample_geometry") != "tensor" or int(row.get("sample_rank", -1)) != len(row.get("sample_shape", [])):
        raise SystemExit(f"invalid tensor geometry metadata: {row}")
    if row.get("tensor_dtype") not in {"F16", "BF16"}:
        raise SystemExit(f"invalid tensor dtype: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {path}")
    actual = path.stat().st_size
    declared = int(row["sample_size_bytes"])
    count = int(row["value_count"])
    if actual != declared or declared != count * 2 or declared <= 0:
        raise SystemExit(f"size mismatch: {path}")
    sizes.append(declared)
    values.append(count)
    dtypes.update([row["tensor_dtype"]])
total = sum(sizes)
if total > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {total}")
print(f"verified_rows={len(rows)} primary_samples={len(rows)} primary_values={sum(values)} primary_bytes={total} dtypes={dict(dtypes)} size_range={min(sizes)}/{statistics.median(sizes)}/{max(sizes)} same_size_fraction={max(Counter(sizes).values()) / len(sizes):.6f}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
