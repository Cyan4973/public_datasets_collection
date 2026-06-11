#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=usgs_fdsn_events_large
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
python3 - <<'PY' "$DOWNLOAD_DIR/usgs_fdsn_events_large.geojson" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src, encoding='utf-8')).get("features", [])
series = {
    "usgs_event_time_ms_i64": ("q", [], "int", 64),
    "usgs_event_magnitude_f32": ("f", [], "float", 32),
    "usgs_event_tsunami_u8": ("B", [], "uint", 8),
    "usgs_event_significance_u16": ("H", [], "uint", 16),
    "usgs_event_nst_i16": ("h", [], "int", 16),
    "usgs_event_gap_i16": ("h", [], "int", 16),
}
kept = 0
for r in rows:
    p = r.get("properties") or {}
    try:
        t = int(p["time"])
        mag = float(p["mag"])
    except Exception:
        continue
    def intval(x, default=-1):
        try: return int(x)
        except Exception: return default
    series["usgs_event_time_ms_i64"][1].append(t)
    series["usgs_event_magnitude_f32"][1].append(mag)
    series["usgs_event_tsunami_u8"][1].append(max(0, intval(p.get("tsunami"), 0)))
    series["usgs_event_significance_u16"][1].append(max(0, intval(p.get("sig"), 0)))
    series["usgs_event_nst_i16"][1].append(intval(p.get("nst"), -1))
    series["usgs_event_gap_i16"][1].append(intval(p.get("gap"), -1))
    kept += 1
with open(os.path.join(index_dir, "samples.jsonl"), "w", encoding="utf-8") as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid)
        os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, "events.bin")
        with open(out, "wb") as f:
            for v in vals:
                f.write(struct.pack("<" + fmt, v))
        idx.write(json.dumps({"dataset_id":"usgs_fdsn_events_large","series_id":sid,"sample_path":out,"numeric_kind":nk,"bit_width":bw,"endianness":"little","element_size_bytes":bw//8,"sample_size_bytes":os.path.getsize(out),"value_count":len(vals)}) + "\n")
json.dump({"rows_total":len(rows),"rows_kept":kept,"rows_skipped":len(rows)-kept,"sample_rows":len(series)}, open(os.path.join(filtered_dir, "ingest_stats.json"), "w", encoding="utf-8"))
print("build done dataset=usgs_fdsn_events_large")
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
