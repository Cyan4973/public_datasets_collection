#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="weatherbench2_era5_pressure_level_fields_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/probes/$CANDIDATE_ID/chunk"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
BUCKET="weatherbench2"
ZARR_PREFIX="datasets/era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr"
BASE_URL="https://storage.googleapis.com/$BUCKET/$ZARR_PREFIX"
TARGET_ARRAY="temperature"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/probe_chunk.$RUN_TS.log" "$LOG_DIR/probe_chunk.latest.log") 2>&1
echo "[$(date -Is)] Zarr chunk probe start candidate=$CANDIDATE_ID"

UA="openzl-public-datasets-weatherbench2-era5-chunk-probe/1.0"
curl --globoff --fail --silent --show-error --location \
  --retry 5 --retry-delay 2 --retry-all-errors --max-time 180 \
  --max-filesize 20000000 --user-agent "$UA" \
  --output "$OUT_DIR/zmetadata.json.part" "$BASE_URL/.zmetadata"
mv "$OUT_DIR/zmetadata.json.part" "$OUT_DIR/zmetadata.json"

export BASE_URL BUCKET OUT_DIR TARGET_ARRAY ZARR_PREFIX
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
from pathlib import Path


out_dir = Path(os.environ["OUT_DIR"])
value = json.loads((out_dir / "zmetadata.json").read_text(encoding="utf-8"))
metadata = value.get("metadata") if isinstance(value, dict) else None
if not isinstance(metadata, dict):
    raise SystemExit("invalid consolidated Zarr metadata")
name = os.environ["TARGET_ARRAY"]
array_meta = metadata.get(f"{name}/.zarray")
attrs = metadata.get(f"{name}/.zattrs")
if not isinstance(array_meta, dict) or not isinstance(attrs, dict):
    raise SystemExit(f"missing Zarr metadata for {name}")
dims = [str(value) for value in attrs.get("_ARRAY_DIMENSIONS", [])]
shape = [int(value) for value in array_meta.get("shape", [])]
chunks = [int(value) for value in array_meta.get("chunks", [])]
if dims != ["time", "level", "longitude", "latitude"]:
    raise SystemExit(f"unexpected dimensions for {name}: {dims}")
if str(array_meta.get("dtype")) != "<f4":
    raise SystemExit(f"unexpected dtype for {name}: {array_meta.get('dtype')}")
compressor = array_meta.get("compressor")
expected_compressor = {"id": "blosc", "cname": "lz4", "clevel": 5, "shuffle": 1, "blocksize": 0}
if compressor != expected_compressor:
    raise SystemExit(f"unexpected compressor for {name}: {compressor}")
if len(shape) != 4 or len(chunks) != 4:
    raise SystemExit(f"unexpected rank for {name}: shape={shape} chunks={chunks}")

