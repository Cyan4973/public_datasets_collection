#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="physionet_mitbih_annotation_codes_u8"
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

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export MITBIH_ANN_MIN_VALUES="${MITBIH_ANN_MIN_VALUES:-1000}"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path

DATASET_ID = "physionet_mitbih_annotation_codes_u8"
SERIES_ID = "mitbih_wfdb_annotation_type_u8"
MIN_VALUES = int(os.environ["MITBIH_ANN_MIN_VALUES"])

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def parse_atr(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < 2 or len(data) % 2 != 0:
        raise ValueError(f"{path.name}: malformed WFDB annotation length {len(data)}")
    i = 0
    codes: list[int] = []
    while i + 1 < len(data):
        word = data[i] | (data[i + 1] << 8)
        i += 2
        ann_type = word >> 10
        interval = word & 0x03FF
        if ann_type == 0:
            if interval == 0:
                break
            continue
        if ann_type == 59:
            if i + 4 > len(data):
                raise ValueError(f"{path.name}: truncated SKIP annotation")
            i += 4
            continue
        if ann_type in {60, 61, 62}:
            continue
        if ann_type == 63:
            aux_len = interval
            skip = aux_len
            if skip % 2:
                skip += 1
            if i + skip > len(data):
                raise ValueError(f"{path.name}: AUX annotation overruns file")
            i += skip
            continue
        if 1 <= ann_type <= 49:
            codes.append(ann_type)
            continue
        raise ValueError(f"{path.name}: unsupported annotation type {ann_type} interval={interval}")
    return codes


records_file = download_dir / "RECORDS.selected"
if not records_file.exists():
    records_file = download_dir / "RECORDS"
if not records_file.exists():
    raise SystemExit(f"missing record list: {records_file}")
records = [line.strip() for line in records_file.read_text(encoding="utf-8").splitlines() if line.strip()]
if not records:
    raise SystemExit("empty record list")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
record_stats: list[dict[str, object]] = []
skipped_tiny = 0
skipped_constant = 0

for rec in records:
    atr = download_dir / f"{rec}.atr"
    if not atr.exists():
        raise SystemExit(f"missing annotation file: {atr}")
    codes = parse_atr(atr)
    hist = Counter(codes)
    stat = {
        "record": rec,
        "source_file": atr.name,
        "source_bytes": atr.stat().st_size,
        "emitted_values": len(codes),
        "distinct_values": len(hist),
    }
    if len(codes) < MIN_VALUES:
        skipped_tiny += 1
        stat["status"] = "skipped_tiny"
        record_stats.append(stat)
        continue
    if len(hist) <= 1:
        skipped_constant += 1
        stat["status"] = "skipped_constant"
        record_stats.append(stat)
        continue
    out = out_dir / f"{rec}_annotation_types_u8_n{len(codes):06d}.bin"
    out.write_bytes(bytes(codes))
    stat.update({
        "status": "kept",
        "sample_path": rel(out),
        "min_value": min(hist),
        "max_value": max(hist),
        "most_common_value": hist.most_common(1)[0][0],
        "most_common_fraction": hist.most_common(1)[0][1] / len(codes),
    })
    record_stats.append(stat)
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(codes),
        "sample_format": "raw homogeneous uint8 annotation-code sequence",
        "sample_geometry": "1d_event_code_sequence",
        "sample_rank": 1,
        "sample_shape": [len(codes)],
        "sample_axes": ["annotation_order"],
        "source_record": rec,
        "source_path": atr.as_posix(),
        "natural_record_kind": "wfdb_annotation_file",
    })

if not index_rows:
    raise SystemExit(f"no qualifying records; skipped_tiny={skipped_tiny} skipped_constant={skipped_constant}")
counts = sorted(int(r["value_count"]) for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "records_seen": len(records),
    "samples": len(index_rows),
    "skipped_tiny": skipped_tiny,
    "skipped_constant": skipped_constant,
    "min_values": counts[0],
    "median_values": counts[len(counts) // 2],
    "max_values": counts[-1],
    "total_values": sum(counts),
    "total_bytes": sum(int(r["sample_size_bytes"]) for r in index_rows),
    "record_stats": record_stats,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(index_rows)} total_values={stats['total_values']} "
    f"median={stats['median_values']} skipped_tiny={skipped_tiny}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
