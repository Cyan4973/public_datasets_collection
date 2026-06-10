#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=nvd_cpe_match_feed
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

python3 - <<'PY' "$DOWNLOAD_DIR/nvd_cpe_match_feed.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import calendar, datetime as dt, json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]

payload = json.load(open(src, encoding="utf-8"))
rows = payload.get("matchStrings", [])
series = {
    "nvd_cpe_created_at_u32": [],
    "nvd_cpe_last_modified_at_u32": [],
    "nvd_cpe_cpe_last_modified_at_u32": [],
    "nvd_cpe_match_count_u16": [],
}

def ts(s):
    return calendar.timegm(dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").utctimetuple())

rows_total = len(rows)
rows_kept = 0
for wrap in rows:
    m = wrap.get("matchString", {})
    try:
        created = ts(m["created"])
        last_modified = ts(m["lastModified"])
        cpe_last_modified = ts(m["cpeLastModified"])
        match_count = len(m.get("matches", []))
    except Exception:
        continue
    series["nvd_cpe_created_at_u32"].append(created)
    series["nvd_cpe_last_modified_at_u32"].append(last_modified)
    series["nvd_cpe_cpe_last_modified_at_u32"].append(cpe_last_modified)
    series["nvd_cpe_match_count_u16"].append(match_count)
    rows_kept += 1

meta = {
    "nvd_cpe_created_at_u32": ("I", "uint", 32),
    "nvd_cpe_last_modified_at_u32": ("I", "uint", 32),
    "nvd_cpe_cpe_last_modified_at_u32": ("I", "uint", 32),
    "nvd_cpe_match_count_u16": ("H", "uint", 16),
}

with open(os.path.join(index_dir, "samples.jsonl"), "w", encoding="utf-8") as idx:
    for sid, vals in series.items():
        code, nk, bw = meta[sid]
        sdir = os.path.join(samples_dir, sid)
        os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, "matches.bin")
        with open(out, "wb") as f:
            for v in vals:
                f.write(struct.pack("<" + code, v))
        idx.write(json.dumps({
            "dataset_id": "nvd_cpe_match_feed",
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
    json.dump({"rows_total": rows_total, "rows_kept": rows_kept, "rows_skipped": rows_total - rows_kept, "sample_rows": len(series)}, f)

print("build done dataset=nvd_cpe_match_feed")
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
