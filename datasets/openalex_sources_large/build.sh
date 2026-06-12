#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_sources_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
python3 - <<'PY' "$DOWNLOAD_DIR/openalex_sources_large.json" "$FILTER_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8'))['results']
series = {
 'openalex_source_works_count_u32': ('I', [], 'uint', 32),
 'openalex_source_oa_works_count_u32': ('I', [], 'uint', 32),
 'openalex_source_cited_by_count_u32': ('I', [], 'uint', 32),
 'openalex_source_2yr_mean_citedness_f32': ('f', [], 'float', 32),
 'openalex_source_h_index_u16': ('H', [], 'uint', 16),
 'openalex_source_i10_index_u32': ('I', [], 'uint', 32),
 'openalex_source_first_publication_year_u16': ('H', [], 'uint', 16),
 'openalex_source_last_publication_year_u16': ('H', [], 'uint', 16),
 'openalex_source_topic_count_u8': ('B', [], 'uint', 8),
}
kept = 0
for r in rows:
    try:
        series['openalex_source_works_count_u32'][1].append(int(r['works_count']))
        series['openalex_source_oa_works_count_u32'][1].append(int(r['oa_works_count']))
        series['openalex_source_cited_by_count_u32'][1].append(int(r['cited_by_count']))
        stats = r.get('summary_stats') or {}
        series['openalex_source_2yr_mean_citedness_f32'][1].append(float(stats.get('2yr_mean_citedness') or 0.0))
        series['openalex_source_h_index_u16'][1].append(int(stats.get('h_index') or 0))
        series['openalex_source_i10_index_u32'][1].append(int(stats.get('i10_index') or 0))
        series['openalex_source_first_publication_year_u16'][1].append(int(r.get('first_publication_year') or 0))
        series['openalex_source_last_publication_year_u16'][1].append(int(r.get('last_publication_year') or 0))
        series['openalex_source_topic_count_u8'][1].append(min(len(r.get('topics') or []), 255))
        kept += 1
    except Exception:
        continue
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'sources.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'openalex_sources_large', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': len(rows), 'rows_kept': kept, 'rows_skipped': len(rows) - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))
print('build done dataset=openalex_sources_large')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
