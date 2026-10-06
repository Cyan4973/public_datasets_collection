#!/usr/bin/env python3
"""Independently re-derive and check every emitted Kikuchi pattern.

This verifier does not import the build script. It re-parses the NORDIF
Setting.txt files, re-derives the expected (map, scan row, scan column) list,
checks the pinned row checksums, byte-compares every sample against its slice
of the downloaded scan row, recomputes per-sample statistics, and checks the
manifest totals against the realized output.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import tomllib
from pathlib import Path

DATASET_ID = "zenodo_nordif_ebsd_kikuchi_patterns_u8"
SERIES_ID = "ebsd_kikuchi_pattern_u8"
SIDE = 240
NBYTES = SIDE * SIDE
STRIDE = 8
EXPECTED = {"II": (59, 208, 706_867_200), "III": (64, 323, 1_190_707_200)}
EXPECTED_SAMPLES = 4_248
INDEX_FIXED = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "numeric_kind": "uint",
    "bit_width": 8,
    "endianness": "little",
    "element_size_bytes": 1,
    "sample_size_bytes": NBYTES,
    "value_count": NBYTES,
}


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def read_area_and_acquisition(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    section = ""
    area: dict[str, str] = {}
    acquisition: dict[str, str] = {}
    with path.open("rb") as handle:
        for line in handle.read().decode("latin-1").replace("\r\n", "\n").split("\n"):
            cells = line.split("\t")
            key = cells[0].strip()
            if key[:1] == "[" and key[-1:] == "]":
                section = key
                continue
            if not key:
                continue
            value = cells[1].strip() if len(cells) > 1 else ""
            if section == "[Area]":
                area[key] = value
            elif section == "[Acquisition settings]":
                acquisition[key] = value
    return area, acquisition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    root: Path = args.data_root
    downloads = root / "downloads" / DATASET_ID
    series_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"

    # Pinned row checksums are mandatory for verification.
    if not args.pins.is_file():
        fail(f"missing pinned row checksum file {args.pins}")
    pins: dict[str, tuple[int, str]] = {}
    for line in args.pins.read_text(encoding="utf-8").splitlines():
        cells = line.split("\t")
        if cells and cells[0] and not cells[0].startswith("#"):
            pins[cells[0]] = (int(cells[1]), cells[2].strip())

    expected: list[tuple[str, int, int, int]] = []  # map, row, col, cols
    row_cache: dict[str, bytes] = {}
    for name, (rows, cols, dat_size) in EXPECTED.items():
        area, acquisition = read_area_and_acquisition(downloads / f"{name}_Setting.txt")
        if acquisition.get("Resolution") != "240x240" or acquisition.get("Gain") != "10":
            fail(f"{name}: acquisition settings {acquisition}")
        grid = tuple(int(x) for x in area.get("Number of samples", "").split("x"))
        if grid != (rows, cols) or rows * cols * NBYTES != dat_size:
            fail(f"{name}: grid {grid} inconsistent with pinned {rows}x{cols} / {dat_size}")
        for row in range(0, rows, STRIDE):
            fname = f"{name}_EBSD.row{row:03d}.bin"
            blob = (downloads / fname).read_bytes()
            if fname not in pins:
                fail(f"{fname}: not pinned")
            pin_size, pin_sha = pins[fname]
            if len(blob) != pin_size or len(blob) != cols * NBYTES:
                fail(f"{fname}: size {len(blob)} != pinned {pin_size} / {cols * NBYTES}")
            if hashlib.sha256(blob).hexdigest() != pin_sha:
                fail(f"{fname}: sha256 mismatch against pin")
            row_cache[fname] = blob
            expected.extend((name, row, col, cols) for col in range(cols))
    if len(pins) != len(row_cache):
        fail(f"pin file lists {len(pins)} rows, recipe selects {len(row_cache)}")
    if len(expected) != EXPECTED_SAMPLES:
        fail(f"expected {EXPECTED_SAMPLES} samples, derived {len(expected)}")

    lines = [line for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != len(expected):
        fail(f"index has {len(lines)} rows, expected {len(expected)}")

    histogram = [0] * 256
    aggregate = hashlib.sha256()
    seen: set[bytes] = set()
    duplicates = 0
    for line, (name, row, col, cols) in zip(lines, expected):
        record = json.loads(line)
        for key, value in INDEX_FIXED.items():
            if record.get(key) != value:
                fail(f"index {name} r{row} c{col}: {key}={record.get(key)!r} != {value!r}")
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{name}_r{row:03d}_c{col:03d}.bin"
        if record.get("sample_path") != rel:
            fail(f"index order/path mismatch: {record.get('sample_path')!r} != {rel!r}")
        if (record.get("scan_map"), record.get("scan_row"), record.get("scan_col")) != (name, row, col):
            fail(f"{rel}: scan coordinates in index disagree")
        if record.get("source_byte_offset") != (row * cols + col) * NBYTES:
            fail(f"{rel}: source_byte_offset mismatch")
        sample = (root / rel).read_bytes()
        if len(sample) != NBYTES:
            fail(f"{rel}: {len(sample)} bytes != {NBYTES}")
        source = row_cache[f"{name}_EBSD.row{row:03d}.bin"]
        if sample != source[col * NBYTES:(col + 1) * NBYTES]:
            fail(f"{rel}: bytes differ from the source scan-row slice")
        tally = collections.Counter(sample)
        lo, hi = min(tally), max(tally)
        if lo == hi:
            fail(f"{rel}: constant pattern")
        distinct = len(tally)
        if distinct < 16:
            fail(f"{rel}: degenerate pattern with {distinct} distinct values")
        if (record.get("min"), record.get("max"), record.get("distinct_values"), record.get("count_255"), record.get("count_0")) != (
            lo, hi, distinct, tally.get(255, 0), tally.get(0, 0)
        ):
            fail(f"{rel}: recorded statistics disagree with recomputation")
        digest = hashlib.sha256(sample).digest()
        if record.get("sha256") != digest.hex():
            fail(f"{rel}: sha256 in index disagrees")
        if digest in seen:
            duplicates += 1
        seen.add(digest)
        for value, count in tally.items():
            histogram[value] += count
        aggregate.update(sample)

    on_disk = sorted(p.name for p in series_dir.iterdir())
    if len(on_disk) != len(expected):
        fail(f"samples directory holds {len(on_disk)} files, expected {len(expected)}")
    if duplicates > 0.005 * len(expected):
        fail(f"{duplicates} byte-identical duplicate patterns")

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats.get("aggregate_sha256") != aggregate.hexdigest() or stats.get("histogram") != histogram:
        fail("ingest_stats.json aggregate hash or histogram disagrees with the samples")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail("manifest must declare exactly one ebsd_kikuchi_pattern_u8 series")
    total_bytes = len(expected) * NBYTES
    if series[0].get("sample_count") != len(expected) or series[0].get("total_size_bytes") != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
            f"!= realized {len(expected)}/{total_bytes}"
        )

    values = sum(histogram)
    used = [v for v in range(256) if histogram[v]]
    print(
        f"verify ok samples={len(expected)} bytes={total_bytes} range={used[0]}..{used[-1]} "
        f"distinct={len(used)} mean={sum(v * c for v, c in enumerate(histogram)) / values:.4f} "
        f"sat255_fraction={histogram[255] / values:.8f} zero_fraction={histogram[0] / values:.8f} "
        f"duplicates={duplicates} aggregate_sha256={aggregate.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
