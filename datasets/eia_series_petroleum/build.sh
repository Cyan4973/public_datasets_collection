#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_series_petroleum"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations
import json, os, shutil, struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

data = json.load(open(download_dir / "eia_series_petroleum.json", encoding="utf-8"))["response"]["data"]
vals = {
    "eia_petroleum_value": [],
    "eia_petroleum_period_year": [],
    "eia_petroleum_period_month": [],
    "eia_petroleum_period_day": [],
    "eia_petroleum_area_name_length": [],
    "eia_petroleum_product_name_length": [],
    "eia_petroleum_process_name_length": [],
}
skipped = 0

for sid in vals:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

for row in data:
    try:
        year_s, month_s, day_s = row["period"].split("-")
        vals["eia_petroleum_value"].append(float(row["value"]))
        vals["eia_petroleum_period_year"].append(int(year_s))
        vals["eia_petroleum_period_month"].append(int(month_s))
        vals["eia_petroleum_period_day"].append(int(day_s))
        vals["eia_petroleum_area_name_length"].append(len(row["area-name"]))
        vals["eia_petroleum_product_name_length"].append(len(row["product-name"]))
        vals["eia_petroleum_process_name_length"].append(len(row["process-name"]))
    except Exception:
        skipped += 1

meta = {
    "eia_petroleum_value": ("float", 32, "f"),
    "eia_petroleum_period_year": ("uint", 16, "H"),
    "eia_petroleum_period_month": ("uint", 8, "B"),
    "eia_petroleum_period_day": ("uint", 8, "B"),
    "eia_petroleum_area_name_length": ("uint", 8, "B"),
    "eia_petroleum_product_name_length": ("uint", 8, "B"),
    "eia_petroleum_process_name_length": ("uint", 8, "B"),
}

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append({
        "dataset_id": "eia_series_petroleum",
        "series_id": sid,
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": kind,
        "bit_width": bits,
        "endianness": "little",
        "element_size_bytes": bits // 8,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(values),
    })

(filter_dir / "ingest_stats.json").write_text(
    json.dumps({"dataset_id": "eia_series_petroleum", "rows_total": len(data), "rows_skipped": skipped}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
