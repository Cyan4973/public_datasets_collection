#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_fonts_ofl_ttf_u8"
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

import json
import os
import shutil
from pathlib import Path

DATASET_ID = "google_fonts_ofl_ttf_u8"
SERIES_ID = "google_fonts_ofl_font_binaries"
MAX_PRIMARY_BYTES = 1_000_000_000
VALID_HEADERS = {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf"}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

selection_path = download_dir / "selection.jsonl"
if not selection_path.exists():
    raise RuntimeError(f"missing selection: {selection_path}")
out_dir = samples_dir / SERIES_ID
reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
seen_paths = set()
for line_number, line in enumerate(selection_path.read_text(encoding="utf-8").splitlines(), start=1):
    row = json.loads(line)
    source_rel = row["local_path"]
    if source_rel in seen_paths:
        raise RuntimeError(f"duplicate font path: {source_rel}")
    seen_paths.add(source_rel)
    source = download_dir / source_rel
    payload = source.read_bytes()
    header = payload[:4]
    if header not in VALID_HEADERS:
        raise RuntimeError(f"{source_rel}: invalid sfnt/OpenType header {header!r}")
    if len(set(payload)) < 2:
        raise RuntimeError(f"{source_rel}: degenerate font payload")
    out = out_dir / f"{line_number:04d}_{source.stem}.bin"
    out.write_bytes(payload)
    index_row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(payload),
        "value_count": len(payload),
    }
    rows.append(index_row)
    records.append(
        {
            "family": row["family"],
            "name": row["name"],
            "source_path": row["path"],
            "sample_path": index_row["sample_path"],
            "bytes": len(payload),
            "values": len(payload),
            "header_hex": header.hex(),
            "distinct_values": len(set(payload)),
        }
    )

total = sum(record["bytes"] for record in records)
if total > MAX_PRIMARY_BYTES:
    raise RuntimeError(f"primary payload exceeds 1 GB cap: {total}")
if len(records) < 40:
    raise RuntimeError(f"too few font samples: {len(records)}")
stats = {"dataset_id": DATASET_ID, "records": records, "record_count": len(records), "total_bytes": total, "total_values": total}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
