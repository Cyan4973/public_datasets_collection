#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ourworldindata_energy_mix"
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
import json, os
from pathlib import Path
root=Path(os.environ['REPO_ROOT']) / os.environ['DATA_DIR']
stats=json.loads((Path(os.environ['FILTER_DIR'])/'ingest_stats.json').read_text())
import struct
EXPECTED={'owid_energy_mix_fossil_fuels_f32','owid_energy_mix_nuclear_f32','owid_energy_mix_renewables_f32'}
rows=[json.loads(line) for line in (Path(os.environ['INDEX_DIR'])/'samples.jsonl').read_text().splitlines() if line.strip()]
if {r['series_id'] for r in rows} != EXPECTED: raise SystemExit(f"unexpected series {sorted(r['series_id'] for r in rows)}")
for row in rows:
 if row['numeric_kind'] != 'float' or int(row['bit_width']) != 32: raise SystemExit(f"not float32 {row['series_id']}")
 p=root / row['sample_path']
 if not p.is_file(): raise SystemExit(f"missing sample {row['sample_path']}")
 if row['sample_size_bytes'] != p.stat().st_size: raise SystemExit(f"size mismatch {row['sample_path']}")
 if row['value_count']*4 != row['sample_size_bytes']: raise SystemExit(f"bad sizing {row['sample_path']}")
 vals=[v for (v,) in struct.iter_unpack('<f', p.read_bytes())]
 if len(vals) != row['value_count']: raise SystemExit(f"count mismatch {row['sample_path']}")
 if len(set(vals)) <= 1: raise SystemExit(f"constant sample {row['sample_path']}")
print(f"verified_samples={len(rows)} rows_total={stats['rows_total']} rows_skipped={stats['rows_skipped']}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
