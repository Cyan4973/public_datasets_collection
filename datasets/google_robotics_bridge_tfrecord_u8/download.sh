#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_robotics_bridge_tfrecord_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${BRIDGE_BASE_URL:-https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0}"
SHARD_FILE="${BRIDGE_SHARD_FILE:-bridge-train.tfrecord-00000-of-01024}"
MAX_SHARD_BYTES="${BRIDGE_MAX_SHARD_BYTES:-500000000}"
MAX_METADATA_BYTES="${BRIDGE_MAX_METADATA_BYTES:-5000000}"
MAX_TOTAL_BYTES="${BRIDGE_MAX_TOTAL_BYTES:-510000000}"
HARD_MAX_TOTAL_BYTES=1000000000
MIN_SOURCE_BYTES="${BRIDGE_MIN_SOURCE_BYTES:-400000000}"
MIN_RECORDS="${BRIDGE_MIN_RECORDS:-16}"
MIN_PAYLOAD_BYTES="${BRIDGE_MIN_PAYLOAD_BYTES:-390000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

if (( MAX_TOTAL_BYTES > HARD_MAX_TOTAL_BYTES )); then
  echo "requested total source size $MAX_TOTAL_BYTES exceeds hard cap $HARD_MAX_TOTAL_BYTES; clamping"
  MAX_TOTAL_BYTES="$HARD_MAX_TOTAL_BYTES"
fi
if (( MAX_SHARD_BYTES > HARD_MAX_TOTAL_BYTES )); then
  echo "requested shard size $MAX_SHARD_BYTES exceeds hard cap $HARD_MAX_TOTAL_BYTES; clamping"
  MAX_SHARD_BYTES="$HARD_MAX_TOTAL_BYTES"
fi

cat > "$PLAN" <<EOF
resource_id	url	file	max_bytes
bridge_train_shard	$BASE_URL/$SHARD_FILE	$SHARD_FILE	$MAX_SHARD_BYTES
bridge_dataset_info	$BASE_URL/dataset_info.json	dataset_info.json	$MAX_METADATA_BYTES
bridge_features	$BASE_URL/features.json	features.json	$MAX_METADATA_BYTES
EOF

while IFS=$'\t' read -r resource_id url file max_bytes; do
  [[ "$resource_id" != "resource_id" ]] || continue
  target="$DOWNLOAD_DIR/$file"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit resource=$resource_id path=$target"
    continue
  fi
  echo "fetch resource=$resource_id url=$url"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$max_bytes" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$target.tmp" "$url"
  mv "$target.tmp" "$target"
done < "$PLAN"

export DOWNLOAD_DIR SHARD_FILE MAX_SHARD_BYTES MAX_TOTAL_BYTES MIN_SOURCE_BYTES MIN_RECORDS MIN_PAYLOAD_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
shard_file = os.environ["SHARD_FILE"]
max_shard_bytes = int(os.environ["MAX_SHARD_BYTES"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
min_source_bytes = int(os.environ["MIN_SOURCE_BYTES"])
min_records = int(os.environ["MIN_RECORDS"])
min_payload_bytes = int(os.environ["MIN_PAYLOAD_BYTES"])


def load_json(name: str) -> object:
    path = download_dir / name
    if not path.is_file():
        raise SystemExit(f"missing metadata file: {path}")
    if path.stat().st_size <= 0:
        raise SystemExit(f"empty metadata file: {path}")
    if path.stat().st_size > 5_000_000:
        raise SystemExit(f"metadata file too large: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def walk_strings(value: object) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            out.append(str(key))
            out.extend(walk_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(walk_strings(item))
    elif isinstance(value, str):
        out.append(value)
    return out


dataset_info = load_json("dataset_info.json")
features = load_json("features.json")
if not isinstance(dataset_info, dict) or dataset_info.get("name") != "bridge":
    raise SystemExit("dataset_info.json does not describe the TFDS bridge dataset")
if "BridgeData" not in str(dataset_info.get("citation", "")):
    raise SystemExit("dataset_info.json is missing the BridgeData citation")
feature_text = "\n".join(walk_strings(features))
for token in ("reward", "state", "action", "image", "float32", "uint8"):
    if token not in feature_text:
        raise SystemExit(f"features.json missing expected token: {token}")

shard = download_dir / shard_file
if not shard.is_file():
    raise SystemExit(f"missing TFRecord shard: {shard}")
source_bytes = shard.stat().st_size
if source_bytes < min_source_bytes:
    raise SystemExit(f"source shard too small: {source_bytes} < {min_source_bytes}")
if source_bytes > max_shard_bytes:
    raise SystemExit(f"source shard exceeds cap: {source_bytes} > {max_shard_bytes}")
with shard.open("rb") as fh:
    head = fh.read(256)
if head.lstrip().lower().startswith(b"<"):
    raise SystemExit(f"download looks like HTML, not TFRecord data: {shard}")

record_count = 0
payload_bytes = 0
min_length: int | None = None
max_length = 0
with shard.open("rb") as fh:
    while True:
        offset = fh.tell()
        length_bytes = fh.read(8)
        if not length_bytes:
            break
        if len(length_bytes) != 8:
            raise SystemExit(f"truncated TFRecord length at offset {offset}")
        (length,) = struct.unpack("<Q", length_bytes)
        length_crc = fh.read(4)
        if len(length_crc) != 4:
            raise SystemExit(f"truncated TFRecord length CRC at offset {offset}")
        if length == 0 or length > max_shard_bytes:
            raise SystemExit(f"bad TFRecord payload length {length} at offset {offset}")
        fh.seek(length, 1)
        data_crc = fh.read(4)
        if len(data_crc) != 4:
            raise SystemExit(f"truncated TFRecord data CRC at offset {offset}")
        record_count += 1
        payload_bytes += length
        min_length = length if min_length is None else min(min_length, length)
        max_length = max(max_length, length)

if record_count < min_records:
    raise SystemExit(f"too few TFRecord records: {record_count} < {min_records}")
if payload_bytes < min_payload_bytes:
    raise SystemExit(f"payload bytes below floor: {payload_bytes} < {min_payload_bytes}")

total_bytes = sum(path.stat().st_size for path in download_dir.iterdir() if path.is_file())
if total_bytes > max_total_bytes:
    raise SystemExit(f"downloads exceed total cap: {total_bytes} > {max_total_bytes}")

inventory = {
    "dataset_id": "google_robotics_bridge_tfrecord_u8",
    "base_url": os.environ.get("BRIDGE_BASE_URL", "https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0"),
    "shard_file": shard_file,
    "source_bytes": source_bytes,
    "metadata_bytes": total_bytes - source_bytes,
    "downloaded_bytes": total_bytes,
    "record_count": record_count,
    "payload_bytes": payload_bytes,
    "min_record_payload_bytes": min_length,
    "max_record_payload_bytes": max_length,
    "max_total_bytes": max_total_bytes,
    "max_shard_bytes": max_shard_bytes,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok records={record_count} source_bytes={source_bytes} "
    f"payload_bytes={payload_bytes} total_downloaded_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
