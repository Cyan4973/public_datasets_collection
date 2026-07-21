#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_robotics_bridge_tfrecord_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

DATASET_ID = "google_robotics_bridge_tfrecord_u8"
MIN_PAYLOAD_BYTES = 390_000_000
MIN_RECORDS = 16
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
payload_rows = [row for row in rows if row["series_id"] == "bridge_train_00000_tfrecord_payload_u8"]
length_rows = [row for row in rows if row["series_id"] == "bridge_train_00000_tfrecord_record_lengths_u32"]
crc_rows = [row for row in rows if row["series_id"] == "bridge_train_00000_tfrecord_masked_crc_u32"]
if len(length_rows) != 1 or len(crc_rows) != 1:
    raise SystemExit(
        f"expected one length row and one CRC row, got lengths={len(length_rows)} crcs={len(crc_rows)}"
    )
if not payload_rows:
    raise SystemExit("missing payload samples")

payload_rows = sorted(payload_rows, key=lambda row: int(row["source_record_index"]))
length_row = length_rows[0]
crc_row = crc_rows[0]
for row in rows:
    if row["dataset_id"] != DATASET_ID:
        raise SystemExit(f"unexpected dataset id: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    if path.stat().st_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"sample size mismatch: {row['sample_path']}")
for row in payload_rows:
    if row.get("role") != "primary":
        raise SystemExit("payload record samples must be primary")
    if row.get("natural_record_kind") != "bridge_tfrecord_record_payload":
        raise SystemExit(f"payload sample is not a natural TFRecord record: {row['sample_path']}")
for row in (length_row, crc_row):
    if row.get("role") != "auxiliary":
        raise SystemExit(f"container framing stream must be auxiliary: {row['series_id']}")

payload_sizes = [int(row["sample_size_bytes"]) for row in payload_rows]
payload_size = sum(payload_sizes)
if payload_size < MIN_PAYLOAD_BYTES:
    raise SystemExit(f"aggregate payload below floor: {payload_size} < {MIN_PAYLOAD_BYTES}")
payload_probe = bytearray()
for row in payload_rows:
    path = root / row["sample_path"]
    size = path.stat().st_size
    if int(row["value_count"]) != size or int(row["element_size_bytes"]) != 1:
        raise SystemExit(f"payload metadata mismatch: {row['sample_path']}")
    with path.open("rb") as fh:
        payload_probe.extend(fh.read(min(65536, size)))
if len(set(payload_probe)) < 32:
    raise SystemExit("payload byte stream appears degenerate")

record_count = int(length_row["value_count"])
if record_count < MIN_RECORDS:
    raise SystemExit(f"too few record lengths: {record_count}")
if record_count != len(payload_rows):
    raise SystemExit(f"record/sample count mismatch: records={record_count} payload_samples={len(payload_rows)}")
length_path = root / length_row["sample_path"]
length_data = length_path.read_bytes()
if len(length_data) != record_count * 4:
    raise SystemExit("length sample size mismatch")
lengths = list(struct.unpack("<" + "I" * record_count, length_data))
if lengths != payload_sizes:
    raise SystemExit("payload sample sizes do not match TFRecord length stream")
if sum(lengths) != payload_size:
    raise SystemExit(f"record lengths do not sum to payload size: {sum(lengths)} != {payload_size}")
if min(lengths) != int(length_row["min"]) or max(lengths) != int(length_row["max"]):
    raise SystemExit("record length min/max metadata mismatch")

crc_count = int(crc_row["value_count"])
if crc_count != record_count * 2:
    raise SystemExit("CRC value count mismatch")
crc_path = root / crc_row["sample_path"]
if crc_path.stat().st_size != crc_count * 4:
    raise SystemExit("CRC sample size mismatch")

primary_bytes = payload_size
auxiliary_bytes = length_path.stat().st_size + crc_path.stat().st_size
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")
if int(stats["primary_sample_bytes"]) != primary_bytes:
    raise SystemExit("stats/index byte mismatch")
if int(stats.get("primary_sample_count", -1)) != len(payload_rows):
    raise SystemExit("stats/index primary sample count mismatch")
if int(stats.get("auxiliary_sample_bytes", -1)) != auxiliary_bytes:
    raise SystemExit("stats/index auxiliary byte mismatch")
if int(stats["record_count"]) != record_count or int(stats["payload_bytes"]) != payload_size:
    raise SystemExit("stats/index record mismatch")

print(
    f"verified dataset={DATASET_ID} primary_samples={len(payload_rows)} auxiliary_samples=2 records={record_count} "
    f"payload_bytes={payload_size} primary_bytes={primary_bytes} auxiliary_bytes={auxiliary_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
