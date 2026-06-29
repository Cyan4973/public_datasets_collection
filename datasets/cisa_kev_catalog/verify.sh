#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="cisa_kev_catalog"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PYV'
import json, os, struct
from pathlib import Path
root = Path(os.environ['REPO_ROOT']) / os.environ['DATA_DIR']
stats = json.loads((Path(os.environ['FILTER_DIR'])/'ingest_stats.json').read_text())
rows = [json.loads(line) for line in (Path(os.environ['INDEX_DIR'])/'samples.jsonl').read_text().splitlines() if line.strip()]
expected = {
    'cisa_kev_cwe_count': ('uint', 16, 2, '<H'),
    'cisa_kev_known_ransomware': ('uint', 8, 1, '<B'),
    'cisa_kev_description_length': ('uint', 16, 2, '<H'),
    'cisa_kev_date_added_year': ('uint', 16, 2, '<H'),
    'cisa_kev_due_year': ('uint', 16, 2, '<H'),
    'cisa_kev_date_added_ymd_u32': ('uint', 32, 4, '<I'),
    'cisa_kev_due_ymd_u32': ('uint', 32, 4, '<I'),
}
if {row['series_id'] for row in rows} != set(expected): raise SystemExit(f'unexpected series set')
if sum(row['value_count'] for row in rows) < 10_000 and sum(row['sample_size_bytes'] for row in rows) < 102_400:
    raise SystemExit('below aggregate floor')
for row in rows:
    kind, bits, element_size, fmt = expected[row['series_id']]
    if row['numeric_kind'] != kind or int(row['bit_width']) != bits or int(row['element_size_bytes']) != element_size:
        raise SystemExit(f"encoding mismatch {row['series_id']}")
    p = root / row['sample_path']
    if not p.is_file(): raise SystemExit(f"missing sample {row['sample_path']}")
    if row['sample_size_bytes'] != p.stat().st_size: raise SystemExit(f"size mismatch {row['sample_path']}")
    if row['value_count'] * row['element_size_bytes'] != row['sample_size_bytes']: raise SystemExit(f"bad sizing {row['sample_path']}")
    values = [value for (value,) in struct.iter_unpack(fmt, p.read_bytes())]
    if min(values) == max(values): raise SystemExit(f"constant sample {row['series_id']}")
print(f"verified_samples={len(rows)} rows_total={stats['rows_total']} rows_skipped={stats['rows_skipped']}")
PYV
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
