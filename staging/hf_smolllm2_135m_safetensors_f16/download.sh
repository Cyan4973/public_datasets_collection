#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="hf_smolllm2_135m_safetensors_f16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
MODEL_URL="${MODEL_URL:-https://huggingface.co/HuggingFaceTB/SmolLM2-135M/resolve/main/model.safetensors}"
CONFIG_URL="${CONFIG_URL:-https://huggingface.co/HuggingFaceTB/SmolLM2-135M/resolve/main/config.json}"
CARD_URL="${CARD_URL:-https://huggingface.co/HuggingFaceTB/SmolLM2-135M/raw/main/README.md}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-1000000000}"

download_if_missing() {
  local target="$1"
  local url="$2"
  if [[ -s "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -o "$target" "$url"
  fi
}

download_if_missing "$DOWNLOAD_DIR/config.json" "$CONFIG_URL"
download_if_missing "$DOWNLOAD_DIR/README.md" "$CARD_URL"
download_if_missing "$DOWNLOAD_DIR/model.safetensors" "$MODEL_URL"

export DOWNLOAD_DIR MAX_FILE_BYTES MODEL_URL CONFIG_URL CARD_URL
python3 - <<'PY'
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
path = download_dir / "model.safetensors"
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
if path.stat().st_size > max_file_bytes:
    raise SystemExit(f"checkpoint exceeds max file bytes: {path.stat().st_size}")
with path.open("rb") as fh:
    header_len = struct.unpack("<Q", fh.read(8))[0]
    if header_len <= 0 or header_len > 64 * 1024 * 1024:
        raise SystemExit(f"invalid safetensors header length: {header_len}")
    header = json.loads(fh.read(header_len))
payload_start = 8 + header_len
records = []
payload_bytes = 0
bad = []
for name, meta in header.items():
    if name == "__metadata__":
        continue
    dtype = str(meta.get("dtype", ""))
    offsets = meta.get("data_offsets")
    shape = meta.get("shape")
    if dtype not in {"F16", "BF16"}:
        bad.append((name, dtype))
        continue
    if not isinstance(offsets, list) or len(offsets) != 2:
        raise SystemExit(f"{name}: invalid data_offsets")
    start, end = int(offsets[0]), int(offsets[1])
    if start < 0 or end <= start or payload_start + end > path.stat().st_size:
        raise SystemExit(f"{name}: invalid tensor byte range")
    size = end - start
    payload_bytes += size
    records.append({"name": name, "dtype": dtype, "shape": shape, "bytes": size, "data_offsets": [start, end]})
if bad:
    raise SystemExit(f"non-16-bit tensors present: {bad[:5]}")
if len(records) < 8:
    raise SystemExit(f"too few tensors: {len(records)}")
if payload_bytes > 1_000_000_000:
    raise SystemExit(f"16-bit tensor payload exceeds cap: {payload_bytes}")
inventory = {
    "dataset_id": "hf_smolllm2_135m_safetensors_f16",
    "model_url": os.environ["MODEL_URL"],
    "config_url": os.environ["CONFIG_URL"],
    "card_url": os.environ["CARD_URL"],
    "source_bytes": path.stat().st_size,
    "header_bytes": header_len,
    "tensor_count": len(records),
    "primary_payload_bytes": payload_bytes,
    "records": records,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok tensors={len(records)} primary_payload_bytes={payload_bytes}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
