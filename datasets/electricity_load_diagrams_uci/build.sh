#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="electricity_load_diagrams_uci"
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
import csv, json, os, sys
from array import array
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source = extract_dir / "LD2011_2014.txt"
if not source.exists():
    raise SystemExit(f"missing source: {source}")

with source.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh, delimiter=";", quotechar='"')
    header = next(reader)
if len(header) < 2:
    raise SystemExit("unexpected header")
meters = header[1:]
n = len(meters)
little = sys.byteorder == "little"
chunk_rows = 10000

meter_info = []
files = []
for name in meters:
    sid = name.strip().replace('"', "").lower().replace("_", "")
    outdir = samples_dir / sid
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "series.bin"
    meter_info.append((sid, out))
    files.append(out.open("wb"))

bufs = [array("f") for _ in range(n)]
rows = 0
first_ts = None
last_ts = None

def flush():
    global bufs
    if not bufs or not bufs[0]:
        return
    for buf, fh in zip(bufs, files):
        b = buf
        if not little:
            b.byteswap()
        b.tofile(fh)
    bufs = [array("f") for _ in range(n)]

with source.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh, delimiter=";", quotechar='"')
    next(reader)
    for row in reader:
        if not row:
            continue
        if len(row) != n + 1:
            raise SystemExit(f"unexpected row width: {len(row)}")
        ts = row[0]
        if first_ts is None:
            first_ts = ts
        last_ts = ts
        for i, value in enumerate(row[1:]):
            bufs[i].append(float(value.replace(",", ".")))
        rows += 1
        if len(bufs[0]) >= chunk_rows:
            flush()
flush()
for fh in files:
    fh.close()

filter_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / "inventory.tsv").write_text(
    f"row_count\tmeter_count\tfirst_timestamp\tlast_timestamp\n{rows}\t{n}\t{first_ts}\t{last_ts}\n",
    encoding="utf-8",
)
index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for sid, path in meter_info:
        size = path.stat().st_size
        out.write(json.dumps({
            "dataset_id": "electricity_load_diagrams_uci",
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
