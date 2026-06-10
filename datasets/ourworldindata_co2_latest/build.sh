#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=ourworldindata_co2_latest
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
python3 - <<'PY' "$DOWNLOAD_DIR/annual-co2-emissions-per-country.csv" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import csv, json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
series = {
 'owid_co2_year_u16': ('H', [], 'uint', 16),
 'owid_co2_annual_emissions_f64': ('d', [], 'float', 64),
}
rows_total = 0; kept = 0
with open(src, encoding='utf-8', newline='') as f:
    for row in csv.DictReader(f):
        rows_total += 1
        try:
            year = int(row['Year']); co2 = float(row['Annual CO₂ emissions'])
        except Exception:
            continue
        series['owid_co2_year_u16'][1].append(year)
        series['owid_co2_annual_emissions_f64'][1].append(co2)
        kept += 1
with open(os.path.join(index_dir, 'samples.jsonl'), 'w', encoding='utf-8') as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid); os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, 'co2.bin')
        with open(out, 'wb') as f:
            for v in vals: f.write(struct.pack('<' + fmt, v))
        idx.write(json.dumps({'dataset_id': 'ourworldindata_co2_latest', 'series_id': sid, 'sample_path': out, 'numeric_kind': nk, 'bit_width': bw, 'endianness': 'little', 'element_size_bytes': bw // 8, 'sample_size_bytes': os.path.getsize(out), 'value_count': len(vals)}) + '\n')
json.dump({'rows_total': rows_total, 'rows_kept': kept, 'rows_skipped': rows_total - kept, 'sample_rows': len(series)}, open(os.path.join(filtered_dir, 'ingest_stats.json'), 'w', encoding='utf-8'))

print('build done dataset=ourworldindata_co2_latest')
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
