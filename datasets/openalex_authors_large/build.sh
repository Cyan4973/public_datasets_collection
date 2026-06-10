#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=openalex_authors_large
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
python3 - <<'PY' "$DOWNLOAD_DIR/openalex_authors_large.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8'))['results']
series = {
 'openalex_author_works_count_u32': ('I', [], 'uint', 32),
 'openalex_author_cited_by_count_u32': ('I', [], 'uint', 32),
 'openalex_author_h_index_u16': ('H', [], 'uint', 16),
 'openalex_author_i10_index_u16': ('H', [], 'uint', 16),
 'openalex_author_raw_name_count_u8': ('B', [], 'uint', 8),
 'openalex_author_affiliation_count_u8': ('B', [], 'uint', 8),
 'openalex_author_topic_count_u8': ('B', [], 'uint', 8),
}
kept = 0
for r in rows:
    try:
        works = int(r['works_count']); cited = int(r['cited_by_count'])
    except Exception:
        continue
    stats = r.get('summary_stats') or {}
    series['openalex_author_works_count_u32'][1].append(works)
    series['openalex_author_cited_by_count_u32'][1].append(cited)
    series['openalex_author_h_index_u16'][1].append(int(stats.get('h_index') or 0))
    series['openalex_author_i10_index_u16'][1].append(int(stats.get('i10_index') or 0))
    series['openalex_author_raw_name_count_u8'][1].append(min(len(r.get('raw_author_names') or []), 255))
    series['openalex_author_affiliation_count_u8'][1].append(min(len(r.get('affiliations') or []), 255))
    series['openalex_author_topic_count_u8'][1].append(min(len(r.get('topics') or []), 255))
    kept += 1
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'authors.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'openalex_authors_large', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': len(rows), 'rows_kept': kept, 'rows_skipped': len(rows) - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))

print('build done dataset=openalex_authors_large')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
