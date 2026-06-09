#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=noaa_tides_water_level
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

python3 - <<'PY' "$DOWNLOAD_DIR/noaa_tides_water_level.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
from datetime import datetime
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src)).get("data", [])
series = {
    "noaa_tides_level_f64": ("d", [], "float", 64),
    "noaa_tides_sigma_f64": ("d", [], "float", 64),
    "noaa_tides_year_u16": ("H", [], "uint", 16),
    "noaa_tides_month_u8": ("B", [], "uint", 8),
    "noaa_tides_day_u8": ("B", [], "uint", 8),
    "noaa_tides_hour_u8": ("B", [], "uint", 8),
    "noaa_tides_minute_u8": ("B", [], "uint", 8),
    "noaa_tides_q_length_u8": ("B", [], "uint", 8),
}
kept = 0
for r in rows:
    try:
        dt = datetime.strptime(r["t"], "%Y-%m-%d %H:%M")
        level = float(r["v"])
        sigma = float(r["s"])
    except Exception:
        continue
    series["noaa_tides_level_f64"][1].append(level)
    series["noaa_tides_sigma_f64"][1].append(sigma)
    series["noaa_tides_year_u16"][1].append(dt.year)
    series["noaa_tides_month_u8"][1].append(dt.month)
    series["noaa_tides_day_u8"][1].append(dt.day)
    series["noaa_tides_hour_u8"][1].append(dt.hour)
    series["noaa_tides_minute_u8"][1].append(dt.minute)
    series["noaa_tides_q_length_u8"][1].append(len(r.get("q") or ""))
    kept += 1

index_path = os.path.join(index_dir, "samples.jsonl")
with open(index_path, "w", encoding="utf-8") as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid)
        os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, "matches.bin")
        with open(out, "wb") as f:
            for v in vals:
                f.write(struct.pack("<" + fmt, v))
        idx.write(json.dumps({
            "dataset_id": "noaa_tides_water_level",
            "series_id": sid,
            "sample_path": out,
            "numeric_kind": nk,
            "bit_width": bw,
            "endianness": "little",
            "element_size_bytes": bw // 8,
            "sample_size_bytes": os.path.getsize(out),
            "value_count": len(vals),
        }) + "\n")

with open(os.path.join(filtered_dir, "ingest_stats.json"), "w", encoding="utf-8") as f:
    json.dump({"rows_total": len(rows), "rows_kept": kept, "rows_skipped": len(rows) - kept, "sample_rows": len(series)}, f)

print("[%s] build done dataset=noaa_tides_water_level" % __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"))
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
