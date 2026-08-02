#!/usr/bin/env python3
"""Validate and characterize the pinned native uint16 VACV MRC volume."""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys


EXPECTED_SIZE = 107_649_024
EXPECTED_MD5 = "a06b214d041398b9d0f0e8702dce8d7a"
EXPECTED_SHAPE = (464, 464, 250)


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_header(header: bytes, file_size: int) -> dict[str, int | str]:
    if len(header) != 1024 or header[208:212] != b"MAP ":
        raise ValueError("invalid MRC header or MAP signature")
    nx, ny, nz, mode = struct.unpack_from("<4i", header, 0)
    nsymbt = struct.unpack_from("<i", header, 92)[0]
    if (nx, ny, nz) != EXPECTED_SHAPE:
        raise ValueError(f"unexpected shape: {(nx, ny, nz)}")
    if mode != 6:
        raise ValueError(f"unexpected MRC mode {mode}; expected uint16 mode 6")
    if nsymbt != 0:
        raise ValueError(f"unexpected extended-header size {nsymbt}")
    value_count = nx * ny * nz
    data_offset = 1024 + nsymbt
    if data_offset + value_count * 2 != file_size:
        raise ValueError("MRC payload size does not exactly match dimensions")
    return {
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "mode": mode,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "extended_header_bytes": nsymbt,
        "data_offset": data_offset,
        "value_count": value_count,
    }


def inspect(path: Path) -> dict[str, object]:
    if path.stat().st_size != EXPECTED_SIZE or md5(path) != EXPECTED_MD5:
        raise ValueError("source size or MD5 mismatch")
    histogram: Counter[int] = Counter()
    slice_nonzero: list[int] = []
    slice_hashes: set[str] = set()
    constant_slices = 0
    transitions = 0
    previous: int | None = None
    with path.open("rb") as handle:
        header = parse_header(handle.read(1024), path.stat().st_size)
        slice_values = int(header["nx"]) * int(header["ny"])
        slice_bytes = slice_values * 2
        for slice_index in range(int(header["nz"])):
            payload = handle.read(slice_bytes)
            if len(payload) != slice_bytes:
                raise ValueError(f"truncated slice {slice_index}")
            words = array("H")
            words.frombytes(payload)
            if words.itemsize != 2:
                raise ValueError("host unsigned-short width is not 16 bits")
            if sys.byteorder == "big":
                words.byteswap()
            histogram.update(words)
            nonzero = sum(value != 0 for value in words)
            slice_nonzero.append(nonzero)
            if len(set(words)) == 1:
                constant_slices += 1
            slice_hashes.add(hashlib.sha256(payload).hexdigest())
            for value in words:
                if previous is not None and value != previous:
                    transitions += 1
                previous = value
        if handle.read(1):
            raise ValueError("unexpected bytes after MRC payload")
    total = sum(histogram.values())
    nonzero_total = total - histogram.get(0, 0)
    entropy = -sum(
        (count / total) * math.log2(count / total) for count in histogram.values()
    )
    ordered_histogram = {str(value): histogram[value] for value in sorted(histogram)}
    return {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_md5": EXPECTED_MD5,
        **header,
        "distinct_values": len(histogram),
        "minimum": min(histogram),
        "maximum": max(histogram),
        "histogram": ordered_histogram,
        "nonzero_values": nonzero_total,
        "nonzero_fraction": nonzero_total / total,
        "shannon_entropy_bits_per_value": entropy,
        "flattened_transitions": transitions,
        "constant_slices": constant_slices,
        "occupied_slices": sum(count > 0 for count in slice_nonzero),
        "unique_slice_payloads": len(slice_hashes),
        "slice_nonzero_minimum": min(slice_nonzero),
        "slice_nonzero_median": statistics.median(slice_nonzero),
        "slice_nonzero_maximum": max(slice_nonzero),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mrc", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.mrc.is_file():
        raise SystemExit(f"missing MRC source: {args.mrc}")
    report = inspect(args.mrc)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if int(report["distinct_values"]) < 2:
        raise SystemExit("segmentation volume is constant")
    if int(report["occupied_slices"]) < 2:
        raise SystemExit("segmentation occupies fewer than two slices")


if __name__ == "__main__":
    main()
