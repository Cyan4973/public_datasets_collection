#!/usr/bin/env python3
"""Minimal pure-stdlib Blosc1 (c-blosc 1.x, header version 2) frame decoder.

Scope (anything else is rejected, never guessed):
  * 16-byte header: version, versionlz, flags, typesize, nbytes, blocksize, cbytes
  * flags: bit0 byte-shuffle, bit1 memcpyed, bit4 dont-split; bit2 (bitshuffle)
    is rejected; bits 5-7 = compressor code, only 4 (zstd) is accepted
  * memcpyed frames: raw payload follows the header, no block table, no shuffle
  * otherwise: int32 block-start table, then per block a single stream
    [int32 csize][payload] (dont-split is required); csize equal to the raw
    block size means a stored (memcpy) stream, otherwise a zstd frame decoded
    with the zstd CLI
  * byte-unshuffle per block over floor(bsize/typesize) elements, trailing
    bsize % typesize bytes copied verbatim (c-blosc unshuffle_generic), which
    also covers a short final (leftover) block

Run `python3 blosc1.py selftest` to exercise every path on synthetic frames.
"""
from __future__ import annotations

import os
import random
import struct
import subprocess
import sys

ZSTD = os.environ.get("ZSTD_BIN", "zstd")
HEADER = struct.Struct("<BBBBiii")
FLAG_SHUFFLE = 0x01
FLAG_MEMCPYED = 0x02
FLAG_BITSHUFFLE = 0x04
FLAG_DONT_SPLIT = 0x10
ZSTD_CODE = 4


class BloscError(ValueError):
    pass


def parse_header(frame: bytes) -> dict:
    if len(frame) < HEADER.size:
        raise BloscError("frame shorter than 16-byte header")
    version, versionlz, flags, typesize, nbytes, blocksize, cbytes = HEADER.unpack_from(frame, 0)
    return {
        "version": version,
        "versionlz": versionlz,
        "flags": flags,
        "typesize": typesize,
        "nbytes": nbytes,
        "blocksize": blocksize,
        "cbytes": cbytes,
        "compcode": flags >> 5,
    }


