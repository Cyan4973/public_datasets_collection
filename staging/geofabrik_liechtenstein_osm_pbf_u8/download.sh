#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geofabrik_liechtenstein_osm_pbf_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
curl -fL --retry 3 --retry-delay 5 -o "$DOWNLOAD_DIR/liechtenstein-latest.osm.pbf" \
  "https://download.geofabrik.de/europe/liechtenstein-latest.osm.pbf"
sha256sum "$DOWNLOAD_DIR/liechtenstein-latest.osm.pbf"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import os
import struct
from pathlib import Path

path = Path(os.environ["DOWNLOAD_DIR"]) / "liechtenstein-latest.osm.pbf"

def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise RuntimeError("truncated varint")
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7
        if shift > 70:
            raise RuntimeError("oversized varint")

def fields(buf: bytes):
    pos = 0
    while pos < len(buf):
        key, pos = read_varint(buf, pos)
        field = key >> 3
        wire = key & 7
        if wire == 0:
            value, pos = read_varint(buf, pos)
            yield field, value
        elif wire == 2:
            size, pos = read_varint(buf, pos)
            end = pos + size
            if end > len(buf):
                raise RuntimeError("truncated length-delimited field")
            yield field, buf[pos:end]
            pos = end
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            raise RuntimeError(f"unsupported wire type {wire}")

def parse_header(buf: bytes) -> tuple[str, int]:
    block_type = None
    datasize = None
    for field, value in fields(buf):
        if field == 1:
            block_type = value.decode("ascii", "strict")
        elif field == 3:
            datasize = int(value)
    if block_type is None or datasize is None:
        raise RuntimeError("missing BlobHeader type or datasize")
    return block_type, datasize

block_types = []
with path.open("rb") as fh:
    while len(block_types) < 4:
        raw_len = fh.read(4)
        if not raw_len:
            break
        if len(raw_len) != 4:
            raise SystemExit("truncated PBF block header length")
        header_len = struct.unpack(">I", raw_len)[0]
        if header_len <= 0 or header_len > 64 * 1024:
            raise SystemExit(f"invalid PBF header size: {header_len}")
        block_type, datasize = parse_header(fh.read(header_len))
        if datasize <= 0 or datasize > 64 * 1024 * 1024:
            raise SystemExit(f"invalid PBF blob size: {datasize}")
        payload = fh.read(datasize)
        if len(payload) != datasize:
            raise SystemExit("truncated PBF blob")
        block_types.append(block_type)
if not block_types or block_types[0] != "OSMHeader" or "OSMData" not in block_types:
    raise SystemExit(f"unexpected initial PBF block types: {block_types}")
print(f"semantic_validation=ok initial_block_types={','.join(block_types)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
