#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=who_gho_observations
INDEX_PATH="$DATA_DIR/index/$DATASET_ID/samples.jsonl"
FILTERED_PATH="$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/verify.$TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE") 2>&1

python3 - <<'PY' "$INDEX_PATH" "$FILTERED_PATH"
import json, os, sys
idx, stats = sys.argv[1:3]
rows = [json.loads(line) for line in open(idx)]
st = json.load(open(stats))
assert len(rows) == 8
for r in rows:
    assert os.path.exists(r["sample_path"])
    assert r["sample_size_bytes"] == os.path.getsize(r["sample_path"])
    assert r["value_count"] == st["rows_kept"]
print(f"verified_samples={len(rows)} rows_total={st['rows_total']} rows_skipped={st['rows_skipped']}")
print("[%s] verify done dataset=who_gho_observations" % __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"))
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
