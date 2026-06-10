#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=gdc_cases
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTERED_DIR="$DATA_DIR/filtered/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR" "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/build.$TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE") 2>&1
python3 - <<'PY' "$DOWNLOAD_DIR/gdc_cases.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8'))['data']['hits']
series = {
 'gdc_case_project_id_length_u8': ('B', [], 'uint', 8),
 'gdc_case_submitter_id_length_u8': ('B', [], 'uint', 8),
 'gdc_case_diagnosis_count_u8': ('B', [], 'uint', 8),
 'gdc_case_age_at_diagnosis_i32': ('i', [], 'int', 32),
}
kept = 0
for r in rows:
    project = ((r.get('project') or {}).get('project_id') or '')
    submitter = (r.get('submitter_id') or '')
    if not project or not submitter:
        continue
    diags = r.get('diagnoses') or []
    age = -1
    if diags and isinstance(diags, list):
        try: age = int(diags[0].get('age_at_diagnosis'))
        except Exception: age = -1
    series['gdc_case_project_id_length_u8'][1].append(min(len(project), 255))
    series['gdc_case_submitter_id_length_u8'][1].append(min(len(submitter), 255))
    series['gdc_case_diagnosis_count_u8'][1].append(min(len(diags), 255))
    series['gdc_case_age_at_diagnosis_i32'][1].append(age)
    kept += 1
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'cases.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'gdc_cases', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': len(rows), 'rows_kept': kept, 'rows_skipped': len(rows) - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))

print('build done dataset=gdc_cases')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
