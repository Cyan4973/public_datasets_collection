#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="skadi_srtm_bay_area_hgt_i16"
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
import re
import shutil
import struct
from pathlib import Path

DATASET_ID = "skadi_srtm_bay_area_hgt_i16"
SERIES_ID = "skadi_srtm_n37w122_elevation_i16"
TILE = "N37W122"
TILE_VALUES = 3601 * 3601
TILE_BYTES = TILE_VALUES * 2
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

out_dir = samples_dir / SERIES_ID
reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / f"{TILE}.bin"

hgt_path = download_dir / f"{TILE}.hgt.gz"
rows_dir = download_dir / "row_shards"
source_records = []
if hgt_path.exists():
    raw = gzip.decompress(hgt_path.read_bytes())
    if len(raw) != TILE_BYTES:
        raise SystemExit(f"unexpected decoded HGT size: {len(raw)}")
    converted = bytearray(TILE_BYTES)
    converted[0::2] = raw[1::2]
    converted[1::2] = raw[0::2]
    out.write_bytes(converted)
    source_kind = "hgt_gzip"
    source_records.append({"source": hgt_path.name, "source_bytes": hgt_path.stat().st_size, "decoded_bytes": len(raw)})
elif rows_dir.exists():
    pattern = re.compile(rf"^{TILE}_rows_(\d{{4}})_(\d{{4}})\.bin$")
    files = sorted(rows_dir.glob(f"{TILE}_rows_*.bin"))
    if not files:
        raise SystemExit(f"missing row shard files in {rows_dir}")
    expected_start = 0
    with out.open("wb") as dst:
        for path in files:
            match = pattern.match(path.name)
            if not match:
                raise SystemExit(f"unexpected row shard name: {path.name}")
            start = int(match.group(1))
            end = int(match.group(2))
            if start != expected_start:
                raise SystemExit(f"row coverage gap or overlap before row {start}; expected {expected_start}")
            expected_bytes = (end - start + 1) * 3601 * 2
            payload = path.read_bytes()
            if len(payload) != expected_bytes:
                raise SystemExit(f"row shard size mismatch: {path.name} expected {expected_bytes} got {len(payload)}")
            dst.write(payload)
            expected_start = end + 1
            source_records.append({"source": path.name, "source_bytes": len(payload), "row_start": start, "row_end": end})
    if expected_start != 3601:
        raise SystemExit(f"row coverage ended at {expected_start - 1}, expected 3600")
    source_kind = "row_shards"
else:
    raise SystemExit("missing local import; run download.sh first")

size = out.stat().st_size
if size != TILE_BYTES:
    raise SystemExit(f"reconstructed tile size mismatch: expected {TILE_BYTES} got {size}")
if size > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {size}")

with out.open("rb") as fh:
    prefix = fh.read(20000)
if len(set(prefix)) < 2:
    raise SystemExit("degenerate tile prefix")
sample_values = struct.unpack("<" + "h" * (len(prefix) // 2), prefix[: (len(prefix) // 2) * 2])
if all(value == -32768 for value in sample_values):
    raise SystemExit("degenerate all-void tile prefix")

row = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "sample_path": rel(out),
    "numeric_kind": "int",
    "bit_width": 16,
    "endianness": "little",
    "element_size_bytes": 2,
    "sample_size_bytes": size,
    "value_count": TILE_VALUES,
    "tile": TILE,
    "grid_width": 3601,
    "grid_height": 3601,
    "source_kind": source_kind,
}
stats = {
    "dataset_id": DATASET_ID,
    "tile": TILE,
    "sample_count": 1,
    "primary_values": TILE_VALUES,
    "primary_bytes": size,
    "source_kind": source_kind,
    "source_records": source_records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples=1 primary_bytes={size} source_kind={source_kind}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
