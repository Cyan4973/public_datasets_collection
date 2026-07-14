#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gaia_dr3_astrometry_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
INDEX_PATH="$INDEX_DIR/samples.jsonl" REPO_ROOT="$REPO_ROOT" DATA_DIR="$DATA_DIR" python3 - <<'PY'
import json, os, sys
from array import array
from pathlib import Path

index_path = Path(os.environ["INDEX_PATH"])
repo_root = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
EXPECTED = {"gaia_parallax_mas_f32", "gaia_pmra_masyr_f32", "gaia_pmdec_masyr_f32"}
MIN_TOTAL_VALUES = 10000
little = sys.byteorder == "little"

if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")

rows = 0
per_series = {}
seen_paths = set()
total_values = 0
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    rows += 1
    obj = json.loads(line)
    sid = obj.get("series_id")
    if sid not in EXPECTED:
        raise SystemExit(f"unexpected series_id: {sid}")
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
    # independently recompute min/max/constant from the stored float32 bytes
    a = array("f")
    a.frombytes(p.read_bytes())
    if not little:
        a.byteswap()
    if len(a) == 0:
        raise SystemExit(f"empty sample: {p}")
    vmin, vmax = min(a), max(a)
    if vmin == vmax:
        raise SystemExit(f"constant sample: {p}")
    if vmin != obj.get("min") or vmax != obj.get("max"):
        raise SystemExit(f"min/max mismatch for {p}: index=({obj.get('min')},{obj.get('max')}) recomputed=({vmin},{vmax})")
    per_series[sid] = per_series.get(sid, 0) + 1
    total_values += len(a)

if EXPECTED - set(per_series):
    raise SystemExit(f"missing series: {sorted(EXPECTED - set(per_series))}")
counts = set(per_series.values())
if len(counts) != 1:
    raise SystemExit(f"series have unequal sample counts: {per_series}")
n = counts.pop()
if n < 1:
    raise SystemExit("no samples per series")
if rows != len(EXPECTED) * n:
    raise SystemExit(f"expected {len(EXPECTED)*n} samples, got {rows}")
if total_values < MIN_TOTAL_VALUES:
    raise SystemExit(f"total primary values {total_values} < floor {MIN_TOTAL_VALUES}")
print(f"verified_rows={rows} samples_per_series={n} total_values={total_values}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
