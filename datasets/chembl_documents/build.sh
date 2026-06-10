#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=chembl_documents
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
python3 - <<'PY' "$DOWNLOAD_DIR/chembl_documents.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8'))['documents']
series = {
 'chembl_doc_src_id_u16': ('H', [], 'uint', 16),
 'chembl_doc_year_u16': ('H', [], 'uint', 16),
 'chembl_doc_title_length_u16': ('H', [], 'uint', 16),
 'chembl_doc_abstract_length_u16': ('H', [], 'uint', 16),
}
kept = 0
for r in rows:
    try: src_id = int(r['src_id'])
    except Exception: continue
    try: year = int(r.get('year') or 0)
    except Exception: year = 0
    series['chembl_doc_src_id_u16'][1].append(src_id)
    series['chembl_doc_year_u16'][1].append(year)
    series['chembl_doc_title_length_u16'][1].append(min(len(r.get('title') or ''), 65535))
    series['chembl_doc_abstract_length_u16'][1].append(min(len(r.get('abstract') or ''), 65535))
    kept += 1
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'documents.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'chembl_documents', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': len(rows), 'rows_kept': kept, 'rows_skipped': len(rows) - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))

print('build done dataset=chembl_documents')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
