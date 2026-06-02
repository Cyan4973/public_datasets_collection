#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="yearpredictionmsd_uci"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import csv, json, os, struct, sys
from array import array
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source = extract_dir / "YearPredictionMSD.txt"
if not source.exists():
    raise SystemExit(f"missing source: {source}")

little = sys.byteorder == "little"
chunk_rows = 20000

year_dir = samples_dir / "msd_year"
year_dir.mkdir(parents=True, exist_ok=True)
year_path = year_dir / "series.bin"
year_f = year_path.open("wb")
feature_paths = []
feature_files = []
for i in range(1, 91):
    sid = f"msd_feat_{i:03d}"
    outdir = samples_dir / sid
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "series.bin"
    feature_paths.append((sid, out))
    feature_files.append(out.open("wb"))

year_buf = array("H")
feat_bufs = [array("f") for _ in range(90)]
rows = 0

def flush():
    global year_buf, feat_bufs
    if not year_buf:
        return
    y = year_buf
    if not little:
        y.byteswap()
    y.tofile(year_f)
    for buf, fh in zip(feat_bufs, feature_files):
        b = buf
        if not little:
            b.byteswap()
        b.tofile(fh)
    year_buf = array("H")
    feat_bufs = [array("f") for _ in range(90)]

with source.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh)
    for row in reader:
        if not row:
            continue
        if len(row) != 91:
            raise SystemExit(f"unexpected row width: {len(row)}")
        year = int(float(row[0]))
        year_buf.append(year)
        for i in range(90):
            feat_bufs[i].append(float(row[i + 1]))
        rows += 1
        if len(year_buf) >= chunk_rows:
            flush()
flush()
year_f.close()
for fh in feature_files:
    fh.close()

filter_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / "inventory.tsv").write_text(f"row_count\n{rows}\n", encoding="utf-8")
index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    year_stat = year_path.stat().st_size
    out.write(json.dumps({
        "dataset_id": "yearpredictionmsd_uci",
        "series_id": "msd_year",
        "sample_path": str(year_path.relative_to(repo / data_dir)),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": year_stat,
        "value_count": rows,
    }, sort_keys=True) + "\n")
    for sid, path in feature_paths:
        size = path.stat().st_size
        out.write(json.dumps({
            "dataset_id": "yearpredictionmsd_uci",
            "series_id": sid,
            "sample_path": str(path.relative_to(repo / data_dir)),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": rows,
        }, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
