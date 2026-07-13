#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ena_fastq_quality_phred"
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
MAX_READS="${FASTQ_MAX_READS:-500000}"
MIN_RECORDS="${FASTQ_MIN_CYCLE_RECORDS:-1000}"
PHRED_OFFSET="${FASTQ_PHRED_OFFSET:-33}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MAX_READS MIN_RECORDS PHRED_OFFSET
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_reads = int(os.environ["MAX_READS"])
min_records = int(os.environ["MIN_RECORDS"])
offset = int(os.environ["PHRED_OFFSET"])

DATASET_ID = "ena_fastq_quality_phred"
FAMILY = "fastq_phred_quality_u8"

src = download_dir / "reads.fastq.gz"
if not src.is_file():
    raise SystemExit(f"missing {src}")

# per-cycle (read position) Phred quality values
by_cycle: dict[int, bytearray] = defaultdict(bytearray)
reads = 0
bad = 0

with gzip.open(src, "rt", encoding="ascii", errors="replace") as fh:
    while reads < max_reads:
        header = fh.readline()
        if not header:
            break
        _seq = fh.readline()
        plus = fh.readline()
        qual = fh.readline().rstrip("\n")
        if not header.startswith("@") or not plus.startswith("+") or not qual:
            bad += 1
            continue
        reads += 1
        for i, ch in enumerate(qual):
            q = ord(ch) - offset
            if 0 <= q <= 93:
                by_cycle[i].append(q)
            else:
                bad += 1

if samples_dir.exists():
    shutil.rmtree(samples_dir)
fam_dir = samples_dir / FAMILY
fam_dir.mkdir(parents=True, exist_ok=True)

qualifying = sorted(c for c, vals in by_cycle.items()
                    if len(vals) >= min_records and len(set(vals)) > 1)
if len(qualifying) < 5:
    raise SystemExit(f"only {len(qualifying)} cycles >= {min_records} records (reads={reads})")

index_rows = []
for c in qualifying:
    vals = by_cycle[c]
    out = fam_dir / f"{FAMILY}_cycle{c:03d}_n{len(vals):07d}.bin"
    out.write_bytes(bytes(vals))  # uint8
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": FAMILY,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(vals),
        "sample_geometry": "sequence",
        "sample_rank": 1,
        "cycle": c,
        "natural_record_kind": "fastq_read_cycle",
    })

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": {FAMILY: len(index_rows)},
    "samples": len(index_rows),
    "reads_used": reads,
    "bad_entries": bad,
    "phred_offset": offset,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built family={FAMILY} cycles={len(index_rows)} reads={reads} bad={bad} "
    f"primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