separator = str(array_meta.get("dimension_separator") or ".")
chunk_indices = [0, 0, 0, 0]
chunk_key = separator.join(str(value) for value in chunk_indices)
chunk_object = f"{os.environ['ZARR_PREFIX']}/{name}/{chunk_key}"
actual_chunk_shape = [min(chunk, extent) for chunk, extent in zip(chunks, shape)]
expected_decoded_bytes = math.prod(actual_chunk_shape) * 4
summary = {
    "candidate_id": "weatherbench2_era5_pressure_level_fields_f32",
    "zarr_prefix": os.environ["ZARR_PREFIX"],
    "array": name,
    "dtype": array_meta["dtype"],
    "dimensions": dims,
    "shape": shape,
    "chunks": chunks,
    "compressor": compressor,
    "order": array_meta.get("order"),
    "fill_value": array_meta.get("fill_value"),
    "chunk_indices": chunk_indices,
    "chunk_key": chunk_key,
    "chunk_object": chunk_object,
    "actual_chunk_shape": actual_chunk_shape,
    "expected_decoded_bytes": expected_decoded_bytes,
}
(out_dir / "chunk_object.txt").write_text(chunk_object + "\n", encoding="utf-8")
(out_dir / "metadata_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

CHUNK_OBJECT="$(tr -d '\r\n' < "$OUT_DIR/chunk_object.txt")"
curl --globoff --fail --silent --show-error --location \
  --retry 5 --retry-delay 2 --retry-all-errors --max-time 180 \
  --max-filesize 2000000 --user-agent "$UA" \
  --get --data-urlencode "maxResults=10" --data-urlencode "prefix=$CHUNK_OBJECT" \
  --output "$OUT_DIR/chunk_listing.json.part" \
  "https://storage.googleapis.com/storage/v1/b/$BUCKET/o"
mv "$OUT_DIR/chunk_listing.json.part" "$OUT_DIR/chunk_listing.json"

export CHUNK_OBJECT
python3 - <<'PY'
from __future__ import annotations

import base64
import json
import os
from pathlib import Path


out_dir = Path(os.environ["OUT_DIR"])
name = os.environ["CHUNK_OBJECT"]
value = json.loads((out_dir / "chunk_listing.json").read_text(encoding="utf-8"))
matches = [item for item in value.get("items", []) if isinstance(item, dict) and item.get("name") == name]
if len(matches) != 1:
    raise SystemExit(f"expected one exact chunk object, found {len(matches)}")
item = matches[0]
metadata = {
    "name": name,
    "size_bytes": int(str(item.get("size") or "0")),
    "generation": str(item.get("generation") or ""),
    "md5_base64": str(item.get("md5Hash") or ""),
}
if metadata["size_bytes"] <= 16 or not metadata["generation"] or not metadata["md5_base64"]:
    raise SystemExit(f"incomplete chunk metadata: {metadata}")
metadata["md5_hex"] = base64.b64decode(metadata["md5_base64"], validate=True).hex()
(out_dir / "chunk_metadata.json").write_text(
    json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(metadata, indent=2, sort_keys=True))
PY

CHUNK_SIZE="$(jq -r .size_bytes "$OUT_DIR/chunk_metadata.json")"
CHUNK_GENERATION="$(jq -r .generation "$OUT_DIR/chunk_metadata.json")"
CHUNK_URL="https://storage.googleapis.com/$BUCKET/$CHUNK_OBJECT?generation=$CHUNK_GENERATION"
curl --globoff --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
  --speed-limit 1024 --speed-time 120 --max-time 900 \
  --max-filesize "$((CHUNK_SIZE + 1))" --user-agent "$UA" \
  --output "$OUT_DIR/chunk.blosc.part" "$CHUNK_URL"
if [[ "$(stat -c %s "$OUT_DIR/chunk.blosc.part")" != "$CHUNK_SIZE" ]]; then
  echo "FATAL: chunk size mismatch" >&2
  exit 1
fi
mv "$OUT_DIR/chunk.blosc.part" "$OUT_DIR/chunk.blosc"

python3 - <<'PY'
from __future__ import annotations

from array import array
import ctypes
import ctypes.util
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys


out_dir = Path(os.environ["OUT_DIR"])
compressed = (out_dir / "chunk.blosc").read_bytes()
metadata = json.loads((out_dir / "metadata_summary.json").read_text(encoding="utf-8"))
object_metadata = json.loads((out_dir / "chunk_metadata.json").read_text(encoding="utf-8"))
if hashlib.md5(compressed).hexdigest() != object_metadata["md5_hex"]:
    raise SystemExit("compressed chunk MD5 mismatch")
if len(compressed) < 16:
    raise SystemExit("truncated Blosc header")
version, codec_version, flags, typesize, nbytes, blocksize, cbytes = struct.unpack_from("<BBBBIII", compressed, 0)
if cbytes != len(compressed):
    raise SystemExit(f"Blosc compressed-size mismatch: {cbytes} != {len(compressed)}")
if nbytes != int(metadata["expected_decoded_bytes"]):
    raise SystemExit(f"Blosc decoded-size mismatch: {nbytes} != {metadata['expected_decoded_bytes']}")
if typesize != 4:
    raise SystemExit(f"expected Blosc typesize 4, found {typesize}")
if flags & 0x04:
    raise SystemExit("bit-shuffled Blosc chunks are unsupported")


def unshuffle(block: bytes, width: int) -> bytes:
    count = len(block) // width
    main = count * width
    result = bytearray(len(block))
    for byte_index in range(width):
        result[byte_index:main:width] = block[byte_index * count : (byte_index + 1) * count]
    result[main:] = block[main:]
    return bytes(result)


if flags & 0x02:
    decoded = compressed[16 : 16 + nbytes]
    if len(decoded) != nbytes:
        raise SystemExit("truncated memcpy Blosc chunk")
else:
    block_count = math.ceil(nbytes / blocksize)
    table_end = 16 + block_count * 4
    if table_end > len(compressed):
        raise SystemExit("truncated Blosc block-offset table")
    offsets = list(struct.unpack_from("<" + "I" * block_count, compressed, 16))
    library = None
    load_errors = []
    for library_name in (
        ctypes.util.find_library("lz4"),
        "/lib64/liblz4.so.1",
        "/usr/lib64/liblz4.so.1",
        "/usr/lib/x86_64-linux-gnu/liblz4.so.1",
        "liblz4.so.1",
    ):
        if not library_name:
            continue
        try:
            library = ctypes.CDLL(library_name)
            break
        except OSError as exc:
            load_errors.append(f"{library_name}: {exc}")
    if library is None:
        raise SystemExit("unable to load liblz4: " + "; ".join(load_errors))
    library.LZ4_decompress_safe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    library.LZ4_decompress_safe.restype = ctypes.c_int
    blocks: list[bytes] = []
    output_offset = 0
    for index, start in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < len(offsets) else cbytes
        if not (table_end <= start < end <= cbytes):
            raise SystemExit(f"invalid Blosc block bounds index={index} start={start} end={end}")
        expected = min(blocksize, nbytes - output_offset)
        # Blosc splits a full block into one stream per byte in the element
        # type. Each stream has a uint32 compressed-length prefix. The final
        # short block is stored as one stream.
        split_count = typesize if expected == blocksize else 1
        split_decoded_size = expected // split_count
        position = start
        decoded_splits: list[bytes] = []
        for split_index in range(split_count):
            if position + 4 > end:
                raise SystemExit(f"truncated Blosc split header block={index} split={split_index}")
            encoded_size = struct.unpack_from("<I", compressed, position)[0]
            position += 4
            encoded_end = position + encoded_size
            if encoded_end > end:
                raise SystemExit(f"truncated Blosc split block={index} split={split_index}")
            encoded = compressed[position:encoded_end]
            position = encoded_end
            if encoded_size == split_decoded_size:
                decoded_split = encoded
            else:
                source = ctypes.create_string_buffer(encoded)
                destination = ctypes.create_string_buffer(split_decoded_size)
                decoded_size = library.LZ4_decompress_safe(
                    source, destination, encoded_size, split_decoded_size
                )
                if decoded_size != split_decoded_size:
                    raise SystemExit(
                        f"LZ4 split decode failed block={index} split={split_index} "
                        f"result={decoded_size} encoded={encoded_size} "
                        f"expected={split_decoded_size}"
                    )
                decoded_split = destination.raw[:split_decoded_size]
            decoded_splits.append(decoded_split)
        if position != end:
            raise SystemExit(f"Blosc block has trailing bytes index={index}: {end - position}")
        block = b"".join(decoded_splits)
        if flags & 0x01:
            block = unshuffle(block, typesize)
        blocks.append(block)
        output_offset += expected
    decoded = b"".join(blocks)

if len(decoded) != nbytes:
    raise SystemExit(f"decoded length mismatch: {len(decoded)} != {nbytes}")
(out_dir / "decoded_chunk.f32le").write_bytes(decoded)

values = array("f")
values.frombytes(decoded)
if sys.byteorder != "little":
    values.byteswap()
finite = [value for value in values if math.isfinite(value)]
if len(finite) != len(values):
    raise SystemExit(f"non-finite values found: {len(values) - len(finite)}")
time_count = int(metadata["actual_chunk_shape"][0])
values_per_time = math.prod(int(value) for value in metadata["actual_chunk_shape"][1:])
summary = {
    **metadata,
    "compressed_size_bytes": len(compressed),
    "compressed_md5": object_metadata["md5_hex"],
    "blosc_header": {
        "version": version,
        "codec_version": codec_version,
        "flags": flags,
        "typesize": typesize,
        "decoded_bytes": nbytes,
        "blocksize": blocksize,
        "compressed_bytes": cbytes,
    },
    "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
    "decoded_value_count": len(values),
    "time_slices_in_chunk": time_count,
    "values_per_time_slice": values_per_time,
    "bytes_per_time_slice": values_per_time * 4,
    "minimum": min(finite),
    "maximum": max(finite),
    "nonfinite_values": 0,
}
(out_dir / "probe_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] Zarr chunk probe done candidate=$CANDIDATE_ID"
