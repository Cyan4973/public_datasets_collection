#!/usr/bin/env bash
# Fetch only a bounded HDF5 prefix for Dataset 2 layout discovery.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_calochallenge_showers_f64"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
URL="https://zenodo.org/api/records/6366271/files/dataset_2_1.hdf5/content"
EXPECTED_TOTAL_BYTES=1356475617
PREFIX_BYTES=4194304

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/probe.$RUN_TS.log" "$LOG_DIR/probe.latest.log") 2>&1
echo "[$(date -Is)] range probe start candidate=$CANDIDATE_ID"

rm -f "$OUT_DIR/dataset_2_1.prefix.part" "$OUT_DIR/headers.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 300 --max-filesize "$((PREFIX_BYTES + 1))" \
  --speed-limit 1024 --speed-time 180 \
  --user-agent "openzl-public-datasets-calochallenge-range-probe/1.0" \
  --range "0-$((PREFIX_BYTES - 1))" \
  --dump-header "$OUT_DIR/headers.part" \
  --output "$OUT_DIR/dataset_2_1.prefix.part" \
  "$URL"

actual_bytes="$(stat -c %s "$OUT_DIR/dataset_2_1.prefix.part")"
if [ "$actual_bytes" != "$PREFIX_BYTES" ]; then
  echo "range size mismatch expected=$PREFIX_BYTES actual=$actual_bytes" >&2
  exit 1
fi

export HEADERS="$OUT_DIR/headers.part"
export EXPECTED_TOTAL_BYTES PREFIX_BYTES
python3 - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path

