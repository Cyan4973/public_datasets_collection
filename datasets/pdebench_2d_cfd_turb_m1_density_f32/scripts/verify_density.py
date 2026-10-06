#!/usr/bin/env python3
"""Independent verification of the PDEBench 2D CFD Turb M1.0 density samples.

Re-derives every expected byte range from the HDF5 layout parsed out of the
pinned metadata ranges (not from the build's constants), byte-compares each
sample with its fetched range, rescans values through a separate code path
(memoryview cast plus per-value isfinite), and cross-checks the sample index,
ingest statistics and manifest totals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pdebench_h5 as h5  # noqa: E402

DATASET_ID = "pdebench_2d_cfd_turb_m1_density_f32"
SERIES_ID = "cfd_turb_m1_density_trajectory_f32"
FILE_SIZE = 88_080_392_528
STRIDE = 25
MIN_DISTINCT = 10_000
EXPECTED_ROOT = {"Vx", "Vy", "density", "pressure", "t-coordinate", "x-coordinate", "y-coordinate"}
PREFIX = (0, "4b901a23ac2c49174a8726031b60eba8953127bc29c0a1bf7438fde63b0e8b09")
ISLAND = (66_060_290_048, "ac53bc506b485b7de64f97a6e1740ad2e934480dee9c5e9e1d102b98526b99ba")


def fail(message: str) -> None:
    raise SystemExit(f"{DATASET_ID} verify: {message}")


def density_layout(downloads: Path) -> tuple[int, tuple[int, ...]]:
    segments = []
    for (start, digest), name in ((PREFIX, "hdf5_prefix.bin"), (ISLAND, "hdf5_island.bin")):
        payload = (downloads / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            fail(f"{name} does not match its pinned SHA-256")
        segments.append((start, payload))
    report = h5.describe(h5.Sparse(segments))
    if report["superblock"]["eof_address"] != FILE_SIZE or set(report["datasets"]) != EXPECTED_ROOT:
        fail("HDF5 superblock or root group changed")
    density = report["datasets"]["density"]
    shape = tuple(density["shape"])
    layout = density["layout"]
    if len(shape) != 4 or not density["is_f32le"] or density["has_filter_pipeline"] or density["has_external_files"]:
        fail(f"/density is no longer an unfiltered rank-4 F32LE dataset: {density}")
    if layout.get("class") != "contiguous" or layout["size"] != 4 * math.prod(shape):
        fail(f"/density layout is not a contiguous full-size block: {layout}")
    return layout["address"], shape


def scan(payload: bytes, frames: int, frame_values: int) -> dict:
    view = memoryview(payload).cast("f")
    if sys.byteorder != "little":
        fail("verification assumes a little-endian host")
    if not all(map(math.isfinite, view)):
        fail("non-finite value in sample")
    low = min(view)
    high = max(view)
    if low <= 0.0:
        fail(f"non-positive density {low}")
    if low == high:
        fail("constant sample")
    frame0 = view[:frame_values]
    distinct = []
    for frame in range(1, frames):
        count = len(set(view[frame * frame_values : (frame + 1) * frame_values]))
        if count < MIN_DISTINCT:
            fail(f"degenerate frame t={frame}: {count} distinct values")
        distinct.append(count)
    return {
        "min": low,
        "max": high,
        "t0_uniform_one": min(frame0) == 1.0 and max(frame0) == 1.0,
        "min_distinct": min(distinct),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--recipe-dir", required=True)
    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()
    recipe = Path(args.recipe_dir).resolve()
    downloads = data_root / "downloads" / DATASET_ID
    output_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"

    address, shape = density_layout(downloads)
    frames, frame_values = shape[1], shape[2] * shape[3]
    record_bytes = 4 * frames * frame_values
    expected_indices = list(range(0, shape[0], STRIDE))

    pins: dict[int, str] = {}
    pin_file = recipe / "trajectory_sha256.tsv"
    if pin_file.is_file():
        for line in pin_file.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(("#", "trajectory_index")):
                index, start, end, digest = line.split("\t")
                pins[int(index)] = digest
        if sorted(pins) != expected_indices:
            fail("pinned trajectory hashes do not cover the expected selection")
    else:
        print("WARNING: trajectory_sha256.tsv absent; verifying against fetched ranges only")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [row.get("source_trajectory_index") for row in rows] != expected_indices:
        fail("index does not list the evenly spaced trajectories in order")
    aggregate = hashlib.sha256()
    seen_hashes: set[str] = set()
    expected_files = set()
    t0_uniform = 0
    low = math.inf
    high = -math.inf
    for row, index in zip(rows, expected_indices):
        start = address + index * record_bytes
        end = start + record_bytes - 1
        name = f"density_traj_{index:04d}.f32"
        sample = output_dir / name
        expected_files.add(sample)
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": sample.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": record_bytes,
            "value_count": frames * frame_values,
            "shape": [frames, shape[2], shape[3]],
            "source_byte_start": start,
            "source_byte_end": end,
            "source_dataset": "/density",
        }
        for key, value in fixed.items():
            if row.get(key) != value:
                fail(f"index field {key} for trajectory {index}: {row.get(key)!r} != {value!r}")
        payload = sample.read_bytes()
        if len(payload) != record_bytes:
            fail(f"{name} has {len(payload)} bytes")
        digest = hashlib.sha256(payload).hexdigest()
        fetched = downloads / name
        if hashlib.sha256(fetched.read_bytes()).hexdigest() != digest:
            fail(f"{name} differs from the fetched byte range {start}-{end}")
        if row.get("sample_sha256") != digest or (pins and pins[index] != digest):
            fail(f"{name} SHA-256 disagrees with the index or the pinned hash")
        if digest in seen_hashes:
            fail(f"duplicate trajectory payload {name}")
        seen_hashes.add(digest)
        stats = scan(payload, frames, frame_values)
        if (row.get("min"), row.get("max"), row.get("t0_uniform_one"), row.get("min_distinct_per_frame_t_ge_1")) != (
            stats["min"], stats["max"], stats["t0_uniform_one"], stats["min_distinct"]
        ):
            fail(f"index statistics for trajectory {index} do not match a fresh scan: {stats}")
        t0_uniform += stats["t0_uniform_one"]
        low = min(low, stats["min"])
        high = max(high, stats["max"])
        aggregate.update(payload)
        print(f"verified trajectory={index} range={stats['min']!r}..{stats['max']!r} "
              f"t0_uniform_one={stats['t0_uniform_one']} min_distinct={stats['min_distinct']}", flush=True)

    actual_files = set(output_dir.iterdir())
    if actual_files != expected_files:
        fail(f"unexpected files in sample directory: {sorted(map(str, actual_files ^ expected_files))[:5]}")
    count = len(rows)
    total_bytes = count * record_bytes
    median_values = statistics.median(row["value_count"] for row in rows)
    if total_bytes > 1_000_000_000 or median_values < 1_000 or count < 5:
        fail("output violates the repository cap or floors")

    summary = json.loads(stats_path.read_text(encoding="utf-8"))
    checks = {
        "sample_count": count,
        "total_size_bytes": total_bytes,
        "total_values": count * frames * frame_values,
        "minimum": low,
        "maximum": high,
        "samples_with_uniform_one_t0_frame": t0_uniform,
        "aggregate_sha256": aggregate.hexdigest(),
    }
    for key, value in checks.items():
        if summary.get(key) != value:
            fail(f"ingest_stats {key}={summary.get(key)!r} != recomputed {value!r}")

    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("sample_count") != count or series[0].get("total_size_bytes") != total_bytes:
        fail("manifest sample_count/total_size_bytes do not match the realized output")
    print(
        f"verify=ok samples={count} values={count * frames * frame_values} bytes={total_bytes} "
        f"range={low!r}..{high!r} t0_uniform_one={t0_uniform}/{count} pinned={'yes' if pins else 'no'} "
        f"aggregate_sha256={aggregate.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, h5.H5Error) as exc:
        raise SystemExit(f"{DATASET_ID} verify: {exc}") from exc
