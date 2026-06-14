#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ucsc_hg38_chromosomes_u8"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import shutil
from pathlib import Path

DATASET_ID = "ucsc_hg38_chromosomes_u8"
PRIMARY = [f"chr{i}" for i in range(1, 23)] + ["chrX", "chrY", "chrM"]
PRIMARY_SET = set(PRIMARY)
ALLOWED = set(b"ACGTRYSWKMBDHVNacgtryswkmbdhvn")

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "hg38.fa.gz"

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

out_dir = samples_dir / "hg38_primary_chromosome_bases"
reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
seen: set[str] = set()
current_name: str | None = None
current_header = ""
current_fh = None
current_path: Path | None = None
current_values = 0
current_distinct: set[int] = set()

def close_record() -> None:
    global current_name, current_header, current_fh, current_path, current_values, current_distinct
    if current_fh is None:
        return
    current_fh.close()
    assert current_name is not None and current_path is not None
    if current_values == 0:
        raise RuntimeError(f"{current_name}: empty sequence")
    if len(current_distinct) < 2:
        raise RuntimeError(f"{current_name}: degenerate sequence")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": "hg38_primary_chromosome_bases",
        "sample_path": rel(current_path),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": current_values,
        "value_count": current_values,
    }
    rows.append(row)
    records.append(
        {
            "name": current_name,
            "header": current_header,
            "sample_path": row["sample_path"],
            "values": current_values,
            "bytes": current_values,
            "distinct_values": len(current_distinct),
            "min": min(current_distinct),
            "max": max(current_distinct),
        }
    )
    current_name = None
    current_header = ""
    current_fh = None
    current_path = None
    current_values = 0
    current_distinct = set()

with gzip.open(archive, "rb") as fh:
    for raw in fh:
        if raw.startswith(b">"):
            close_record()
            header = raw[1:].strip().decode("ascii", "strict")
            name = header.split(None, 1)[0]
            if name in PRIMARY_SET:
                seen.add(name)
                current_name = name
                current_header = header
                current_path = out_dir / f"{PRIMARY.index(name) + 1:02d}_{name}.bin"
                current_fh = current_path.open("wb")
            continue
        if current_fh is None:
            continue
        seq = raw.strip()
        bad = set(seq) - ALLOWED
        if bad:
            raise RuntimeError(f"{current_name}: unexpected sequence byte(s) {sorted(bad)}")
        current_fh.write(seq)
        current_values += len(seq)
        current_distinct.update(seq)
close_record()

missing = [name for name in PRIMARY if name not in seen]
if missing:
    raise RuntimeError(f"missing primary chromosomes: {missing}")
rows.sort(key=lambda row: PRIMARY.index(Path(row["sample_path"]).stem.split("_", 1)[1]))
stats = {
    "dataset_id": DATASET_ID,
    "source": rel(archive),
    "records": records,
    "record_count": len(records),
    "total_values": sum(record["values"] for record in records),
    "total_bytes": sum(record["bytes"] for record in records),
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for row in rows:
        out.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
