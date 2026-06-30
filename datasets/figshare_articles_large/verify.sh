#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_articles_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
import csv
import json
import os
import statistics
import struct
from pathlib import Path

root = Path(os.environ['REPO_ROOT']) / os.environ['DATA_DIR']
rows = [json.loads(line) for line in (Path(os.environ['INDEX_DIR']) / 'samples.jsonl').read_text().splitlines() if line.strip()]
expected = {
    'figshare_id_u32': ('uint', 32, 4, '<I'),
    'figshare_defined_type_u16': ('uint', 16, 2, '<H'),
    'figshare_group_id_u32': ('uint', 32, 4, '<I'),
    'figshare_published_timestamp_i64': ('int', 64, 8, '<q'),
    'figshare_created_timestamp_i64': ('int', 64, 8, '<q'),
    'figshare_modified_timestamp_i64': ('int', 64, 8, '<q'),
}
if {row['series_id'] for row in rows} != set(expected):
    raise SystemExit('unexpected series set')
if len({row['value_count'] for row in rows}) != 1:
    raise SystemExit('series length mismatch')
if sum(row['value_count'] for row in rows) < 100000:
    raise SystemExit('below large-repair value target')
if statistics.median(row['value_count'] for row in rows) < 17000:
    raise SystemExit('median sample count below large-repair target')

for row in rows:
    kind, bits, element_size, fmt = expected[row['series_id']]
    if row['numeric_kind'] != kind or int(row['bit_width']) != bits or int(row['element_size_bytes']) != element_size:
        raise SystemExit(f"encoding mismatch {row['series_id']}")
    path = root / row['sample_path']
    if not path.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    data = path.read_bytes()
    if len(data) != int(row['sample_size_bytes']) or len(data) != int(row['value_count']) * element_size:
        raise SystemExit(f"bad sizing {row['sample_path']}")
    values = [value for (value,) in struct.iter_unpack(fmt, data)]
    if min(values) == max(values):
        raise SystemExit(f"constant sample {row['series_id']}")

with open(Path(os.environ['FILTER_DIR']) / 'stats.tsv', encoding='utf-8') as f:
    stats = list(csv.DictReader(f, delimiter='\t'))
kept = int(stats[0]['kept_count'])
if kept != rows[0]['value_count']:
    raise SystemExit('stats/index retained-count mismatch')
print(f"verified_samples={len(rows)} rows_total={kept} total_values={sum(row['value_count'] for row in rows)} total_bytes={sum(row['sample_size_bytes'] for row in rows)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
