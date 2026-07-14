#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="statlog_landsat_satellite_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
INDEX_PATH="$INDEX_DIR/samples.jsonl" REPO_ROOT="$REPO_ROOT" DATA_DIR="$DATA_DIR" python3 - <<'PY'
import json, os
from pathlib import Path

index_path = Path(os.environ["INDEX_PATH"])
repo_root = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
EXPECTED = {
    "landsat_band_green_u8",
    "landsat_band_red_u8",
    "landsat_band_nir1_u8",
    "landsat_band_nir2_u8",
}
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")

rows = 0
per_series = {}
seen_paths = set()
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    rows += 1
    obj = json.loads(line)
    sid = obj.get("series_id")
    if sid not in EXPECTED:
        raise SystemExit(f"unexpected series_id: {sid}")
    if obj.get("numeric_kind") != "uint" or int(obj.get("bit_width", 0)) != 8:
        raise SystemExit(f"unexpected representation: {obj}")
    if obj["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {obj['sample_path']}")
    seen_paths.add(obj["sample_path"])
    p = repo_root / data_dir / obj["sample_path"]
    if not p.exists():
        raise SystemExit(f"missing sample: {p}")
    size = p.stat().st_size
    if size != obj["sample_size_bytes"] or size != int(obj["value_count"]):
        raise SystemExit(f"size mismatch: {p}")
    # independent degenerate-output check: reject empty or constant samples
    data = p.read_bytes()
    if len(data) == 0 or min(data) == max(data):
        raise SystemExit(f"empty or constant sample: {p}")
    per_series[sid] = per_series.get(sid, 0) + 1

if rows != 8:
    raise SystemExit(f"expected 8 samples (4 bands x 2 splits), got {rows}")
for sid in EXPECTED:
    if per_series.get(sid) != 2:
        raise SystemExit(f"series {sid} has {per_series.get(sid)} samples, expected 2")
print(f"verified_rows={rows} series={sorted(EXPECTED)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
