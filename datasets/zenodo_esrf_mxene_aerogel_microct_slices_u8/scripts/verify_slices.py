#!/usr/bin/env python3
"""Independently re-derive and check the ESRF ID15 MXene aerogel micro-CT
slice samples from the local downloads (local files only; shares no code with
build_slices.py, check_slice.py or check_metadata.py).
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import sys
import tomllib
from fractions import Fraction
from pathlib import Path

DATASET_ID = "zenodo_esrf_mxene_aerogel_microct_slices_u8"
SERIES_ID = "mxene_aerogel_microct_slice_u8"
N = 1381
VOXELS = N * N
PER_VOLUME = 20
MARGIN = Fraction(5, 100)
EXPECTED_STRAINS = list(range(0, 55, 5))
EXPECTED_RECORDS = {4761663: [0, 5, 10, 15], 4764282: [20, 25, 30, 35], 4766087: [40, 45, 50]}
# Same missing-value / degeneracy policy as build: every voxel is kept; a slice
# fails if it has < 64 distinct values, a modal value above 10% of voxels, a
# constant voxel row or column, or a mean grey level outside [72, 104].
MIN_DISTINCT = 64
MAX_MODAL = Fraction(1, 10)
MEAN_LO, MEAN_HI = 72, 104
# SHA-256 over "<sample name>\t<sample sha256>\n" lines in index order, from the
# verified 2026-10-06 autocollect download.
EXPECTED_LISTING_SHA256 = "eff23b6f7a8b4102e9ccea6c767e81e1273477d89bc17080c641acb20bbbe0d3"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def read_volumes(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith("#")]
    vols = []
    for fields in csv.reader(lines, delimiter="\t"):
        strain, record, raw_key, url_key, raw_bytes, _md5, z, txt_key, txt_bytes, _tmd5, txt_sha = fields
        vols.append({"strain": int(strain), "record": int(record), "raw_key": raw_key, "url_key": url_key,
                     "raw_bytes": int(raw_bytes), "z": int(z), "txt_key": txt_key,
                     "txt_bytes": int(txt_bytes), "txt_sha": txt_sha})
    if [v["strain"] for v in vols] != EXPECTED_STRAINS:
        fail("volumes.tsv does not list strains 0..50 in 5% steps")
    for record, strains in EXPECTED_RECORDS.items():
        if sorted(v["strain"] for v in vols if v["record"] == record) != strains:
            fail(f"volumes.tsv record/file map for {record} changed")
    for v in vols:
        if v["url_key"] != v["raw_key"].replace(" ", "%20"):
            fail(f"{v['raw_key']!r}: URL key {v['url_key']!r} is not the %20-encoded file name")
        if v["txt_key"] != f"{v['strain']:02d}percent.txt":
            fail(f"{v['txt_key']}: descriptor name does not match strain {v['strain']}")
    return vols


def descriptor_check(path: Path, vol: dict) -> None:
    data = path.read_bytes()
    if len(data) != vol["txt_bytes"] or hashlib.sha256(data).hexdigest() != vol["txt_sha"]:
        fail(f"{path.name}: size or sha256 differs from volumes.tsv")
    text = data.decode("ascii").lower()
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    ints = [int(x) for x in numbers if "." not in x]
    if ints[:3] != [N, N, vol["z"]]:
        fail(f"{path.name}: leading lattice numbers {ints[:3]} != [{N}, {N}, {vol['z']}]")
    if "8 bit" not in text or "little endian" not in text or "3.1" not in numbers:
        fail(f"{path.name}: does not declare 8 bit / little endian / 3.1 micron voxels")
    if N * N * vol["z"] != vol["raw_bytes"]:
        fail(f"{path.name}: lattice does not tile {vol['raw_bytes']} bytes")


def kept_z(z_count: int) -> list[int]:
    margin = math.ceil(MARGIN * z_count)
    first, last = margin, z_count - 1 - margin
    out = []
    for k in range(PER_VOLUME):
        exact = first + Fraction(k * (last - first), PER_VOLUME - 1)
        out.append(math.floor(exact + Fraction(1, 2)))
    if len(set(out)) != PER_VOLUME or out[0] < margin or out[-1] > z_count - 1 - margin:
        fail(f"bad slice plan for Z={z_count}: {out}")
    return out


def slice_stats(data: bytes) -> dict:
    counter = collections.Counter(data)
    total = sum(value * count for value, count in counter.items())
    mean = Fraction(total, VOXELS)
    modal = max(counter.values())
    if len(counter) < MIN_DISTINCT:
        fail(f"only {len(counter)} distinct values")
    if Fraction(modal, VOXELS) > MAX_MODAL:
        fail(f"modal fraction {modal / VOXELS:.3f} > 0.10")
    if not MEAN_LO <= mean <= MEAN_HI:
        fail(f"mean {float(mean):.2f} outside [{MEAN_LO}, {MEAN_HI}]")
    rows = [data[i:i + N] for i in range(0, VOXELS, N)]
    if any(len(set(row)) == 1 for row in rows):
        fail("constant voxel row")
    if any(len(set(data[x::N])) == 1 for x in range(N)):
        fail("constant voxel column")
    return {"min": min(counter), "max": max(counter), "mean": float(mean), "distinct": len(counter),
            "zeros": counter.get(0, 0), "saturated": counter.get(255, 0)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--volumes", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    root: Path = args.data_root
    downloads = root / "downloads" / DATASET_ID
    series_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"

    vols = read_volumes(args.volumes)
    if not args.pins.is_file():
        fail(f"pinned slice checksums missing: {args.pins}")
    pins = {}
    for line in args.pins.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, size, digest = line.split("\t")
            if int(size) != VOXELS:
                fail(f"pin {name}: size {size} != {VOXELS}")
            pins[name] = digest

    expected = []  # (sample name, source slice name, vol, z)
    for vol in vols:
        descriptor_check(downloads / "descriptors" / vol["txt_key"], vol)
        for z in kept_z(vol["z"]):
            expected.append((f"strain{vol['strain']:02d}pct_z{z:04d}.bin", f"s{vol['strain']:02d}_z{z:04d}.bin", vol, z))
    if len(expected) != 220:
        fail(f"expected 220 planned slices, got {len(expected)}")
    if set(pins) != {src for _, src, _, _ in expected}:
        fail("slice_sha256.tsv does not pin exactly the planned slices")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in rows}
    if len(by_path) != len(rows):
        fail("duplicate sample_path in index")
    expected_paths = [f"samples/{DATASET_ID}/{SERIES_ID}/{name}" for name, _, _, _ in expected]
    if [row["sample_path"] for row in rows] != expected_paths:
        fail("index rows are not exactly the planned samples in strain, z order")
    on_disk = sorted(p.name for p in series_dir.iterdir())
    if on_disk != sorted(name for name, _, _, _ in expected):
        fail("sample directory does not match the planned sample list")

    digests = set()
    listing = hashlib.sha256()
    histogram = collections.Counter()
    for (name, src, vol, z), rel in zip(expected, expected_paths):
        sample = (root / rel).read_bytes()
        source = (downloads / "slices" / src).read_bytes()
        if len(sample) != VOXELS:
            fail(f"{name}: {len(sample)} bytes != {VOXELS}")
        if sample != source:
            fail(f"{name}: differs from downloaded slice {src}")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != pins[src]:
            fail(f"{name}: sha256 {digest} != pinned {pins[src]}")
        if digest in digests:
            fail(f"{name}: duplicate payload")
        digests.add(digest)
        listing.update(f"{name}\t{digest}\n".encode())
        try:
            stats = slice_stats(sample)
        except SystemExit as exc:
            fail(f"{name}: {exc}")
        histogram.update(sample)
        row = by_path[rel]
        want = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": VOXELS, "value_count": VOXELS,
            "shape": [N, N], "strain_pct": vol["strain"], "z_index": z, "z_slices": vol["z"],
            "source_record": vol["record"], "source_file": vol["raw_key"], "source_byte_offset": z * VOXELS,
            "min": stats["min"], "max": stats["max"], "distinct_values": stats["distinct"],
            "zeros": stats["zeros"], "saturated_255": stats["saturated"], "sha256": digest,
        }
        for key, value in want.items():
            if row.get(key) != value:
                fail(f"{name}: index {key}={row.get(key)!r} != {value!r}")
        if abs(row.get("mean", -1) - stats["mean"]) > 5e-4:
            fail(f"{name}: index mean {row.get('mean')} != {stats['mean']:.4f}")

    if listing.hexdigest() != EXPECTED_LISTING_SHA256:
        fail(f"listing sha256 {listing.hexdigest()} != pinned {EXPECTED_LISTING_SHA256}")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail("manifest must declare exactly one series with the expected id")
    s = series[0]
    if (s.get("role"), s.get("numeric_kind"), s.get("bit_width")) != ("primary", "uint", 8):
        fail("manifest series role/kind/width mismatch")
    if s.get("sample_count") != len(rows) or s.get("total_size_bytes") != len(rows) * VOXELS:
        fail(f"manifest sample_count/total_size_bytes {s.get('sample_count')}/{s.get('total_size_bytes')} "
             f"!= realized {len(rows)}/{len(rows) * VOXELS}")

    total = sum(histogram.values())
    mean = sum(v * c for v, c in histogram.items()) / total
    print(f"verify ok samples={len(rows)} bytes={len(rows) * VOXELS} distinct_payloads={len(digests)} "
          f"range={min(histogram)}..{max(histogram)} mean={mean:.4f} "
          f"zero_fraction={histogram.get(0, 0) / total:.8f} sat255_fraction={histogram.get(255, 0) / total:.8f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
