#!/usr/bin/env bash
# Independently re-decode every pinned epoch and check each sample file and
# index row; reject degenerate or constant segments.
set -euo pipefail

DATASET_ID="earthscope_4p_mt_magnetic_field_counts_i32"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DL_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/mt_mseed.py" selftest
python3 -I "$RECIPE_DIR/scripts/mt_mseed.py" verify \
  --selection "$RECIPE_DIR/selection.tsv" \
  --station-dir "$DL_DIR/station" \
  --downloads "$DL_DIR/mseed" \
  --data-root "$DATA_ROOT"

# manifest totals must match the realized index
python3 -I - "$RECIPE_DIR/manifest.toml" "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" <<'EOF'
import json, sys, tomllib
manifest = tomllib.load(open(sys.argv[1], "rb"))
rows = [json.loads(line) for line in open(sys.argv[2], encoding="utf-8") if line.strip()]
for series in manifest["series"]:
    mine = [r for r in rows if r["series_id"] == series["id"]]
    count, size = len(mine), sum(r["sample_size_bytes"] for r in mine)
    if (count, size) != (series["sample_count"], series["total_size_bytes"]):
        sys.exit(f"manifest {series['id']}: declared {series['sample_count']}/{series['total_size_bytes']} realized {count}/{size}")
    print(f"manifest totals ok: {series['id']} samples={count} bytes={size}")
EOF

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
