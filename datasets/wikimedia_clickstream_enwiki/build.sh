#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=wikimedia_clickstream_enwiki
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

python3 - <<'PY' "$DOWNLOAD_DIR/clickstream-enwiki-2024-01.tsv.gz" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import gzip, json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]

vals = []
rows_total = 0
rows_kept = 0
with gzip.open(src, "rt", encoding="utf-8", newline="") as f:
    for line in f:
        rows_total += 1
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        try:
            v = int(parts[3])
        except Exception:
            continue
        if v < 0 or v > 0xFFFFFFFF:
            continue
        vals.append(v)
        rows_kept += 1

sid = "wikimedia_clickstream_count_u32"
sdir = os.path.join(samples_dir, sid)
os.makedirs(sdir, exist_ok=True)
out = os.path.join(sdir, "counts.bin")
with open(out, "wb") as f:
    for v in vals:
        f.write(struct.pack("<I", v))

with open(os.path.join(index_dir, "samples.jsonl"), "w", encoding="utf-8") as idx:
    idx.write(json.dumps({
        "dataset_id": "wikimedia_clickstream_enwiki",
        "series_id": sid,
        "sample_path": out,
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": os.path.getsize(out),
        "value_count": len(vals),
    }) + "\n")

with open(os.path.join(filtered_dir, "ingest_stats.json"), "w", encoding="utf-8") as f:
    json.dump({"rows_total": rows_total, "rows_kept": rows_kept, "rows_skipped": rows_total - rows_kept, "sample_rows": 1}, f)

print("build done dataset=wikimedia_clickstream_enwiki")
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
