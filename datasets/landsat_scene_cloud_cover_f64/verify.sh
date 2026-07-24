#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
ID="landsat_scene_cloud_cover_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start $ID"
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from pathlib import Path
import json, struct, math, os
repo=Path(os.environ["REPO_ROOT"])
data_root=repo/Path(os.environ["DATA_DIR"])
idx=Path(os.environ["INDEX_DIR"])/"samples.jsonl"
rows=[json.loads(l) for l in idx.read_text().splitlines() if l.strip()]
for r in rows:
    p=data_root/r["sample_path"]
    d=p.read_bytes()
    cnt=r["value_count"]
    assert len(d)==cnt*8
    vals=struct.unpack("<"+"d"*cnt,d)
    assert all(math.isfinite(v) for v in vals)
    assert len(set(vals))>1
print(f"verified {len(rows)} samples total {sum(r['value_count'] for r in rows)}")
PY
echo "[$(date -Is)] verify done $ID"
