#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_hdri_exr_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1

python3 - <<'PY'
import json, statistics
from pathlib import Path
import os
repo_root = Path(os.environ.get("REPO_ROOT", "."))
data_dir = os.environ.get("DATA_DIR", ".data")
dataset_id="polyhaven_hdri_exr_f32"
data_root=repo_root / data_dir
index_path=data_root / "index" / dataset_id / "samples.jsonl"
stats_path=data_root / "filtered" / dataset_id / "ingest_stats.json"
if not index_path.exists() or not stats_path.exists():
    raise SystemExit("missing samples index or ingest stats")
rows=[json.loads(l) for l in index_path.read_text().splitlines() if l.strip()]
for r in rows:
    if r["bit_width"]!=32 or r["element_size_bytes"]!=4:
        raise SystemExit(f"unexpected width {r}")
    p=data_root / r["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing {p}")
    if p.stat().st_size != r["sample_size_bytes"]:
        raise SystemExit(f"size mismatch {p}")
print(f"verified samples={len(rows)}")
PY
