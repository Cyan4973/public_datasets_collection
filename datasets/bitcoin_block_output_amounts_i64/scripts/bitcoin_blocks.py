#!/usr/bin/env python3
"""Validate raw Bitcoin blocks and extract native int64 output amounts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct


DATASET_ID = "bitcoin_block_output_amounts_i64"
SERIES_ID = "bitcoin_transaction_output_amount_i64"
HEIGHTS = tuple(range(840000, 840012))
MAX_MONEY = 21_000_000 * 100_000_000
MIN_SAMPLE_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_VECTOR_COUNT = 10_000_000
FILENAME_RE = re.compile(r"^height_(\d+)_([0-9a-f]{64})\.blk$")


def hash256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


class Reader:
    def __init__(self, data: bytes, context: str):
        self.data = data
        self.context = context
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read(self, size: int) -> bytes:
        if size < 0 or size > self.remaining():
            raise ValueError(
                f"{self.context}: truncated at offset {self.pos}, need {size} bytes"
            )
        result = self.data[self.pos : self.pos + size]
        self.pos += size
        return result

    def peek(self, size: int) -> bytes:
        if size > self.remaining():
            return b""
        return self.data[self.pos : self.pos + size]

    def compact_size(self) -> int:
        prefix = self.read(1)[0]
        if prefix < 0xFD:
            value = prefix
        elif prefix == 0xFD:
            value = struct.unpack("<H", self.read(2))[0]
            if value < 0xFD:
                raise ValueError(f"{self.context}: noncanonical CompactSize")
        elif prefix == 0xFE:
            value = struct.unpack("<I", self.read(4))[0]
            if value < 0x10000:
                raise ValueError(f"{self.context}: noncanonical CompactSize")
        else:
            value = struct.unpack("<Q", self.read(8))[0]
            if value < 0x100000000:
                raise ValueError(f"{self.context}: noncanonical CompactSize")
        if value > MAX_VECTOR_COUNT:
            raise ValueError(f"{self.context}: unreasonable vector count {value}")
        return value


@dataclass(frozen=True)
class ParsedBlock:
    height: int
    block_hash: str
    transaction_count: int
    output_amount_bytes: tuple[bytes, ...]
    minimum: int
    maximum: int
    zero_count: int
    repeated_adjacent: int


def parse_transaction(reader: Reader) -> tuple[bytes, list[bytes]]:
    tx_start = reader.pos
    version = reader.read(4)
    segwit = False
    if len(reader.peek(2)) == 2 and reader.peek(2)[0] == 0:
        marker, flag = reader.read(2)
        if flag == 0:
            raise ValueError(f"{reader.context}: zero SegWit flag")
        if flag != 1:
            raise ValueError(f"{reader.context}: unsupported SegWit flag {flag}")
        segwit = True
    input_section_start = reader.pos
    input_count = reader.compact_size()
    if input_count <= 0:
        raise ValueError(f"{reader.context}: transaction has no inputs")
    for _ in range(input_count):
        reader.read(32 + 4)
        script_size = reader.compact_size()
        reader.read(script_size)
        reader.read(4)
    output_count = reader.compact_size()
    if output_count <= 0:
        raise ValueError(f"{reader.context}: transaction has no outputs")
    amounts = []
    for _ in range(output_count):
        amount_bytes = reader.read(8)
        amount = struct.unpack("<q", amount_bytes)[0]
        if amount < 0 or amount > MAX_MONEY:
            raise ValueError(f"{reader.context}: amount outside MoneyRange {amount}")
        amounts.append(amount_bytes)
        script_size = reader.compact_size()
        reader.read(script_size)
    output_section_end = reader.pos
    if segwit:
        for _ in range(input_count):
            item_count = reader.compact_size()
            for _ in range(item_count):
                item_size = reader.compact_size()
                reader.read(item_size)
    locktime = reader.read(4)
    tx_end = reader.pos
    if segwit:
        base_serialization = (
            version + reader.data[input_section_start:output_section_end] + locktime
        )
    else:
        base_serialization = reader.data[tx_start:tx_end]
    return hash256(base_serialization), amounts


def merkle_root(txids: list[bytes]) -> bytes:
    if not txids:
        raise ValueError("block has no transactions")
    level = list(txids)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hash256(level[index] + level[index + 1]) for index in range(0, len(level), 2)]
    return level[0]


def parse_block(path: Path) -> ParsedBlock:
    match = FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"unexpected block filename: {path.name}")
    height = int(match.group(1))
    expected_hash = match.group(2)
    data = path.read_bytes()
    if len(data) <= 81 or len(data) > 8_000_000:
        raise ValueError(f"{path.name}: implausible raw block size {len(data)}")
    header = data[:80]
    actual_hash = hash256(header)[::-1].hex()
    if actual_hash != expected_hash:
        raise ValueError(
            f"{path.name}: block hash mismatch {actual_hash} != {expected_hash}"
        )
    expected_merkle = header[36:68]
    reader = Reader(data, path.name)
    reader.read(80)
    transaction_count = reader.compact_size()
    if transaction_count <= 0:
        raise ValueError(f"{path.name}: block has no transactions")
    txids = []
    amounts: list[bytes] = []
    for _ in range(transaction_count):
        txid, tx_amounts = parse_transaction(reader)
        txids.append(txid)
        amounts.extend(tx_amounts)
    if reader.remaining() != 0:
        raise ValueError(f"{path.name}: {reader.remaining()} trailing block bytes")
    actual_merkle = merkle_root(txids)
    if actual_merkle != expected_merkle:
        raise ValueError(f"{path.name}: Merkle-root mismatch")
    if len(amounts) < MIN_SAMPLE_VALUES:
        raise ValueError(f"{path.name}: only {len(amounts)} output amounts")
    decoded = [struct.unpack("<q", value)[0] for value in amounts]
    if len(set(decoded)) <= 1:
        raise ValueError(f"{path.name}: constant output-amount stream")
    repeated = sum(left == right for left, right in zip(decoded, decoded[1:]))
    return ParsedBlock(
        height=height,
        block_hash=actual_hash,
        transaction_count=transaction_count,
        output_amount_bytes=tuple(amounts),
        minimum=min(decoded),
        maximum=max(decoded),
        zero_count=sum(value == 0 for value in decoded),
        repeated_adjacent=repeated,
    )


def source_paths(block_dir: Path) -> list[Path]:
    paths = sorted(block_dir.glob("height_*.blk"))
    heights = []
    for path in paths:
        match = FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(f"unexpected block file {path.name}")
        heights.append(int(match.group(1)))
    if tuple(heights) != HEIGHTS:
        raise ValueError(f"expected heights {HEIGHTS}, found {tuple(heights)}")
    return paths


def inspect(paths: list[Path]) -> None:
    if len(paths) != len(HEIGHTS):
        raise ValueError(f"expected {len(HEIGHTS)} blocks, found {len(paths)}")
    total = 0
    for path in paths:
        block = parse_block(path)
        total += len(block.output_amount_bytes)
        print(
            f"height={block.height} hash={block.block_hash} "
            f"transactions={block.transaction_count} outputs={len(block.output_amount_bytes)} "
            f"min={block.minimum} max={block.maximum}"
        )
    print(f"semantic_validation=ok blocks={len(paths)} outputs={total}")


def build(block_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    paths = source_paths(block_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for path in paths:
        block = parse_block(path)
        value_count = len(block.output_amount_bytes)
        payload = b"".join(block.output_amount_bytes)
        output = output_dir / f"height_{block.height}_output_amounts_i64_n{value_count:07d}.bin"
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
                "numeric_kind": "int",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(payload),
                "value_count": value_count,
                "sample_format": "raw homogeneous signed int64 satoshi amount array",
                "sample_geometry": "block_transaction_output_value_stream",
                "sample_rank": 1,
                "sample_shape": [value_count],
                "sample_axes": ["ordered_transaction_output"],
                "natural_record_kind": "bitcoin_mainnet_block_output_amount_stream",
                "source_field": "transaction output nValue",
                "source_sample": path.name,
                "block_height": block.height,
                "block_hash": block.block_hash,
                "transaction_count": block.transaction_count,
                "min": block.minimum,
                "max": block.maximum,
            }
        )
        records.append(
            {
                "source_name": path.name,
                "source_bytes": path.stat().st_size,
                "block_height": block.height,
                "block_hash": block.block_hash,
                "transaction_count": block.transaction_count,
                "output_count": value_count,
                "min": block.minimum,
                "max": block.maximum,
                "zero_fraction": block.zero_count / value_count,
                "repeated_adjacent_fraction": block.repeated_adjacent
                / (value_count - 1),
            }
        )

    counts = [int(row["value_count"]) for row in rows]
    total_values = sum(counts)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES:
        raise ValueError(f"total values below floor: {total_values}")
    if median_values < MIN_SAMPLE_VALUES:
        raise ValueError(f"median sample below floor: {median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "records": records,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built samples={len(rows)} primary_values={total_values} "
        f"primary_bytes={total_bytes} median={median_values:g}"
    )


def verify(block_dir: Path, index_path: Path, data_root: Path) -> None:
    paths = source_paths(block_dir)
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != len(paths):
        raise ValueError(f"expected {len(paths)} samples, found {len(rows)}")
    rows_by_height = {int(row["block_height"]): row for row in rows}
    if set(rows_by_height) != set(HEIGHTS):
        raise ValueError("indexed block-height set mismatch")
    counts = []
    total_bytes = 0
    for path in paths:
        block = parse_block(path)
        row = rows_by_height[block.height]
        if row.get("dataset_id") != DATASET_ID or row.get("role") != "primary":
            raise ValueError("invalid index identity or role")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 64:
            raise ValueError("indexed sample is not signed int64")
        expected = b"".join(block.output_amount_bytes)
        sample = data_root / row["sample_path"]
        if sample.read_bytes() != expected:
            raise ValueError(f"source-to-output mismatch at height {block.height}")
        value_count = len(block.output_amount_bytes)
        if row.get("value_count") != value_count or row.get(
            "sample_size_bytes"
        ) != len(expected):
            raise ValueError(f"indexed size/count mismatch at height {block.height}")
        counts.append(value_count)
        total_bytes += len(expected)
    if sum(counts) < MIN_TOTAL_VALUES or statistics.median(counts) < MIN_SAMPLE_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output cap failed")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} "
        f"median={statistics.median(counts):g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("sources", nargs="+", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--block-dir", required=True, type=Path)
    build_parser.add_argument("--samples-dir", required=True, type=Path)
    build_parser.add_argument("--index", required=True, type=Path)
    build_parser.add_argument("--stats", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--block-dir", required=True, type=Path)
    verify_parser.add_argument("--index", required=True, type=Path)
    verify_parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.sources)
    elif args.command == "build":
        build(args.block_dir, args.samples_dir, args.index, args.stats)
    else:
        verify(args.block_dir, args.index, args.data_root)


if __name__ == "__main__":
    main()
