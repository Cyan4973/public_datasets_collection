#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="electricity_load_diagrams_uci"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
INDEX_PATH="$INDEX_DIR/samples.jsonl" REPO_ROOT="$REPO_ROOT" DATA_DIR="$DATA_DIR" python3 - <<'PY'
import json, os, struct
from pathlib import Path
index_path = Path(os.environ["INDEX_PATH"])
repo_root = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
MIN_SAMPLES = int(os.environ.get("ELEC_MIN_SAMPLES", "50"))
SERIES_ID = "electricity_load_kw"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
rows = 0
seen_paths = set()
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    rows += 1
    obj = json.loads(line)
    if obj.get("series_id") != SERIES_ID:
        raise SystemExit(f"unexpected series_id: {obj.get('series_id')}")
    if obj.get("numeric_kind") != "float" or int(obj.get("bit_width", 0)) != 32:
        raise SystemExit(f"unexpected representation: {obj}")
    if obj["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {obj['sample_path']}")
    seen_paths.add(obj["sample_path"])
    p = repo_root / data_dir / obj["sample_path"]
    if not p.exists():
        raise SystemExit(f"missing sample: {p}")
    size = p.stat().st_size
    if size != obj["sample_size_bytes"] or size != int(obj["value_count"]) * 4:
        raise SystemExit(f"size mismatch: {p}")
    # full-series non-constant check (leading zero-runs before a client comes
    # online are normal, so a prefix check is not sufficient)
    data = p.read_bytes()
    vmin = vmax = None
    for (v,) in struct.iter_unpack("<f", data):
        if vmin is None or v < vmin: vmin = v
        if vmax is None or v > vmax: vmax = v
    if vmin is None or vmin == vmax:
        raise SystemExit(f"constant sample: {p}")
if rows < MIN_SAMPLES:
    raise SystemExit(f"only {rows} samples < {MIN_SAMPLES}")
print(f"verified_rows={rows} series={SERIES_ID}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
