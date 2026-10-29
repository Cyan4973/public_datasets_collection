#!/usr/bin/env python3
"""Validate, build and verify the MDPL2 dark-matter particle position prefix.

The Zenodo file mdpl2_particles_0.7333_72m.npy is a NumPy v1 file holding one
structured array of 71,806,599 records [('x', '<f8'), ('y', '<f8'), ('z', '<f8')].
download.sh range-fetches its 128-byte header and the first PARTICLES records.
The build writes those record bytes verbatim, so the sample is x0, y0, z0, x1, ...
as little-endian float64.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

DATASET_ID = "mdpl2_nbody_dm_particle_xyz_f64"
SERIES_ID = "mdpl2_dm_particle_xyz_f64"
RECORD_ID = 5259075
LICENSE_ID = "cc-by-4.0"
FILE_KEY = "mdpl2_particles_0.7333_72m.npy"
FILE_SIZE = 1_723_358_504
FILE_MD5 = "fdebca8efbac362f57de94c342537b8d"
CATALOG_PARTICLES = 71_806_599
PARTICLES = 16_000_000
RECORD_BYTES = 24
HEADER_DICT = "{'descr': [('x', '<f8'), ('y', '<f8'), ('z', '<f8')], 'fortran_order': False, 'shape': (71806599,), }"
HEADER = b"\x93NUMPY\x01\x00" + struct.pack("<H", 118) + (HEADER_DICT + " " * (117 - len(HEADER_DICT)) + "\n").encode()
PREFIX_BYTES = len(HEADER) + PARTICLES * RECORD_BYTES
PREFIX_SHA256 = "fa5904abedb4020bfc14276a7ee191db98478a253aa27a10d80c99b6ad50c89a"
PREFIX_NAME = "mdpl2_particles_0.7333_72m.prefix.npy"
RECORD_JSON = f"zenodo_record_{RECORD_ID}.json"
SAMPLE_NAME = f"mdpl2_a0.7333_particles_{0:09d}_{PARTICLES:09d}.bin"
BOX_MPC_H = 1000.0
# Cell grids (cells per box side) whose contiguity in file order the stats report.
ORDER_GRIDS = (4, 16, 512)
# Grid whose touched cells are grouped into face-connected regions (periodic box).
REGION_GRID = 16
FLOAT32 = struct.Struct("<f")


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def check_record(download_dir: Path) -> None:
    """The Zenodo record must still be CC-BY-4.0 and list the same file."""
    record = json.loads((download_dir / RECORD_JSON).read_text())
    if record.get("id") != RECORD_ID:
        fail(f"record id {record.get('id')} != {RECORD_ID}")
    license_id = (record.get("metadata", {}).get("license") or {}).get("id")
    if license_id != LICENSE_ID:
        fail(f"record license {license_id!r} != {LICENSE_ID!r}")
    entries = [entry for entry in record.get("files", []) if entry.get("key") == FILE_KEY]
    if len(entries) != 1:
        fail(f"record lists {len(entries)} entries named {FILE_KEY}")
    if entries[0].get("size") != FILE_SIZE or entries[0].get("checksum") != f"md5:{FILE_MD5}":
        fail(f"record entry changed: size={entries[0].get('size')} checksum={entries[0].get('checksum')}")


def read_prefix(download_dir: Path) -> bytes:
    """Return the record bytes of the prefix after checking size, hash and header."""
    path = download_dir / PREFIX_NAME
    data = path.read_bytes()
    if len(data) != PREFIX_BYTES:
        fail(f"{path.name}: {len(data)} bytes != {PREFIX_BYTES}")
    digest = hashlib.sha256(data).hexdigest()
    if PREFIX_SHA256 and digest != PREFIX_SHA256:
        fail(f"{path.name}: sha256 {digest} != pinned {PREFIX_SHA256}")
    if not PREFIX_SHA256:
        print(f"warning: prefix sha256 not pinned yet; computed {digest}", file=sys.stderr)
    if data[: len(HEADER)] != HEADER:
        fail(f"{path.name}: NPY header changed: {data[:len(HEADER)]!r}")
    return data[len(HEADER):]


def decimals(value: float) -> int:
    """Fewest decimal places (0-6) whose rounding reproduces value exactly, else 7."""
    if round(value, 6) != value:
        return 7
    if round(value, 5) != value:
        return 6
    places = 5
    while places > 0 and round(value, places - 1) == value:
        places -= 1
    return places


def measure(records: bytes) -> dict:
    """Validate every value and return the sample statistics."""
    if sys.byteorder != "little":
        fail("this script assumes a little-endian host")
    values = memoryview(records).cast("d")
    if len(values) != PARTICLES * 3:
        fail(f"{len(values)} values != {PARTICLES * 3}")
    place_counts = [0] * 8
    out_of_box = non_finite = float32_prints = float32_exact = 0
    for value in values:
        if not math.isfinite(value):
            non_finite += 1
            continue
        if not 0.0 <= value <= BOX_MPC_H:
            out_of_box += 1
        place_counts[decimals(value)] += 1
        # The publisher's float64 values are six-decimal prints of float32 positions.
        single = FLOAT32.unpack(FLOAT32.pack(value))[0]
        float32_exact += single == value
        float32_prints += float("%.6f" % single) == value
    if non_finite:
        fail(f"{non_finite} non-finite values")
    if out_of_box:
        fail(f"{out_of_box} values outside [0, {BOX_MPC_H}] Mpc/h")
    if place_counts[7]:
        fail(f"{place_counts[7]} values are not exact numbers with at most six decimal places")
    if float32_prints != len(values):
        fail(f"{len(values) - float32_prints} values are not the six-decimal print of their nearest float32")

    axes = {}
    for offset, name in enumerate("xyz"):
        axis = values[offset::3]
        mean = math.fsum(axis) / len(axis)
        variance = math.fsum((value - mean) ** 2 for value in axis) / len(axis)
        sampled_distinct = len(set(axis[::101]))
        if variance <= 0.0 or sampled_distinct < 1000:
            fail(f"axis {name} is degenerate: variance={variance} sampled_distinct={sampled_distinct}")
        axes[name] = {"min": min(axis), "max": max(axis), "mean": round(mean, 6), "std": round(math.sqrt(variance), 6),
                      "distinct_in_every_101st": sampled_distinct}

    order = {}
    for grid in ORDER_GRIDS:
        size = BOX_MPC_H / grid
        cells: set[tuple[int, int, int]] = set()
        runs = 0
        previous = None
        for index in range(0, len(values), 3):
            cell = (int(values[index] / size), int(values[index + 1] / size), int(values[index + 2] / size))
            if cell != previous:
                runs += 1
                cells.add(cell)
                previous = cell
        order[str(grid)] = {"cell_size_mpc_h": size, "cells": len(cells), "runs": runs}
    order[str(REGION_GRID)].update(regions(values))

    repeated = sum(1 for index in range(3, len(values), 3)
                   if values[index] == values[index - 3] and values[index + 1] == values[index - 2]
                   and values[index + 2] == values[index - 1])
    return {
        "particles": PARTICLES,
        "values": len(values),
        "bytes": len(records),
        "sha256": hashlib.sha256(records).hexdigest(),
        "min": min(axes[name]["min"] for name in "xyz"),
        "max": max(axes[name]["max"] for name in "xyz"),
        "axes": axes,
        "decimal_places": {str(places): count for places, count in enumerate(place_counts[:7])},
        "float32_print_values": float32_prints,
        "float32_exact_values": float32_exact,
        "cell_order": order,
        "particles_repeating_previous_position": repeated,
    }


def regions(values: memoryview) -> dict:
    """Face-connected regions of the touched REGION_GRID cells, with their particle counts
    and how often catalog order moves from one region to another."""
    size = BOX_MPC_H / REGION_GRID
    sequence: list[tuple[int, int, int]] = []
    counts: dict[tuple[int, int, int], int] = {}
    for index in range(0, len(values), 3):
        cell = (int(values[index] / size), int(values[index + 1] / size), int(values[index + 2] / size))
        counts[cell] = counts.get(cell, 0) + 1
        if not sequence or sequence[-1] != cell:
            sequence.append(cell)
    label: dict[tuple[int, int, int], int] = {}
    members: list[list[tuple[int, int, int]]] = []
    for seed in sorted(counts):
        if seed in label:
            continue
        label[seed] = len(members)
        group, stack = [seed], [seed]
        while stack:
            x, y, z = stack.pop()
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                near = ((x + dx) % REGION_GRID, (y + dy) % REGION_GRID, (z + dz) % REGION_GRID)
                if near in counts and near not in label:
                    label[near] = len(members)
                    group.append(near)
                    stack.append(near)
        members.append(group)
    found = sorted(({"cells": len(group), "particles": sum(counts[cell] for cell in group)} for group in members),
                   key=lambda region: -region["particles"])
    switches = sum(1 for before, after in zip(sequence, sequence[1:]) if label[before] != label[after])
    return {"regions": found, "region_switches": switches}


def index_row(stats: dict) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{SAMPLE_NAME}",
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": stats["bytes"],
        "value_count": stats["values"],
        "shape": [PARTICLES, 3],
        "source_key": FILE_KEY,
        "first_record": 0,
        "end_record": PARTICLES,
        "catalog_records": CATALOG_PARTICLES,
        "sha256": stats["sha256"],
        "min": stats["min"],
        "max": stats["max"],
    }


def cmd_validate(args: argparse.Namespace) -> None:
    check_record(args.download_dir)
    stats = measure(read_prefix(args.download_dir))
    print(json.dumps({"validated": FILE_KEY, "particles": stats["particles"], "sha256": stats["sha256"]}))


def cmd_build(args: argparse.Namespace) -> None:
    check_record(args.download_dir)
    records = read_prefix(args.download_dir)
    stats = measure(records)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*.bin"):
        if stale.name != SAMPLE_NAME:
            stale.unlink()
    (series_dir / SAMPLE_NAME).write_bytes(records)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(json.dumps(index_row(stats), sort_keys=True) + "\n")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"built": SAMPLE_NAME, "values": stats["values"], "bytes": stats["bytes"], "sha256": stats["sha256"]}))


def cmd_verify(args: argparse.Namespace) -> None:
    check_record(args.download_dir)
    records = read_prefix(args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    samples = sorted(path.name for path in series_dir.glob("*.bin"))
    if samples != [SAMPLE_NAME]:
        fail(f"unexpected sample files {samples}")
    sample = (series_dir / SAMPLE_NAME).read_bytes()
    if sample != records:
        fail("sample bytes differ from the NPY records of the pinned prefix")
    stats = measure(sample)
    recorded_stats = json.loads(args.stats.read_text())
    if recorded_stats != json.loads(json.dumps(stats)):
        fail("ingest stats differ from the recomputed statistics")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if rows != [json.loads(json.dumps(index_row(stats)))]:
        fail("index differs from the recomputed row")
    print(json.dumps({"verified": SAMPLE_NAME, "values": stats["values"], "bytes": stats["bytes"], "sha256": stats["sha256"]}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--download-dir", type=Path, required=True)
    validate.set_defaults(func=cmd_validate)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        command = sub.add_parser(name)
        command.add_argument("--download-dir", type=Path, required=True)
        command.add_argument("--samples-dir", type=Path, required=True)
        command.add_argument("--index", type=Path, required=True)
        command.add_argument("--stats", type=Path, required=True)
        command.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
