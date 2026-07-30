#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_dorothea_binary_molecular_features_u8"
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

export REPO_ROOT DATA_DIR DOWNLOAD_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

DATASET_ID = "uci_dorothea_binary_molecular_features_u8"
SERIES_ID = "dorothea_molecular_feature_vector_u8"
FEATURE_COUNT = 100_000
EXPECTED_ROWS = {"train": 800, "valid": 350, "test": 800}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
out_dir = samples_dir / SERIES_ID
inventory_path = download_dir / "inventory.tsv"


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def parse_indices(line: str, split: str, row_number: int) -> list[int]:
    try:
        indices = [int(token) for token in line.split()]
    except ValueError as exc:
        raise SystemExit(f"malformed index split={split} row={row_number}: {exc}")
    if not indices:
        raise SystemExit(f"empty sparse row split={split} row={row_number}")
    if indices[0] < 1 or indices[-1] > FEATURE_COUNT:
        raise SystemExit(f"index out of range split={split} row={row_number}")
    if any(left >= right for left, right in zip(indices, indices[1:])):
        raise SystemExit(f"indices not strictly increasing split={split} row={row_number}")
    return indices


if not inventory_path.is_file():
    raise SystemExit(f"missing validated inventory; run download.sh first: {inventory_path}")
with inventory_path.open("r", encoding="utf-8", newline="") as fh:
    inventory = list(csv.DictReader(fh, delimiter="\t"))
if [row["split"] for row in inventory] != ["train", "valid", "test"]:
    raise SystemExit("inventory split order/content mismatch")

reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
index_rows: list[dict[str, object]] = []
split_stats: list[dict[str, object]] = []
aggregate_active = 0

for inventory_row in inventory:
    split = inventory_row["split"]
    source = extract_dir / inventory_row["extracted_filename"]
    if not source.is_file():
        raise SystemExit(f"missing extracted sparse matrix: {source}")
    rows = 0
    split_active = 0
    active_counts: list[int] = []
    with source.open("r", encoding="ascii") as fh:
        for row_number, line in enumerate(fh, 1):
            if not line.strip():
                raise SystemExit(f"empty sparse row split={split} row={row_number}")
            indices = parse_indices(line, split, row_number)
            vector = bytearray(FEATURE_COUNT)
            for index in indices:
                vector[index - 1] = 1
            active = len(indices)
            inactive = FEATURE_COUNT - active
            if active <= 0 or inactive <= 0:
                raise SystemExit(f"constant decoded vector split={split} row={row_number}")
            output = out_dir / f"{split}_{row_number:04d}_features_u8_n{FEATURE_COUNT}.bin"
            output.write_bytes(vector)
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": rel(output),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": FEATURE_COUNT,
                "value_count": FEATURE_COUNT,
                "sample_format": "raw homogeneous uint8 binary feature vector",
                "sample_geometry": "100000_dimensional_compound_feature_vector",
                "sample_rank": 1,
                "sample_shape": [FEATURE_COUNT],
                "sample_axes": ["feature_index"],
                "natural_record_kind": "dorothea_compound_feature_vector",
                "source_format": "whitespace_delimited_sparse_binary_index_rows",
                "source_field": "documented_100000_binary_molecular_input_features",
                "source_path": rel(source),
                "source_split": split,
                "source_row_number": row_number,
                "zero_count": inactive,
                "one_count": active,
                "one_fraction": active / FEATURE_COUNT,
            })
            rows += 1
            split_active += active
            active_counts.append(active)
    if rows != EXPECTED_ROWS[split] or rows != int(inventory_row["rows"]):
        raise SystemExit(
            f"row mismatch split={split} built={rows} expected={EXPECTED_ROWS[split]} inventory={inventory_row['rows']}"
        )
    if split_active != int(inventory_row["total_active_features"]):
        raise SystemExit(f"active-feature total mismatch split={split}")
    aggregate_active += split_active
    active_counts.sort()
    split_stats.append({
        "split": split,
        "samples": rows,
        "active_features": split_active,
        "min_active_features": active_counts[0],
        "median_active_features": active_counts[len(active_counts) // 2],
        "max_active_features": active_counts[-1],
        "one_fraction": split_active / (rows * FEATURE_COUNT),
    })
    print(
        f"built split={split} samples={rows} active_total={split_active} "
        f"active_min={active_counts[0]} active_median={active_counts[len(active_counts)//2]} "
        f"active_max={active_counts[-1]}"
    )

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

total_values = len(index_rows) * FEATURE_COUNT
all_active_counts = sorted(int(row["one_count"]) for row in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "feature_count": FEATURE_COUNT,
    "primary_values": total_values,
    "primary_sample_bytes": total_values,
    "active_features": aggregate_active,
    "inactive_features": total_values - aggregate_active,
    "one_fraction": aggregate_active / total_values,
    "min_active_features": all_active_counts[0],
    "median_active_features": (all_active_counts[974] + all_active_counts[975]) / 2,
    "max_active_features": all_active_counts[-1],
    "splits": split_stats,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"built dataset={DATASET_ID} samples={len(index_rows)} values={total_values} "
    f"one_fraction={stats['one_fraction']:.8f}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
