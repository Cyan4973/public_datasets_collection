#!/usr/bin/env python3
"""Synthetic self-test of the Blosc1/zstd decoder and the type-1 chunk B-tree walker.

Builds Blosc1 buffers by hand (zstd CLI for compression) covering the cases
the TUM-VIE files may contain: byte-shuffle + DONT_SPLIT + zstd blocks, a
block stored uncompressed (csize == block size), per-byte split streams, and
a memcpyed buffer.  Also builds a two-level v1 B-tree (type 1) in a sparse
segment map and checks that chunk_refs() returns exactly the requested leaf
entries and requests missing nodes via NeedBytes.  Exits non-zero on failure.
"""
from __future__ import annotations

import random
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tumvie_h5 as T  # noqa: E402


def zstd_compress(data: bytes) -> bytes:
    p = subprocess.run(["zstd", "-q", "-1", "-c", "--no-progress"], input=data, stdout=subprocess.PIPE, check=True)
    return p.stdout


def shuffle(block: bytes, ts: int) -> bytes:
    n = len(block) // ts
    return b"".join(block[i : n * ts : ts] for i in range(ts)) + block[n * ts :]


def make_blosc(values: list[int], blocksize: int, *, dont_split: bool = True, raw_block: int | None = None,
               memcpyed: bool = False) -> bytes:
    data = struct.pack(f"<{len(values)}H", *values)
    nbytes = len(data)
    if memcpyed:
        flags = 0x02 | 0x10 | (4 << 5)
        return struct.pack("<BBBBIII", 2, 1, flags, 2, nbytes, blocksize, 16 + nbytes) + data
    flags = 0x01 | (0x10 if dont_split else 0) | (4 << 5)
    nblocks = -(-nbytes // blocksize)
    hdr_len = 16 + 4 * nblocks
    payload = bytearray()
    starts = []
    for b in range(nblocks):
        blk = shuffle(data[b * blocksize : (b + 1) * blocksize], 2)
        starts.append(hdr_len + len(payload))
        splits = [blk] if dont_split else [blk[: len(blk) // 2], blk[len(blk) // 2 :]]
        for s in splits:
            comp = s if b == raw_block else zstd_compress(s)
            payload += struct.pack("<i", len(comp)) + comp
    total = hdr_len + len(payload)
    return struct.pack("<BBBBIII", 2, 1, flags, 2, nbytes, blocksize, total) + struct.pack(f"<{nblocks}i", *starts) + payload


def test_blosc() -> None:
    rng = random.Random(7)
    vals = [rng.randrange(0, 1280) for _ in range(T.CHUNK_ELEMS)]
    ref = struct.pack(f"<{len(vals)}H", *vals)
    cases = {
        "shuffle+dont_split+zstd": make_blosc(vals, 32768),
        "uncompressed second block": make_blosc(vals, 32768, raw_block=1),
        "split streams": make_blosc(vals, 32768, dont_split=False),
        "split streams, raw block": make_blosc(vals, 16384, dont_split=False, raw_block=2),
        "memcpyed": make_blosc(vals, 32768, memcpyed=True),
    }
    for name, buf in cases.items():
        out = T.blosc_decode(buf)
        assert out == ref, f"Blosc case {name!r} decoded wrongly"
    lo, hi, n = T.u16_stats(T.blosc_decode(cases["shuffle+dont_split+zstd"]))
    assert (lo, hi, n) == (min(vals), max(vals), T.CHUNK_ELEMS)
    bad = bytearray(cases["shuffle+dont_split+zstd"])
    bad[4:8] = struct.pack("<I", 1000)
    try:
        T.blosc_decode(bytes(bad))
    except T.LayoutError:
        pass
    else:
        raise AssertionError("nbytes mismatch was not rejected")
    print(f"selftest blosc ok cases={len(cases)}")


def build_btree(n_chunks: int, per_leaf: int, base: int) -> tuple[T.Segments, int, dict[int, tuple[int, int]]]:
    """Two-level type-1 B-tree over n_chunks chunks of a 1-D uint16 dataset."""
    ndims = 2
    key_size = 8 + 8 * ndims
    node_len = T.node_bytes(ndims)
    file_size = base + 64 * node_len + n_chunks * 100 + 1_000_000
    seg = T.Segments(file_size)
    chunks = {i: (base + 64 * node_len + i * 100, 50 + i % 7) for i in range(n_chunks)}

    def key(csize: int, off: int) -> bytes:
        return struct.pack("<IIQQ", csize, 0, off, 0)

    def node(level: int, entries: list[tuple[int, int, int]], last_off: int) -> bytes:
        raw = bytearray(b"TREE" + struct.pack("<BBH", 1, level, len(entries)) + struct.pack("<QQ", T.UNDEFINED, T.UNDEFINED))
        for csize, off, child in entries:
            raw += key(csize, off) + struct.pack("<Q", child)
        raw += key(0, last_off)
        raw += b"\x00" * (node_len - len(raw))
        assert len(raw) == node_len and key_size == 24
        return bytes(raw)

    leaves = []
    for li, start in enumerate(range(0, n_chunks, per_leaf)):
        idx = list(range(start, min(n_chunks, start + per_leaf)))
        addr = base + (1 + li) * node_len
        ents = [(chunks[i][1], i * T.CHUNK_ELEMS, chunks[i][0]) for i in idx]
        seg.add(addr, node(0, ents, (idx[-1] + 1) * T.CHUNK_ELEMS))
        leaves.append((idx[0], addr))
    root_ents = [(0, first * T.CHUNK_ELEMS, addr) for first, addr in leaves]
    seg.add(base, node(1, root_ents, n_chunks * T.CHUNK_ELEMS))
    return seg, base, chunks


def test_btree() -> None:
    seg, root, chunks = build_btree(300, 57, 10_000)
    ds = T.Dataset("x", 0, (300 * T.CHUNK_ELEMS,), 0, 2, False, "little", 16, 0, 2, root, (T.CHUNK_ELEMS, 2),
                   [(T.BLOSC_FILTER_ID, (2, 2, 2, 65536, 1, 1, 5))])
    for first, count in [(0, 10), (50, 20), (100, 128), (172, 128)]:
        refs = T.chunk_refs(seg, ds, first, count)
        assert [r.index for r in refs] == list(range(first, first + count))
        for r in refs:
            assert (r.address, r.size) == chunks[r.index]
    # a missing leaf must surface as NeedBytes, not as wrong data
    sparse = T.Segments(seg.file_size)
    sparse.parts = [p for p in seg.parts if p[0] == root]
    try:
        T.chunk_refs(sparse, ds, 100, 128)
    except T.NeedBytes as need:
        assert need.length == T.node_bytes(2)
    else:
        raise AssertionError("missing leaf did not raise NeedBytes")
    print("selftest btree ok")


def main() -> int:
    test_blosc()
    test_btree()
    return 0


if __name__ == "__main__":
    sys.exit(main())
