#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eeg_physionet"
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
python3 - <<'PY'
import json
import os
import struct
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

subjects = [f"S{i:03d}" for i in range(1, 11)]
runs = ["01", "02", "04"]
channels = [("C3", "eeg_c3"), ("Cz", "eeg_cz"), ("C4", "eeg_c4")]


def parse_edf(path: Path):
    with path.open("rb") as f:
        f.read(8)
        f.read(80)
        f.read(80)
        f.read(8)
        f.read(8)
        header_bytes = int(f.read(8).strip() or b"0")
        f.read(44)
        n_records = int(f.read(8).strip() or b"0")
        f.read(8)
        n_signals = int(f.read(4).strip() or b"0")

        labels = [f.read(16).decode("ascii", errors="replace").strip() for _ in range(n_signals)]
        for _ in range(n_signals):
            f.read(80)
        for _ in range(n_signals):
            f.read(8)
        for _ in range(n_signals):
            f.read(8)
        for _ in range(n_signals):
            f.read(8)
        for _ in range(n_signals):
            f.read(8)
        for _ in range(n_signals):
            f.read(8)
        for _ in range(n_signals):
            f.read(80)
        samples_per_record = [int(f.read(8).strip() or b"0") for _ in range(n_signals)]
        for _ in range(n_signals):
            f.read(32)

        f.seek(header_bytes)
        signals = {labels[i]: [] for i in range(n_signals)}
        for _ in range(n_records):
            for i in range(n_signals):
                n = samples_per_record[i]
                raw = f.read(n * 2)
                if len(raw) != n * 2:
                    raise SystemExit(f"truncated EDF payload: {path}")
                signals[labels[i]].extend(struct.unpack(f"<{n}h", raw))
    return signals


def find_channel(signals, target: str):
    for label in signals:
        if label.rstrip(".").strip() == target:
            return label
    return None


records = []
subject_summary = []
for target, family in channels:
    (samples_dir / family).mkdir(parents=True, exist_ok=True)

for subject in subjects:
    channel_values = {target: [] for target, _ in channels}
    subject_runs = 0
    for run in runs:
        edf = download_dir / subject / f"{subject}R{run}.edf"
        if not edf.exists():
            raise SystemExit(f"missing input EDF: {edf}")
        signals = parse_edf(edf)
        subject_runs += 1
        for target, _family in channels:
            label = find_channel(signals, target)
            if label is None:
                raise SystemExit(f"missing channel {target} in {edf}")
            channel_values[target].extend(signals[label])

    for target, family in channels:
        payload = struct.pack(f"<{len(channel_values[target])}h", *channel_values[target])
        out = samples_dir / family / f"{subject.lower()}.bin"
        out.write_bytes(payload)
        records.append({
            "dataset_id": "eeg_physionet",
            "series_id": family,
            "sample_path": str(out.relative_to(repo / data_dir)),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(channel_values[target]),
        })
        subject_summary.append((subject, family, subject_runs, len(channel_values[target]), out.stat().st_size))

filter_dir.mkdir(parents=True, exist_ok=True)
with (filter_dir / "inventory.tsv").open("w", encoding="utf-8") as fh:
    fh.write("subject\tseries_id\truns\tsamples\tbytes\n")
    for row in subject_summary:
        fh.write("\t".join(str(x) for x in row) + "\n")

index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in records:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
