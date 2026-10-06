#!/usr/bin/env python3
"""Build GOOSE VLS-128 sweep xyz float32 samples from locally downloaded members.

Each pinned sweep payload is a SemanticKITTI-layout `.bin`: N points x 4
little-endian float32 fields (x, y, z, remission). The sample keeps the first
three fields of every point bit-exactly, in source point order, as an N x 3
row-major little-endian float32 array. Remission is dropped (integer-valued
0..255 stored as float, so it is not a genuine float32 quantity).

Missing-value policy (shared with verify_samples.py): every field of every
point must be finite, and no point may be an all-zero (x = y = z = 0) padding
point; either condition is fatal. Nothing is dropped, reordered, or imputed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import zlib
from array import array
from pathlib import Path

DATASET_ID = "goose_vls128_lidar_scan_xyz_f32"
SERIES_ID = "goose_vls128_sweep_xyz_f32"
POINT_BYTES = 16


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        for key in ("local_header_offset", "range_start", "range_end", "payload_bytes", "point_count"):
            row[key] = int(row[key])
    return rows


def float_array(raw: bytes) -> array:
    values = array("f")
    if values.itemsize != 4:
        raise SystemExit("platform float is not 32-bit")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def count_non_finite(values: array) -> int:
    total = sum(values)
    # With |value| far below 1e30 the float64 sum cannot overflow, so a finite sum
    # proves every value finite; otherwise count exactly.
    if math.isfinite(total):
        return 0
    return sum(1 for value in values if not math.isfinite(value))


def sweep_diagnostics(xs: array, ys: array, zs: array) -> dict:
    degree_counts = [0] * 360
    backward_jumps = 0
    previous = None
    min_range = math.inf
    max_range = 0.0
    for x, y, z in zip(xs, ys, zs):
        azimuth = math.degrees(math.atan2(y, x)) % 360.0
        degree_counts[int(azimuth) % 360] += 1
        if previous is not None:
            # Points are stored in firing order while the head turns clockwise (azimuth
            # decreasing); count consecutive points that jump > 5 degrees the other way.
            increase = (azimuth - previous) % 360.0
            if 5.0 < increase < 180.0:
                backward_jumps += 1
        previous = azimuth
        distance = math.sqrt(x * x + y * y + z * z)
        min_range = min(min_range, distance)
        max_range = max(max_range, distance)
    return {
        "azimuth_degrees_covered": sum(1 for count in degree_counts if count),
        "max_points_per_azimuth_degree": max(degree_counts),
        "counter_rotation_jumps_gt5deg": backward_jumps,
        "range_m_min": min_range,
        "range_m_max": max_range,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "build_stats.json"
    license_path = download_dir / "meta" / "LICENSE"
    if not license_path.is_file() or not license_path.read_text(encoding="utf-8").startswith(
        "Attribution-ShareAlike 4.0 International"
    ):
        raise SystemExit(f"missing or unexpected LICENSE member at {license_path}; run download.sh")

    rows = load_sources(args.sources)
    if len(rows) != 64 or len({row["sequence"] for row in rows}) != 8:
        raise SystemExit("sources.tsv must pin 8 sweeps from each of 8 val sequences")

    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.iterdir():
        if stale.is_file():
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    index_rows = []
    sweeps = []
    total_values = total_bytes = 0
    for row in rows:
        member_base = Path(row["member_name"]).name
        payload_path = download_dir / "lidar" / "val" / row["sequence"] / member_base
        payload = payload_path.read_bytes() if payload_path.is_file() else b""
        if len(payload) != row["payload_bytes"]:
            raise SystemExit(f"{payload_path}: missing or wrong size ({len(payload)} != {row['payload_bytes']})")
        if f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}" != row["crc32"]:
            raise SystemExit(f"{payload_path}: CRC32 mismatch")
        if len(payload) % POINT_BYTES:
            raise SystemExit(f"{payload_path}: not a whole number of 16-byte points")
        points = len(payload) // POINT_BYTES
        if points != row["point_count"]:
            raise SystemExit(f"{payload_path}: point count {points} != pinned {row['point_count']}")

        values = float_array(payload)
        non_finite = count_non_finite(values)
        if non_finite:
            raise SystemExit(f"{member_base}: {non_finite} non-finite float32 fields (fatal by policy)")
        xs, ys, zs, remission = values[0::4], values[1::4], values[2::4], values[3::4]
        zero_points = sum(1 for x, y, z in zip(xs, ys, zs) if x == 0.0 and y == 0.0 and z == 0.0)
        if zero_points:
            raise SystemExit(f"{member_base}: {zero_points} all-zero padding points (fatal by policy)")
        for axis, column in (("x", xs), ("y", ys), ("z", zs)):
            if min(column) == max(column):
                raise SystemExit(f"{member_base}: constant {axis} column")

        xyz = array("f", bytes(12 * points))
        xyz[0::3] = xs
        xyz[1::3] = ys
        xyz[2::3] = zs
        stored_min = min(xyz)
        stored_max = max(xyz)
        if sys.byteorder != "little":
            xyz.byteswap()
        sample_bytes = xyz.tobytes()
        sample_name = f"{member_base[: -len('.bin')]}_xyz.f32"
        sample_path = series_dir / sample_name
        tmp_path = sample_path.with_suffix(".f32.part")
        tmp_path.write_bytes(sample_bytes)
        os.replace(tmp_path, sample_path)

        value_count = 3 * points
        total_values += value_count
        total_bytes += len(sample_bytes)
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": sample_path.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(sample_bytes),
                "value_count": value_count,
                "sample_shape": [points, 3],
                "sample_axes": ["point", "xyz_component"],
                "point_count": points,
                "sequence": row["sequence"],
                "frame": row["frame"],
                "timestamp_ns": row["timestamp_ns"],
                "source_member": row["member_name"],
                "source_crc32": row["crc32"],
                "min": stored_min,
                "max": stored_max,
                "sha256": hashlib.sha256(sample_bytes).hexdigest(),
            }
        )
        diagnostics = sweep_diagnostics(xs, ys, zs)
        sweeps.append(
            {
                "sample": sample_name,
                "sequence": row["sequence"],
                "frame": row["frame"],
                "points": points,
                "x_min": min(xs),
                "x_max": max(xs),
                "y_min": min(ys),
                "y_max": max(ys),
                "z_min": min(zs),
                "z_max": max(zs),
                "remission_min": min(remission),
                "remission_max": max(remission),
                "remission_all_integral": all(value == int(value) for value in remission),
                "source_payload_sha256": hashlib.sha256(payload).hexdigest(),
                **diagnostics,
            }
        )
        print(
            f"sample={sample_name} points={points} min={stored_min:.3f} max={stored_max:.3f} "
            f"azimuth_deg={diagnostics['azimuth_degrees_covered']} max_per_deg={diagnostics['max_points_per_azimuth_degree']}"
        )

    tmp_index = index_path.with_suffix(".jsonl.part")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    os.replace(tmp_index, index_path)
    counts = sorted(item["value_count"] for item in index_rows)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "points": total_values // 3,
        "values": total_values,
        "bytes": total_bytes,
        "median_sample_values": (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2,
        "non_finite_fields": 0,
        "all_zero_points": 0,
        "partial_sweeps_lt_300deg": sum(1 for sweep in sweeps if sweep["azimuth_degrees_covered"] < 300),
        "sweeps": sweeps,
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(
        f"build_summary samples={len(index_rows)} points={total_values // 3} values={total_values} bytes={total_bytes} "
        f"partial_sweeps_lt_300deg={stats['partial_sweeps_lt_300deg']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
