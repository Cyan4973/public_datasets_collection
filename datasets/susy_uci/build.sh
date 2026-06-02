#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="susy_uci"
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
import csv, gzip, json, os, sys
from array import array
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source = extract_dir / "SUSY.csv.gz"
opener = gzip.open if source.exists() else open
if not source.exists():
    source = extract_dir / "SUSY.csv"
if not source.exists():
    raise SystemExit("missing SUSY source file")

little = sys.byteorder == "little"
chunk_rows = 20000

label_dir = samples_dir / "susy_label"
label_dir.mkdir(parents=True, exist_ok=True)
label_path = label_dir / "series.bin"
label_f = label_path.open("wb")
feature_info = []
feature_files = []
for i in range(1, 19):
    sid = f"susy_feat_{i:03d}"
    outdir = samples_dir / sid
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "series.bin"
    feature_info.append((sid, out))
    feature_files.append(out.open("wb"))

label_buf = array("B")
feat_bufs = [array("f") for _ in range(18)]
rows = 0

def flush():
    global label_buf, feat_bufs
    if not label_buf:
        return
    label_buf.tofile(label_f)
    for buf, fh in zip(feat_bufs, feature_files):
        b = buf
        if not little:
            b.byteswap()
        b.tofile(fh)
    label_buf = array("B")
    feat_bufs = [array("f") for _ in range(18)]

with opener(source, "rt", encoding="utf-8", newline="") as fh:
    reader = csv.reader(fh)
    for row in reader:
        if not row:
            continue
        if len(row) != 19:
            raise SystemExit(f"unexpected row width: {len(row)}")
        label = int(float(row[0]))
        if label not in (0, 1):
            raise SystemExit(f"unexpected label: {label}")
        label_buf.append(label)
        for i in range(18):
            feat_bufs[i].append(float(row[i + 1]))
        rows += 1
        if len(label_buf) >= chunk_rows:
            flush()
flush()
label_f.close()
for fh in feature_files:
    fh.close()

filter_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / "inventory.tsv").write_text(f"row_count\n{rows}\n", encoding="utf-8")
index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    out.write(json.dumps({
        "dataset_id": "susy_uci",
        "series_id": "susy_label",
        "sample_path": str(label_path.relative_to(repo / data_dir)),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": label_path.stat().st_size,
        "value_count": rows,
    }, sort_keys=True) + "\n")
    for sid, path in feature_info:
        size = path.stat().st_size
        out.write(json.dumps({
            "dataset_id": "susy_uci",
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
