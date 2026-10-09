#!/usr/bin/env python3
"""Independent verification of swisstopo_swisssurface3d_alps_las_z_i32 output.

Re-derives every sample from the local zips with a different code path than
build (struct.iter_unpack of whole 28-byte LAS records instead of strided byte
slicing), compares bytes, and re-checks the index, manifest totals, the
missing-value policy (none: every record kept) and degeneracy.
"""

from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import struct
import sys
import tomllib
import zipfile
from pathlib import Path

DATASET_ID = "swisstopo_swisssurface3d_alps_las_z_i32"
SERIES_ID = "swisssurface3d_z_i32"
RECORD = struct.Struct("<iiiHBBbBHd")  # LAS point data record format 1
HEADER = struct.Struct("<4sHHIHH8sBB32s32sHHHIIBHI5I3d3d6d")
BLOCK = 200_000
INDEX_KEYS = (
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width",
    "endianness", "element_size_bytes", "sample_size_bytes", "value_count",
)


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    if sys.byteorder != "little":
        fail("little-endian host required")
    assert RECORD.size == 28 and HEADER.size == 227

    with args.sources.open(newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if len(rows) != len(sources):
        fail(f"index has {len(rows)} rows, sources {len(sources)}")
    manifest = tomllib.loads(args.manifest.read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    series = series[0]

    on_disk = sorted((data_root / "samples" / DATASET_ID / SERIES_ID).glob("*"))
    if len(on_disk) != len(sources):
        fail(f"{len(on_disk)} files on disk, expected {len(sources)}")

    hashes = set()
    total_bytes = 0
    for src, row in zip(sources, rows):
        for key in INDEX_KEYS:
            if key not in row:
                fail(f"index row missing {key}")
        if (row["dataset_id"], row["series_id"], row["numeric_kind"], row["bit_width"],
                row["endianness"], row["element_size_bytes"]) != (DATASET_ID, SERIES_ID, "int", 32, "little", 4):
            fail(f"bad index metadata {row}")
        if row["source_item"] != src["item_id"]:
            fail(f"index order mismatch {row['source_item']} vs {src['item_id']}")
        easting, northing = src["item_id"].rsplit("_", 1)[1].split("-")
        n_expected = int(src["point_count"])
        sample = data_root / row["sample_path"]
        size = sample.stat().st_size
        if size != row["sample_size_bytes"] or size != 4 * row["value_count"] or row["value_count"] != n_expected:
            fail(f"{sample.name}: size/count mismatch")

        zip_path = args.download_dir / src["asset_name"]
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if names != [src["member_name"]]:
                fail(f"{zip_path.name}: members {names}")
            info = zf.getinfo(names[0])
            if info.CRC != int(src["member_crc32"], 16) or info.file_size != 227 + 28 * n_expected:
                fail(f"{zip_path.name}: CRC/size mismatch")
            with zf.open(info) as member, sample.open("rb") as out:
                h = HEADER.unpack(member.read(227))
                (sig, _src_id, _enc, _g1, _g2, _g3, _g4, vmaj, vmin, _sys, _sw, _doy, _yr,
                 hsize, pofs, nvlr, pf, rl, npts) = h[:19]
                sx, sy, sz, ox, oy, oz = h[24:30]
                maxz, minz = h[34], h[35]
                if (sig, vmaj, vmin, hsize, pofs, nvlr, pf, rl, npts) != (b"LASF", 1, 2, 227, 227, 0, 1, 28, n_expected):
                    fail(f"{zip_path.name}: header {h[:19]}")
                if (sx, sy, sz, ox, oy, oz) != (0.01, 0.01, 0.01, int(easting) * 1000.0, int(northing) * 1000.0, 0.0):
                    fail(f"{zip_path.name}: scale/offset")
                digest = hashlib.sha256()
                zmin = zmax = None
                remaining = n_expected
                previous_block = None
                varied = False
                while remaining:
                    count = min(BLOCK, remaining)
                    buf = member.read(count * 28)
                    if len(buf) != count * 28:
                        fail(f"{zip_path.name}: truncated")
                    z = array.array("i", (rec[2] for rec in RECORD.iter_unpack(buf)))
                    expected = z.tobytes()
                    got = out.read(len(expected))
                    if got != expected:
                        fail(f"{sample.name}: bytes differ from re-derived Z")
                    digest.update(got)
                    bmin, bmax = min(z), max(z)
                    zmin = bmin if zmin is None else min(zmin, bmin)
                    zmax = bmax if zmax is None else max(zmax, bmax)
                    if previous_block is not None and previous_block != expected:
                        varied = True
                    previous_block = expected
                    remaining -= count
                if member.read(1) != b"" or out.read(1) != b"":
                    fail(f"{sample.name}: trailing data")
        if zmin == zmax or not varied and n_expected > BLOCK:
            fail(f"{sample.name}: degenerate Z")
        if (zmin, zmax) != (row["min"], row["max"]) or (zmin, zmax) != (round(minz * 100), round(maxz * 100)):
            fail(f"{sample.name}: min/max {zmin}..{zmax} vs index {row['min']}..{row['max']} / header")
        if not (100_000 <= zmin and zmax <= 500_000):
            fail(f"{sample.name}: implausible Z codes")
        if row["top_value_fraction"] > 0.05 or row["distinct_values"] < 10_000:
            fail(f"{sample.name}: dominated or low-cardinality sample")
        if digest.hexdigest() != row["sha256"] or row["sha256"] in hashes:
            fail(f"{sample.name}: sha256 mismatch or duplicate sample")
        hashes.add(row["sha256"])
        total_bytes += size
        print(f"verified {sample.name} values={n_expected} z_code={zmin}..{zmax}")

    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        fail(f"manifest totals {series['sample_count']}/{series['total_size_bytes']} vs {len(rows)}/{total_bytes}")
    if total_bytes > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    print(f"verify=ok samples={len(rows)} bytes={total_bytes}")


if __name__ == "__main__":
    main()