def zstd_decompress(payload: bytes, expected: int) -> bytes:
    proc = subprocess.run([ZSTD, "-dcq"], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise BloscError(f"zstd failed rc={proc.returncode}: {proc.stderr.decode(errors='replace').strip()[:200]}")
    if len(proc.stdout) != expected:
        raise BloscError(f"zstd stream decoded to {len(proc.stdout)} bytes, expected {expected}")
    return proc.stdout


def unshuffle(block: bytes, typesize: int) -> bytes:
    """Inverse of c-blosc byte shuffle for one block (planes -> interleaved)."""
    n = len(block) // typesize
    if typesize <= 1 or n == 0:
        return bytes(block)
    out = bytearray(len(block))
    for j in range(typesize):
        out[j : n * typesize : typesize] = block[j * n : (j + 1) * n]
    out[n * typesize :] = block[n * typesize :]
    return bytes(out)


def shuffle(block: bytes, typesize: int) -> bytes:
    """Forward byte shuffle (used only by the self-test encoder)."""
    n = len(block) // typesize
    if typesize <= 1 or n == 0:
        return bytes(block)
    out = bytearray(len(block))
    for j in range(typesize):
        out[j * n : (j + 1) * n] = block[j : n * typesize : typesize]
    out[n * typesize :] = block[n * typesize :]
    return bytes(out)


def decode(frame: bytes) -> tuple[bytes, dict]:
    h = parse_header(frame)
    flags = h["flags"]
    if h["version"] != 2:
        raise BloscError(f"unsupported blosc format version {h['version']}")
    if flags & FLAG_BITSHUFFLE:
        raise BloscError("bitshuffle frames are not supported")
    if flags & ~(FLAG_SHUFFLE | FLAG_MEMCPYED | FLAG_DONT_SPLIT | 0xE0):
        raise BloscError(f"unknown flag bits 0x{flags:02x}")
    if h["cbytes"] != len(frame):
        raise BloscError(f"header cbytes {h['cbytes']} != frame length {len(frame)}")
    nbytes, blocksize, typesize = h["nbytes"], h["blocksize"], h["typesize"]
    if nbytes < 0 or typesize < 1:
        raise BloscError("negative nbytes or zero typesize")
    if flags & FLAG_MEMCPYED:
        if HEADER.size + nbytes != len(frame):
            raise BloscError("memcpyed frame length != 16 + nbytes")
        return bytes(frame[HEADER.size :]), h
    if h["compcode"] != ZSTD_CODE:
        raise BloscError(f"compressor code {h['compcode']} is not zstd")
    if not flags & FLAG_DONT_SPLIT:
        raise BloscError("split-stream blocks are not supported (dont-split flag absent)")
    if nbytes == 0:
        return b"", h
    if blocksize <= 0:
        raise BloscError("non-positive blocksize")
    nblocks = -(-nbytes // blocksize)
    table_end = HEADER.size + 4 * nblocks
    if table_end > len(frame):
        raise BloscError("block-start table overruns frame")
    starts = struct.unpack_from(f"<{nblocks}i", frame, HEADER.size)
    out = bytearray()
    extents = []
    for b, start in enumerate(starts):
        bsize = blocksize if b < nblocks - 1 or nbytes % blocksize == 0 else nbytes % blocksize
        if start < table_end or start + 4 > len(frame):
            raise BloscError(f"block {b} start {start} outside the stream area")
        (csize,) = struct.unpack_from("<i", frame, start)
        if csize <= 0 or start + 4 + csize > len(frame):
            raise BloscError(f"block {b} has invalid stream size {csize}")
        extents.append((start, start + 4 + csize))
        payload = frame[start + 4 : start + 4 + csize]
        raw = bytes(payload) if csize == bsize else zstd_decompress(bytes(payload), bsize)
        if flags & FLAG_SHUFFLE:
            raw = unshuffle(raw, typesize)
        out += raw
    # Multithreaded c-blosc writes blocks in completion order, so the table is
    # not monotonic; the block extents must still tile the stream area exactly.
    cursor = table_end
    for start, end in sorted(extents):
        if start != cursor:
            raise BloscError(f"block extents leave a gap or overlap at {cursor}..{start}")
        cursor = end
    if cursor != len(frame):
        raise BloscError(f"{len(frame) - cursor} trailing bytes after last block")
    if len(out) != nbytes:
        raise BloscError(f"decoded {len(out)} bytes, header nbytes {nbytes}")
    return bytes(out), h


def encode(data: bytes, typesize: int, blocksize: int, shuffle_on: bool = True,
           memcpyed: bool = False, store_blocks: frozenset = frozenset(),
           reverse_order: bool = False) -> bytes:
    """Self-test encoder producing c-blosc 1.x style dont-split zstd frames."""
    flags = (ZSTD_CODE << 5) | FLAG_DONT_SPLIT | (FLAG_SHUFFLE if shuffle_on else 0)
    if memcpyed:
        flags |= FLAG_MEMCPYED
        return HEADER.pack(2, 1, flags, typesize, len(data), blocksize, 16 + len(data)) + data
    nblocks = -(-len(data) // blocksize)
    streams = []
    for b in range(nblocks):
        block = data[b * blocksize : (b + 1) * blocksize]
        if shuffle_on:
            block = shuffle(block, typesize)
        if b in store_blocks:
            streams.append(struct.pack("<i", len(block)) + block)
        else:
            comp = subprocess.run([ZSTD, "-q", "-c", "-3"], input=block, stdout=subprocess.PIPE, check=True).stdout
            if len(comp) == len(block):
                raise RuntimeError("self-test block compressed to its own size; adjust data")
            streams.append(struct.pack("<i", len(comp)) + comp)
    pos = 16 + 4 * nblocks
    starts = [0] * nblocks
    order = list(range(nblocks))[::-1] if reverse_order else list(range(nblocks))
    for b in order:
        starts[b] = pos
        pos += len(streams[b])
    body = struct.pack(f"<{nblocks}i", *starts) + b"".join(streams[b] for b in order)
    return HEADER.pack(2, 1, flags, typesize, len(data), blocksize, 16 + len(body)) + body


def selftest() -> None:
    rng = random.Random(20261009)
    vals = [0.0] * 300 + [rng.expovariate(1e-3) for _ in range(5000)]
    data = struct.pack(f"<{len(vals)}d", *vals)
    cases = [
        ("multi_block_leftover_multiple_of_8", data, 8, 4096, True, False, frozenset(), False),
        ("reverse_block_order", data, 8, 4096, True, False, frozenset(), True),
        ("stored_middle_block_reversed", data, 8, 4096, True, False, frozenset({3}), True),
        ("all_stored_blocks", data, 8, 8192, True, False, frozenset(range(10)), False),
        ("single_block", data[:2000], 8, 4096, True, False, frozenset(), False),
        ("leftover_not_multiple_of_typesize", data[:8 * 1000 + 5], 8, 1024, True, False, frozenset(), True),
        ("no_shuffle", data, 8, 4096, False, False, frozenset(), False),
        ("memcpyed", data[:4000], 8, 4096, True, True, frozenset(), False),
    ]
    for name, payload, ts, bs, sh, mc, stored, rev in cases:
        frame = encode(payload, ts, bs, sh, mc, stored, rev)
        decoded, header = decode(frame)
        if decoded != payload:
            raise SystemExit(f"blosc selftest FAIL {name}")
        if header["nbytes"] != len(payload):
            raise SystemExit(f"blosc selftest FAIL {name}: nbytes")
    good = encode(data, 8, 4096)
    bad_cases = {
        "bitshuffle": good[:2] + bytes([good[2] | FLAG_BITSHUFFLE]) + good[3:],
        "split": good[:2] + bytes([good[2] & ~FLAG_DONT_SPLIT]) + good[3:],
        "lz4": good[:2] + bytes([(good[2] & 0x1F) | (1 << 5)]) + good[3:],
        "truncated": good[:-1],
        "trailing": good + b"\x00",
        "version": bytes([1]) + good[1:],
        "overlapping_blocks": good[:20] + good[16:20] + good[24:],
    }
    for name, frame in bad_cases.items():
        try:
            decode(frame)
        except BloscError:
            continue
        raise SystemExit(f"blosc selftest FAIL: corrupt case {name} accepted")
    print(f"blosc1 selftest ok ({len(cases)} decode cases, {len(bad_cases)} rejection cases)")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
    else:
        raise SystemExit("usage: blosc1.py selftest")
