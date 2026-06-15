#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=nasa_donki_cme
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
python3 - <<'PY' "$DOWNLOAD_DIR/nasa_donki_cme.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8'))
series = {
 'donki_cme_active_region_num_u32': ('I', [], 'uint', 32),
 'donki_cme_instrument_count_u8': ('B', [], 'uint', 8),
 'donki_cme_analysis_count_u8': ('B', [], 'uint', 8),
 'donki_cme_speed_f32': ('f', [], 'float', 32),
 'donki_cme_half_angle_f32': ('f', [], 'float', 32),
}
kept = 0
for r in rows:
    begin = r.get('startTime') or r.get('beginTime') or ''
    if len(begin) < 4:
        continue
    analyses = r.get('cmeAnalyses') or []
    first = analyses[0] if analyses else {}
    speed = first.get('speed'); half = first.get('halfAngle')
    series['donki_cme_active_region_num_u32'][1].append(int(r.get('activeRegionNum') or 0))
    series['donki_cme_instrument_count_u8'][1].append(min(len(r.get('instruments') or []), 255))
    series['donki_cme_analysis_count_u8'][1].append(min(len(analyses), 255))
    series['donki_cme_speed_f32'][1].append(float(speed) if speed is not None else float('nan'))
    series['donki_cme_half_angle_f32'][1].append(float(half) if half is not None else float('nan'))
    kept += 1
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'events.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'nasa_donki_cme', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': len(rows), 'rows_kept': kept, 'rows_skipped': len(rows) - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))

print('build done dataset=nasa_donki_cme')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
