#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=npi_registry_ca
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

python3 - <<'PY' "$DOWNLOAD_DIR/npi_registry_ca.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
obj = json.load(open(src))
rows = obj[3]
series = {
    "npi_registry_npi_u64": ("Q", [], "uint", 64),
    "npi_registry_name_length_u16": ("H", [], "uint", 16),
    "npi_registry_taxonomy_length_u16": ("H", [], "uint", 16),
    "npi_registry_address_length_u16": ("H", [], "uint", 16),
}
kept = 0
for row in rows:
    if not isinstance(row, list) or len(row) < 4:
        continue
    try:
        npi = int(row[1])
    except Exception:
        continue
    series["npi_registry_npi_u64"][1].append(npi)
    series["npi_registry_name_length_u16"][1].append(len(row[0] or ""))
    series["npi_registry_taxonomy_length_u16"][1].append(len(row[2] or ""))
    series["npi_registry_address_length_u16"][1].append(len(row[3] or ""))
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
            "dataset_id": "npi_registry_ca",
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

print("[%s] build done dataset=npi_registry_ca" % __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"))
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
