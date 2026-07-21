#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_robotics_bridge_tfrecord_u8"
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
from __future__ import annotations

import json
import os
import shutil
import struct
from pathlib import Path

DATASET_ID = "google_robotics_bridge_tfrecord_u8"
SHARD_FILE = "bridge-train.tfrecord-00000-of-01024"
MIN_PAYLOAD_BYTES = 390_000_000
MIN_RECORDS = 16
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])


def write_u32_values(path: Path, values: list[int]) -> None:
    with path.open("wb") as fh:
        for start in range(0, len(values), 65536):
            chunk = values[start : start + 65536]
            fh.write(struct.pack("<" + "I" * len(chunk), *chunk))


if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

shard = download_dir / SHARD_FILE
if not shard.is_file():
    raise SystemExit(f"missing downloaded shard: {shard}")

payload_dir = samples_dir / "bridge_tfrecord_payload_u8"
length_dir = samples_dir / "bridge_tfrecord_record_lengths_u32"
crc_dir = samples_dir / "bridge_tfrecord_masked_crc_u32"
payload_dir.mkdir(parents=True, exist_ok=True)
length_dir.mkdir(parents=True, exist_ok=True)
crc_dir.mkdir(parents=True, exist_ok=True)

payload_path = payload_dir / "bridge_train_00000_payload_bytes.bin"
length_path = length_dir / "bridge_train_00000_record_lengths.bin"
crc_path = crc_dir / "bridge_train_00000_masked_crcs.bin"

record_lengths: list[int] = []
masked_crcs: list[int] = []
payload_bytes = 0
source_bytes = shard.stat().st_size

with shard.open("rb") as src, payload_path.open("wb") as payload_out:
    while True:
        offset = src.tell()
        length_bytes = src.read(8)
        if not length_bytes:
            break
        if len(length_bytes) != 8:
            raise SystemExit(f"truncated TFRecord length at offset {offset}")
        (length,) = struct.unpack("<Q", length_bytes)
        length_crc_bytes = src.read(4)
        if len(length_crc_bytes) != 4:
            raise SystemExit(f"truncated TFRecord length CRC at offset {offset}")
        if length == 0 or length > source_bytes:
            raise SystemExit(f"bad TFRecord payload length {length} at offset {offset}")
        data = src.read(length)
        if len(data) != length:
            raise SystemExit(f"truncated TFRecord payload at offset {offset}")
        data_crc_bytes = src.read(4)
        if len(data_crc_bytes) != 4:
            raise SystemExit(f"truncated TFRecord data CRC at offset {offset}")
        payload_out.write(data)
        record_lengths.append(length)
        masked_crcs.append(struct.unpack("<I", length_crc_bytes)[0])
        masked_crcs.append(struct.unpack("<I", data_crc_bytes)[0])
        payload_bytes += length

record_count = len(record_lengths)
if record_count < MIN_RECORDS:
    raise SystemExit(f"too few TFRecord records: {record_count} < {MIN_RECORDS}")
if payload_bytes < MIN_PAYLOAD_BYTES:
    raise SystemExit(f"payload bytes below floor: {payload_bytes} < {MIN_PAYLOAD_BYTES}")

write_u32_values(length_path, record_lengths)
write_u32_values(crc_path, masked_crcs)

length_bytes = length_path.stat().st_size
crc_bytes = crc_path.stat().st_size
primary_bytes = payload_bytes
auxiliary_bytes = length_bytes + crc_bytes
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary output exceeds cap: {primary_bytes} > {MAX_PRIMARY_BYTES}")

rows = [
    {
        "dataset_id": DATASET_ID,
        "series_id": "bridge_train_00000_tfrecord_payload_u8",
        "role": "primary",
        "sample_path": payload_path.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": payload_bytes,
        "value_count": payload_bytes,
        "sample_format": "concatenated TFRecord record payload bytes",
        "sample_geometry": "serialized_robotics_episode_records",
        "sample_rank": 1,
        "sample_shape": [payload_bytes],
        "sample_axes": ["byte"],
        "natural_record_kind": "bridge_tfrecord_shard_payload",
        "source_file": SHARD_FILE,
        "record_count": record_count,
    },
    {
        "dataset_id": DATASET_ID,
        "series_id": "bridge_train_00000_tfrecord_record_lengths_u32",
        "role": "auxiliary",
        "sample_path": length_path.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": length_bytes,
        "value_count": record_count,
        "sample_format": "raw homogeneous uint32 TFRecord payload lengths",
        "sample_geometry": "record_metadata_vector",
        "sample_rank": 1,
        "sample_shape": [record_count],
        "sample_axes": ["record"],
        "natural_record_kind": "bridge_tfrecord_record_lengths",
        "source_file": SHARD_FILE,
        "min": min(record_lengths),
        "max": max(record_lengths),
    },
    {
        "dataset_id": DATASET_ID,
        "series_id": "bridge_train_00000_tfrecord_masked_crc_u32",
        "role": "auxiliary",
        "sample_path": crc_path.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": crc_bytes,
        "value_count": len(masked_crcs),
        "sample_format": "raw homogeneous uint32 TFRecord masked CRC fields",
        "sample_geometry": "record_metadata_matrix",
        "sample_rank": 2,
        "sample_shape": [record_count, 2],
        "sample_axes": ["record", "crc_kind"],
        "natural_record_kind": "bridge_tfrecord_masked_crcs",
        "source_file": SHARD_FILE,
        "crc_columns": ["length_crc", "data_crc"],
        "min": min(masked_crcs),
        "max": max(masked_crcs),
    },
]

stats = {
    "dataset_id": DATASET_ID,
    "source_file": SHARD_FILE,
    "source_bytes": source_bytes,
    "record_count": record_count,
    "payload_bytes": payload_bytes,
    "primary_sample_bytes": primary_bytes,
    "primary_values": payload_bytes,
    "auxiliary_sample_bytes": auxiliary_bytes,
    "auxiliary_values": record_count + len(masked_crcs),
    "total_sample_bytes": primary_bytes + auxiliary_bytes,
    "min_record_payload_bytes": min(record_lengths),
    "max_record_payload_bytes": max(record_lengths),
    "series_count": len(rows),
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(rows)} records={record_count} payload_bytes={payload_bytes} "
    f"primary_bytes={primary_bytes} auxiliary_bytes={auxiliary_bytes}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
