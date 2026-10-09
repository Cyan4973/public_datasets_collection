#!/usr/bin/env python3
"""Sparse read-only view of a remote file assembled from aligned range blocks.

Block ``i`` covers bytes ``[i * block_size, min(size, (i + 1) * block_size))``
and is stored at ``<directory>/blk_<i:06d>.bin``.  ``download.sh`` fetches the
blocks with curl; this module never touches the network.  Reading a block that
is not present raises ``MissingBlock`` so the planner can request it.
"""
from __future__ import annotations

from pathlib import Path

BLOCK_SIZE = 1 << 16


class MissingBlock(Exception):
    def __init__(self, index: int) -> None:
        super().__init__(f"missing block {index}")
        self.index = index


class BlockStore:
    def __init__(self, directory: Path, size: int, block_size: int = BLOCK_SIZE) -> None:
        self.directory = Path(directory)
        self.size = int(size)
        self.block_size = int(block_size)
        self.cache: dict[int, bytes] = {}
        self.used: set[int] = set()

    def __len__(self) -> int:
        return self.size

    def block_count(self) -> int:
        return -(-self.size // self.block_size)

    def block_span(self, index: int) -> tuple[int, int]:
        start = index * self.block_size
        if index < 0 or start >= self.size:
            raise ValueError(f"block {index} outside file of {self.size} bytes")
        return start, min(self.size, start + self.block_size)

    def block_path(self, index: int) -> Path:
        return self.directory / f"blk_{index:06d}.bin"

    def present(self, index: int) -> bool:
        path = self.block_path(index)
        if not path.is_file():
            return False
        start, end = self.block_span(index)
        return path.stat().st_size == end - start

    def block(self, index: int) -> bytes:
        data = self.cache.get(index)
        if data is None:
            path = self.block_path(index)
            if not self.present(index):
                raise MissingBlock(index)
            data = path.read_bytes()
            start, end = self.block_span(index)
            if len(data) != end - start:
                raise ValueError(f"block {path} has {len(data)} bytes, expected {end - start}")
            if len(self.cache) > 64:
                self.cache.clear()
            self.cache[index] = data
        self.used.add(index)
        return data

    def blocks_for(self, offset: int, length: int) -> range:
        if length <= 0:
            return range(0)
        return range(offset // self.block_size, (offset + length - 1) // self.block_size + 1)

    def __getitem__(self, item: slice) -> bytes:
        if not isinstance(item, slice) or item.step not in (None, 1):
            raise TypeError("BlockStore supports contiguous slices only")
        start = 0 if item.start is None else int(item.start)
        stop = self.size if item.stop is None else min(int(item.stop), self.size)
        out = bytearray()
        pos = start
        while pos < stop:
            index = pos // self.block_size
            data = self.block(index)
            off = pos - index * self.block_size
            take = min(stop - pos, len(data) - off)
            out += data[off:off + take]
            pos += take
        return bytes(out)
