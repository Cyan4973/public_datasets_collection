#!/usr/bin/env python3
"""Decode the Blosc/LZ4 byte-shuffled chunks used by the selected ERA5 Zarr."""

from __future__ import annotations

import ctypes
import ctypes.util
import math
from pathlib import Path
import struct
from typing import Any


def _load_lz4() -> Any:
    errors = []
    for name in (
        ctypes.util.find_library("lz4"),
        "/lib64/liblz4.so.1",
        "/usr/lib64/liblz4.so.1",
        "/usr/lib/x86_64-linux-gnu/liblz4.so.1",
        "liblz4.so.1",
    ):
        if not name:
            continue
        try:
            library = ctypes.CDLL(name)
            library.LZ4_decompress_safe.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
            ]
            library.LZ4_decompress_safe.restype = ctypes.c_int
            return library
        except OSError as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("unable to load liblz4: " + "; ".join(errors))


def _unshuffle(block: bytes, typesize: int) -> bytes:
    count = len(block) // typesize
    main = count * typesize
    result = bytearray(len(block))
    for byte_index in range(typesize):
        result[byte_index:main:typesize] = block[
            byte_index * count : (byte_index + 1) * count
        ]
    result[main:] = block[main:]
    return bytes(result)


def decompress(data: bytes) -> tuple[bytes, dict[str, int]]:
    if len(data) < 16:
        raise ValueError("truncated Blosc header")
    version, codec_version, flags, typesize, nbytes, blocksize, cbytes = struct.unpack_from(
        "<BBBBIII", data, 0
    )
    if cbytes != len(data):
        raise ValueError(f"Blosc compressed-size mismatch: {cbytes} != {len(data)}")
    if typesize <= 0 or blocksize <= 0 or nbytes <= 0:
        raise ValueError("invalid Blosc sizes")
    if flags & 0x04:
        raise ValueError("bit-shuffled Blosc chunks are unsupported")
    if flags >> 5 != 1:
        raise ValueError(f"expected Blosc LZ4 codec-format flag 1, found {flags >> 5}")

    if flags & 0x02:
        decoded = data[16 : 16 + nbytes]
        if len(decoded) != nbytes:
            raise ValueError("truncated memcpy Blosc chunk")
    else:
        block_count = math.ceil(nbytes / blocksize)
        table_end = 16 + block_count * 4
        if table_end > len(data):
            raise ValueError("truncated Blosc block-offset table")
        offsets = list(struct.unpack_from("<" + "I" * block_count, data, 16))
        library = _load_lz4()
        blocks: list[bytes] = []
        output_offset = 0
        for index, start in enumerate(offsets):
            end = offsets[index + 1] if index + 1 < len(offsets) else cbytes
            if not (table_end <= start < end <= cbytes):
                raise ValueError(
                    f"invalid Blosc block bounds index={index} start={start} end={end}"
                )
            expected = min(blocksize, nbytes - output_offset)
            split_count = typesize if expected == blocksize else 1
            if expected % split_count:
                raise ValueError(f"Blosc block does not divide into byte lanes: {expected}")
            split_decoded_size = expected // split_count
            position = start
            decoded_splits: list[bytes] = []
            for split_index in range(split_count):
                if position + 4 > end:
                    raise ValueError(
                        f"truncated Blosc split header block={index} split={split_index}"
                    )
                encoded_size = struct.unpack_from("<I", data, position)[0]
                position += 4
                encoded_end = position + encoded_size
                if encoded_end > end:
                    raise ValueError(f"truncated Blosc split block={index} split={split_index}")
                encoded = data[position:encoded_end]
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
                        raise ValueError(
                            f"LZ4 split decode failed block={index} split={split_index} "
                            f"result={decoded_size} encoded={encoded_size} "
                            f"expected={split_decoded_size}"
                        )
                    decoded_split = destination.raw[:split_decoded_size]
                decoded_splits.append(decoded_split)
            if position != end:
                raise ValueError(f"Blosc block has trailing bytes index={index}: {end - position}")
            block = b"".join(decoded_splits)
            if flags & 0x01:
                block = _unshuffle(block, typesize)
            blocks.append(block)
            output_offset += expected
        decoded = b"".join(blocks)

    if len(decoded) != nbytes:
        raise ValueError(f"decoded length mismatch: {len(decoded)} != {nbytes}")
    return decoded, {
        "version": version,
        "codec_version": codec_version,
        "flags": flags,
        "typesize": typesize,
        "decoded_bytes": nbytes,
        "blocksize": blocksize,
        "compressed_bytes": cbytes,
    }


def decompress_file(path: Path) -> tuple[bytes, dict[str, int]]:
    return decompress(path.read_bytes())
