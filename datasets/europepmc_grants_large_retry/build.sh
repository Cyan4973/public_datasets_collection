#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="europepmc_grants_large_retry"
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
python3 - <<'PY' "$DOWNLOAD_DIR/europepmc_grants_large_retry.json" "$FILTER_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8'))['resultList']['result']
series = {
 'europepmc_pubyear_u16': ('H', [], 'uint', 16),
 'europepmc_cited_by_count_u16': ('H', [], 'uint', 16),
 'europepmc_author_count_u16': ('H', [], 'uint', 16),
 'europepmc_title_length_u16': ('H', [], 'uint', 16),
}
kept = 0
for r in rows:
    try: pubyear = int(r['pubYear'])
    except Exception: continue
    try: cited = int(r.get('citedByCount') or 0)
    except Exception: cited = 0
    a = r.get('authorString') or ''
    author_count = len([x for x in a.split(',') if x.strip()]) if a else 0
    series['europepmc_pubyear_u16'][1].append(pubyear)
    series['europepmc_cited_by_count_u16'][1].append(cited)
    series['europepmc_author_count_u16'][1].append(min(author_count, 65535))
    series['europepmc_title_length_u16'][1].append(min(len(r.get('title') or ''), 65535))
    kept += 1
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'results.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'europepmc_grants_large_retry', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': len(rows), 'rows_kept': kept, 'rows_skipped': len(rows) - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))
print('build done dataset=europepmc_grants_large_retry')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
