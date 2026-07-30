#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_mhealth_activity_state_u8"
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
from collections import Counter
from pathlib import Path

DATASET_ID = "uci_mhealth_activity_state_u8"
SERIES_ID = "mhealth_activity_id_u8"
ALLOWED = set(range(13))

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


if not inventory_path.is_file():
    raise SystemExit(f"missing validated inventory; run download.sh first: {inventory_path}")
with inventory_path.open("r", encoding="utf-8", newline="") as fh:
    inventory = list(csv.DictReader(fh, delimiter="\t"))
if [int(row["subject"]) for row in inventory] != list(range(1, 11)):
    raise SystemExit("inventory does not contain subjects 1..10 in order")

reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
index_rows: list[dict[str, object]] = []
subject_stats: list[dict[str, object]] = []
aggregate = Counter()

for inventory_row in inventory:
    subject = int(inventory_row["subject"])
    source = extract_dir / f"subject{subject:02d}.log"
    if not source.is_file():
        raise SystemExit(f"missing extracted subject recording: {source}")
    labels = bytearray()
    transitions = 0
    longest_run = 0
    current_run = 0
    previous: int | None = None
    with source.open("r", encoding="ascii") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != 24:
                raise SystemExit(
                    f"wrong field count subject={subject} line={line_number} fields={len(fields)}"
                )
            try:
                label_float = float(fields[-1])
            except ValueError as exc:
                raise SystemExit(f"invalid label subject={subject} line={line_number}: {exc}")
            label = int(label_float)
            if label_float != label or label not in ALLOWED:
                raise SystemExit(
                    f"out-of-range/non-integral label subject={subject} line={line_number} value={fields[-1]}"
                )
            labels.append(label)
            if label == previous:
                current_run += 1
            else:
                if previous is not None:
                    transitions += 1
                longest_run = max(longest_run, current_run)
                current_run = 1
                previous = label
    longest_run = max(longest_run, current_run)
    if len(labels) != int(inventory_row["rows"]):
        raise SystemExit(
            f"inventory row mismatch subject={subject} built={len(labels)} inventory={inventory_row['rows']}"
        )
    hist = Counter(labels)
    if len(labels) < 1_000 or len(hist) <= 1:
        raise SystemExit(f"tiny or constant recording subject={subject}")
    output = out_dir / f"subject{subject:02d}_activity_id_u8_n{len(labels)}.bin"
    output.write_bytes(labels)
    aggregate.update(hist)
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(output),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(labels),
        "value_count": len(labels),
        "sample_format": "raw homogeneous uint8 activity-state sequence",
        "sample_geometry": "1d_subject_recording_timeline",
        "sample_rank": 1,
        "sample_shape": [len(labels)],
        "sample_axes": ["observation_order"],
        "natural_record_kind": "complete_mhealth_subject_recording",
        "source_format": "whitespace_delimited_mhealth_subject_log",
        "source_field": "column_24_activity_label",
        "source_path": rel(source),
        "source_subject_number": subject,
        "activity_histogram": {str(key): hist[key] for key in sorted(hist)},
    })
    subject_stats.append({
        "subject": subject,
        "values": len(labels),
        "transitions": transitions,
        "longest_run": longest_run,
        "activity_histogram": {str(key): hist[key] for key in sorted(hist)},
    })
    print(
        f"built subject={subject} values={len(labels)} transitions={transitions} "
        f"longest_run={longest_run} labels={sorted(hist)}"
    )

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

counts = sorted(int(row["value_count"]) for row in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(index_rows),
    "primary_values": sum(counts),
    "primary_sample_bytes": sum(counts),
    "min_sample_values": counts[0],
    "median_sample_values": (counts[4] + counts[5]) / 2,
    "max_sample_values": counts[-1],
    "activity_histogram": {str(key): aggregate[key] for key in sorted(aggregate)},
    "subjects": subject_stats,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"built dataset={DATASET_ID} samples={len(index_rows)} "
    f"values={sum(counts)} median={stats['median_sample_values']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
