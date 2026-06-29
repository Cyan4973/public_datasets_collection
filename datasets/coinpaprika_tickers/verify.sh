#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="coinpaprika_tickers"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
import json, os, struct
from pathlib import Path
root = Path(os.environ['REPO_ROOT']) / os.environ['DATA_DIR']
stats = json.loads((Path(os.environ['FILTER_DIR'])/'ingest_stats.json').read_text())
rows = [json.loads(line) for line in (Path(os.environ['INDEX_DIR'])/'samples.jsonl').read_text().splitlines() if line.strip()]
expected = {
    "coinpaprika_rank": ("uint", 16, 2, "<H"),
    "coinpaprika_price_usd": ("float", 64, 8, "<d"),
    "coinpaprika_market_cap_usd": ("float", 64, 8, "<d"),
    "coinpaprika_volume_24h_usd": ("float", 64, 8, "<d"),
    "coinpaprika_volume_24h_change_pct_f64": ("float", 64, 8, "<d"),
    "coinpaprika_market_cap_change_24h_pct_f64": ("float", 64, 8, "<d"),
    "coinpaprika_percent_change_7d_f64": ("float", 64, 8, "<d"),
    "coinpaprika_ath_price_usd_f64": ("float", 64, 8, "<d"),
}
if {row["series_id"] for row in rows} != set(expected): raise SystemExit(f'unexpected series set')
if sum(row["value_count"] for row in rows) < 10_000 and sum(row["sample_size_bytes"] for row in rows) < 102_400:
    raise SystemExit("below aggregate floor")
for row in rows:
    kind, bits, element_size, fmt = expected[row["series_id"]]
    if row["numeric_kind"] != kind or int(row["bit_width"]) != bits or int(row["element_size_bytes"]) != element_size:
        raise SystemExit(f'encoding mismatch {row["series_id"]}')
    p = root / row['sample_path']
    if not p.is_file(): raise SystemExit(f'missing sample {row["sample_path"]}')
    if row['sample_size_bytes'] != p.stat().st_size: raise SystemExit(f'size mismatch {row["sample_path"]}')
    if row['value_count'] * row['element_size_bytes'] != row['sample_size_bytes']: raise SystemExit(f'bad sizing {row["sample_path"]}')
    values = [value for (value,) in struct.iter_unpack(fmt, p.read_bytes())]
    if min(values) == max(values): raise SystemExit(f'constant sample {row["series_id"]}')
print(f'verified_samples={len(rows)} rows_total={stats["rows_total"]} rows_skipped={stats["rows_skipped"]}')
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