headers = Path(os.environ["HEADERS"]).read_text(encoding="iso-8859-1")
responses = re.split(r"(?=^HTTP/)", headers, flags=re.MULTILINE)
content_ranges = []
for response in responses:
    matches = re.findall(
        r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$",
        response,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    content_ranges.extend(matches)
if not content_ranges:
    raise SystemExit("server did not return a Content-Range header")
start, end, total = map(int, content_ranges[-1])
expected_prefix = int(os.environ["PREFIX_BYTES"])
expected_total = int(os.environ["EXPECTED_TOTAL_BYTES"])
if (start, end, total) != (0, expected_prefix - 1, expected_total):
    raise SystemExit(
        f"unexpected Content-Range: bytes {start}-{end}/{total}; "
        f"expected bytes 0-{expected_prefix - 1}/{expected_total}"
    )
print(f"range_response=ok bytes={start}-{end} total={total}")
PY

mv "$OUT_DIR/headers.part" "$OUT_DIR/headers.txt"
mv "$OUT_DIR/dataset_2_1.prefix.part" "$OUT_DIR/dataset_2_1.prefix"

python3 - "$OUT_DIR/dataset_2_1.prefix" "$EXPECTED_TOTAL_BYTES" <<'PY'
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys


path = Path(sys.argv[1])
expected_eof = int(sys.argv[2])
raw = path.read_bytes()


def u16(offset: int) -> int:
    return struct.unpack_from("<H", raw, offset)[0]


def u32(offset: int) -> int:
    return struct.unpack_from("<I", raw, offset)[0]


def u64(offset: int) -> int:
    return struct.unpack_from("<Q", raw, offset)[0]


def need(offset: int, size: int, label: str) -> None:
    if offset < 0 or offset + size > len(raw):
        raise SystemExit(f"{label} lies outside fetched prefix: offset={offset} size={size}")


def messages(offset: int) -> list[tuple[int, bytes]]:
    need(offset, 16, "object header")
    if raw[offset] != 1:
        raise SystemExit(f"unsupported object-header version: {raw[offset]}")
    count = u16(offset + 2)
    chunk_size = u32(offset + 8)
    cursor = offset + 16
    need(cursor, chunk_size, "object-header chunk")
    result = []
    for _ in range(count):
        message_type = u16(cursor)
        message_size = u16(cursor + 2)
        start = cursor + 8
        result.append((message_type, raw[start:start + message_size]))
        cursor = start + message_size
    return result


def one(values: list[tuple[int, bytes]], kind: int) -> bytes:
    found = [payload for message_type, payload in values if message_type == kind]
    if len(found) != 1:
        raise SystemExit(f"expected one HDF5 message type {kind}, found {len(found)}")
    return found[0]


if raw[:8] != b"\x89HDF\r\n\x1a\n" or raw[8] != 0:
    raise SystemExit("prefix is not the expected HDF5 v0 file")
if raw[13:15] != b"\x08\x08" or u64(24) != 0 or u64(40) != expected_eof:
    raise SystemExit("unexpected HDF5 address widths, base address, or EOF")

btree = u64(80)
heap = u64(88)
need(btree, 48, "root B-tree")
need(heap, 32, "root local heap")
if raw[btree:btree + 4] != b"TREE" or raw[btree + 4] != 0:
    raise SystemExit("unexpected root-group B-tree")
if raw[heap:heap + 4] != b"HEAP":
    raise SystemExit("unexpected root-group local heap")
heap_data = u64(heap + 24)

links = {}
cursor = btree + 24
for _ in range(u16(btree + 6)):
    child = u64(cursor + 8)
    need(child, 8, "symbol-table node")
    if raw[child:child + 4] != b"SNOD":
        raise SystemExit("unexpected root symbol-table node")
    for index in range(u16(child + 6)):
        entry = child + 8 + index * 40
        name_start = heap_data + u64(entry)
        name_end = raw.find(b"\0", name_start)
        if name_end < 0:
            raise SystemExit("unterminated root link name")
        links[raw[name_start:name_end].decode("ascii")] = u64(entry + 8)
    cursor += 16

if set(links) != {"incident_energies", "showers"}:
    raise SystemExit(f"unexpected root datasets: {sorted(links)}")

datasets = {}
for name, object_header in sorted(links.items()):
    values = messages(object_header)
    dataspace = one(values, 1)
    datatype = one(values, 3)
    layout = one(values, 8)
    filters = one(values, 11)
    rank = dataspace[1]
    shape = struct.unpack_from("<" + "Q" * rank, dataspace, 8)
    type_size = struct.unpack_from("<I", datatype, 4)[0]
    if datatype[0] & 0x0F != 1 or type_size != 8:
        raise SystemExit(f"{name}: expected an eight-byte floating-point datatype")
    if datatype[1] & 0x01:
        raise SystemExit(f"{name}: datatype is not little-endian")
    if layout[:2] != b"\x03\x02":
        raise SystemExit(f"{name}: expected HDF5 v3 chunked layout")
    chunk_rank = layout[2] - 1
    chunk_shape = struct.unpack_from("<" + "I" * chunk_rank, layout, 11)
    if b"deflate\0" not in filters:
        raise SystemExit(f"{name}: expected DEFLATE filter")
    datasets[name] = {
        "shape": list(shape),
        "value_count": math.prod(shape),
        "datatype": "IEEE-754 float64",
        "bit_width": 64,
        "endianness": "little",
        "layout": "chunked",
        "chunk_shape": list(chunk_shape),
        "chunk_btree_address": struct.unpack_from("<Q", layout, 3)[0],
        "filter": "deflate",
    }

showers = datasets["showers"]
if showers["shape"] != [100_000, 6_480]:
    raise SystemExit(f"unexpected Dataset 2 shower shape: {showers['shape']}")

result = {
    "record_id": 6_366_271,
    "file": "dataset_2_1.hdf5",
    "source_size_bytes": expected_eof,
    "license": "CC BY 4.0",
    "datasets": datasets,
    "natural_event_shape": [45, 9, 16],
    "natural_event_values": 6_480,
    "natural_event_bytes": 51_840,
}
(path.parent / "probe.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(result, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] range probe done candidate=$CANDIDATE_ID"
