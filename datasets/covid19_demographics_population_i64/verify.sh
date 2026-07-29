#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
ID="covid19_demographics_population_i64"
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
import json, struct, statistics, os
repo=Path(os.environ["REPO_ROOT"])
data_root=repo/Path(os.environ["DATA_DIR"])
idx=Path(os.environ["INDEX_DIR"])/"samples.jsonl"
rows=[json.loads(l) for l in idx.read_text().splitlines() if l.strip()]
counts=[r["value_count"] for r in rows]
print(f"verified samples={len(rows)} median={statistics.median(counts)} total={sum(counts)}")
PY
echo "[$(date -Is)] verify done $ID"
