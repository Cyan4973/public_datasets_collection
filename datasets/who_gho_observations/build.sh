#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=who_gho_observations
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

python3 - <<'PY' "$DOWNLOAD_DIR/who_gho_observations.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows = json.load(open(src)).get("value", [])

def slen(v): return len(v or "")
series = {
    "who_gho_numeric_value_f64": ("d", [], "float", 64),
    "who_gho_time_dim_u16": ("H", [], "uint", 16),
    "who_gho_record_id_u32": ("I", [], "uint", 32),
    "who_gho_spatial_dim_length_u8": ("B", [], "uint", 8),
    "who_gho_parent_location_length_u8": ("B", [], "uint", 8),
    "who_gho_dim1_length_u8": ("B", [], "uint", 8),
    "who_gho_dim2_length_u8": ("B", [], "uint", 8),
    "who_gho_low_f64": ("d", [], "float", 64),
    "who_gho_high_f64": ("d", [], "float", 64),
}
kept = 0
for r in rows:
    nv = r.get("NumericValue")
    td = r.get("TimeDim")
    rid = r.get("Id")
    if nv is None or td is None or rid is None:
        continue
    try:
        series["who_gho_numeric_value_f64"][1].append(float(nv))
        series["who_gho_time_dim_u16"][1].append(int(td))
        series["who_gho_record_id_u32"][1].append(int(rid))
    except Exception:
        continue
    series["who_gho_spatial_dim_length_u8"][1].append(slen(r.get("SpatialDim")))
    series["who_gho_parent_location_length_u8"][1].append(slen(r.get("ParentLocation")))
    series["who_gho_dim1_length_u8"][1].append(slen(r.get("Dim1")))
    series["who_gho_dim2_length_u8"][1].append(slen(r.get("Dim2")))
    series["who_gho_low_f64"][1].append(float(r["Low"]) if r.get("Low") is not None else float("nan"))
    series["who_gho_high_f64"][1].append(float(r["High"]) if r.get("High") is not None else float("nan"))
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
            "dataset_id": "who_gho_observations",
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

print("[%s] build done dataset=who_gho_observations" % __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"))
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
