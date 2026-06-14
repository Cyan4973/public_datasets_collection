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
import zlib
from pathlib import Path

DATASET_ID = "geofabrik_liechtenstein_osm_pbf_u8"
SERIES_ID = "osm_pbf_primitive_blocks"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source_path = download_dir / "liechtenstein-latest.osm.pbf"

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

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

def iter_fields(buf: bytes):
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
            if pos + 4 > len(buf):
                raise RuntimeError("truncated fixed32 field")
            yield field, buf[pos:pos + 4]
            pos += 4
        elif wire == 1:
            if pos + 8 > len(buf):
                raise RuntimeError("truncated fixed64 field")
            yield field, buf[pos:pos + 8]
            pos += 8
        else:
            raise RuntimeError(f"unsupported wire type {wire}")

def grouped_fields(buf: bytes) -> dict[int, list[object]]:
    out: dict[int, list[object]] = {}
    for field, value in iter_fields(buf):
        out.setdefault(field, []).append(value)
    return out

def parse_header(buf: bytes) -> tuple[str, int]:
    fields = grouped_fields(buf)
    if 1 not in fields or 3 not in fields:
        raise RuntimeError("missing BlobHeader type or datasize")
    return fields[1][0].decode("ascii", "strict"), int(fields[3][0])

def decode_blob(buf: bytes) -> tuple[bytes, str]:
    fields = grouped_fields(buf)
    raw_size = int(fields.get(2, [0])[0])
    if 1 in fields:
        raw = fields[1][0]
        compression = "raw"
    elif 3 in fields:
        raw = zlib.decompress(fields[3][0])
        compression = "zlib"
    else:
        raise RuntimeError("Blob has no raw or zlib_data payload")
    if raw_size and len(raw) != raw_size:
        raise RuntimeError(f"Blob raw_size mismatch: expected {raw_size}, got {len(raw)}")
    return raw, compression

def read_exact(fh, size: int) -> bytes:
    data = fh.read(size)
    if len(data) != size:
        raise RuntimeError(f"truncated file: expected {size} bytes, got {len(data)}")
    return data

out_dir = samples_dir / SERIES_ID
reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
blocks = []
block_index = 0
osm_data_index = 0
with source_path.open("rb") as fh:
    while True:
        raw_len = fh.read(4)
        if not raw_len:
            break
        if len(raw_len) != 4:
            raise RuntimeError("truncated PBF block header length")
        header_len = struct.unpack(">I", raw_len)[0]
        if header_len <= 0 or header_len > 64 * 1024:
            raise RuntimeError(f"invalid PBF header size: {header_len}")
        block_type, datasize = parse_header(read_exact(fh, header_len))
        if datasize <= 0 or datasize > 64 * 1024 * 1024:
            raise RuntimeError(f"invalid PBF blob size: {datasize}")
        blob = read_exact(fh, datasize)
        block_index += 1
        if block_type != "OSMData":
            continue
        raw, compression = decode_blob(blob)
        if len(set(raw)) < 2:
            raise RuntimeError(f"OSMData block {osm_data_index}: degenerate payload")
        out = out_dir / f"primitive_block_{osm_data_index:05d}.bin"
        out.write_bytes(raw)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel(out),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(raw),
            "value_count": len(raw),
        }
        rows.append(row)
        blocks.append(
            {
                "block_index": block_index,
                "primitive_block_index": osm_data_index,
                "sample_path": row["sample_path"],
                "compression": compression,
                "values": len(raw),
                "bytes": len(raw),
                "distinct_values": len(set(raw)),
                "min": min(raw),
                "max": max(raw),
            }
        )
        osm_data_index += 1

if len(rows) < 2:
    raise RuntimeError(f"too few OSMData primitive blocks: {len(rows)}")
stats = {
    "dataset_id": DATASET_ID,
    "source": rel(source_path),
    "source_format": "OSM PBF",
    "primitive_blocks": blocks,
    "primitive_block_count": len(blocks),
    "total_values": sum(block["values"] for block in blocks),
    "total_bytes": sum(block["bytes"] for block in blocks),
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for row in rows:
        out.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
