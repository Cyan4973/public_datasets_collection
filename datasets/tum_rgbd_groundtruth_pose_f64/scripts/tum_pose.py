#!/usr/bin/env python3
"""Build and verify TUM RGB-D ground-truth pose trajectory matrices."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import tarfile
import zlib


DATASET_ID = "tum_rgbd_groundtruth_pose_f64"
MEMBER = "rgbd_dataset_freiburg1_xyz/groundtruth.txt"
SOURCE_NAME = "rgbd_dataset_freiburg1_xyz.tgz"
SOURCE_URL = (
    "https://cvg.cit.tum.de/rgbd/dataset/freiburg1/"
    "rgbd_dataset_freiburg1_xyz.tgz"
)
EXPECTED_ROWS = 3_000
MIN_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def read_poses(path: Path) -> tuple[list[float], list[float], list[float]]:
    if not path.is_file():
        raise ValueError(f"missing source archive: {path}")
    timestamps: list[float] = []
    translation: list[float] = []
    quaternion: list[float] = []
    with tarfile.open(path, "r:gz") as archive:
        try:
            member = archive.getmember(MEMBER)
        except KeyError as exc:
            raise ValueError(f"archive lacks {MEMBER}") from exc
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError(f"cannot read {MEMBER}")
        for line_number, raw in enumerate(handle, 1):
            try:
                line = raw.decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise ValueError(f"non-ASCII ground truth at line {line_number}") from exc
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 8:
                raise ValueError(
                    f"line {line_number}: expected 8 fields, found {len(fields)}"
                )
            try:
                values = [float(field) for field in fields]
            except ValueError as exc:
                raise ValueError(f"line {line_number}: invalid decimal field") from exc
            if any(not math.isfinite(value) for value in values):
                raise ValueError(f"line {line_number}: non-finite pose field")
            timestamp = values[0]
            if timestamps and timestamp <= timestamps[-1]:
                raise ValueError(f"line {line_number}: timestamp is not increasing")
            norm = math.sqrt(sum(value * value for value in values[4:8]))
            if abs(norm - 1.0) > 0.001:
                raise ValueError(
                    f"line {line_number}: quaternion norm {norm} is not near unity"
                )
            timestamps.append(timestamp)
            translation.extend(values[1:4])
            quaternion.extend(values[4:8])
    if len(timestamps) != EXPECTED_ROWS:
        raise ValueError(
            f"expected {EXPECTED_ROWS} poses, found {len(timestamps)}"
        )
    for offset, name in enumerate(("tx", "ty", "tz")):
        if len(set(translation[offset::3])) <= 1:
            raise ValueError(f"constant translation component {name}")
    for offset, name in enumerate(("qx", "qy", "qz", "qw")):
        if len(set(quaternion[offset::4])) <= 1:
            raise ValueError(f"constant quaternion component {name}")
    return timestamps, translation, quaternion


def pack_f64(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}d", *values)


def trajectory_metrics(
    timestamps: list[float], translation: list[float], quaternion: list[float]
) -> dict[str, float | int]:
    translation_steps = []
    quaternion_dots = []
    for index in range(1, len(timestamps)):
        a = translation[(index - 1) * 3 : index * 3]
        b = translation[index * 3 : (index + 1) * 3]
        translation_steps.append(math.sqrt(sum((y - x) ** 2 for x, y in zip(a, b))))
        qa = quaternion[(index - 1) * 4 : index * 4]
        qb = quaternion[index * 4 : (index + 1) * 4]
        quaternion_dots.append(abs(sum(x * y for x, y in zip(qa, qb))))
    return {
        "pose_count": len(timestamps),
        "duration_seconds": timestamps[-1] - timestamps[0],
        "median_translation_step_metres": statistics.median(translation_steps),
        "max_translation_step_metres": max(translation_steps),
        "median_adjacent_quaternion_abs_dot": statistics.median(quaternion_dots),
        "min_adjacent_quaternion_abs_dot": min(quaternion_dots),
    }


def inspect(path: Path) -> None:
    timestamps, translation, quaternion = read_poses(path)
    metrics = trajectory_metrics(timestamps, translation, quaternion)
    print(
        f"semantic_validation=ok poses={len(timestamps)} "
        f"translation_values={len(translation)} quaternion_values={len(quaternion)} "
        f"duration_seconds={metrics['duration_seconds']:.4f}"
    )


def build(source: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    timestamps, translation, quaternion = read_poses(source)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    definitions = (
        (
            "tum_rgbd_translation_f64",
            translation,
            3,
            "row-major float64 translation matrix",
            "pose_translation_trajectory",
            "xyz_component",
            "tx ty tz",
            "tum_rgbd_groundtruth_sequence_translation_trajectory",
        ),
        (
            "tum_rgbd_quaternion_f64",
            quaternion,
            4,
            "row-major float64 quaternion matrix",
            "pose_orientation_trajectory",
            "xyzw_component",
            "qx qy qz qw",
            "tum_rgbd_groundtruth_sequence_orientation_trajectory",
        ),
    )
    rows = []
    compression = {}
    pose_count = len(timestamps)
    for (
        series_id,
        values,
        width,
        sample_format,
        geometry,
        component_axis,
        source_field,
        record_kind,
    ) in definitions:
        output_dir = samples_dir / series_id
        output_dir.mkdir()
        output = output_dir / f"freiburg1_xyz_{series_id}_n{len(values):07d}.bin"
        payload = pack_f64(values)
        output.write_bytes(payload)
        compression[series_id] = len(zlib.compress(payload, 9)) / len(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": series_id,
                "role": "primary",
                "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(payload),
                "value_count": len(values),
                "sample_format": sample_format,
                "sample_geometry": geometry,
                "sample_rank": 2,
                "sample_shape": [pose_count, width],
                "sample_axes": ["pose", component_axis],
                "natural_record_kind": record_kind,
                "source_field": source_field,
                "source_sample": MEMBER,
                "source_url": SOURCE_URL,
            }
        )

    counts = [row["value_count"] for row in rows]
    total_values = sum(counts)
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_VALUES:
        raise ValueError(f"total values below floor: {total_values}")
    if median_values < MIN_MEDIAN_VALUES:
        raise ValueError(f"median sample below floor: {median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")

    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "source_file": source.name,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "zlib_ratio": compression,
        **trajectory_metrics(timestamps, translation, quaternion),
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built poses={pose_count} samples={len(rows)} "
        f"primary_values={total_values} primary_bytes={total_bytes} "
        f"median={median_values:g}"
    )


def verify(source: Path, index_path: Path, data_root: Path) -> None:
    _, translation, quaternion = read_poses(source)
    expected = {
        "tum_rgbd_translation_f64": (translation, [EXPECTED_ROWS, 3]),
        "tum_rgbd_quaternion_f64": (quaternion, [EXPECTED_ROWS, 4]),
    }
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 2:
        raise ValueError(f"expected two samples, found {len(rows)}")
    seen = set()
    counts = []
    total_bytes = 0
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("role") != "primary":
            raise ValueError("invalid index identity or role")
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 64:
            raise ValueError("indexed sample is not float64")
        series_id = row.get("series_id")
        if series_id not in expected or series_id in seen:
            raise ValueError(f"unexpected or duplicate series {series_id!r}")
        seen.add(series_id)
        values, shape = expected[series_id]
        if row.get("sample_shape") != shape or row.get("sample_rank") != 2:
            raise ValueError(f"wrong trajectory shape for {series_id}")
        sample = data_root / row["sample_path"]
        payload = sample.read_bytes()
        if payload != pack_f64(values):
            raise ValueError(f"source-to-output mismatch for {series_id}")
        if len(payload) != row.get("sample_size_bytes") or len(values) != row.get(
            "value_count"
        ):
            raise ValueError(f"indexed size/count mismatch for {series_id}")
        decoded = [value[0] for value in struct.iter_unpack("<d", payload)]
        if any(not math.isfinite(value) for value in decoded):
            raise ValueError(f"non-finite output for {series_id}")
        counts.append(len(values))
        total_bytes += len(payload)
    if sum(counts) < MIN_VALUES or statistics.median(counts) < MIN_MEDIAN_VALUES:
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
    inspect_parser.add_argument("source", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source", required=True, type=Path)
    build_parser.add_argument("--samples-dir", required=True, type=Path)
    build_parser.add_argument("--index", required=True, type=Path)
    build_parser.add_argument("--stats", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source", required=True, type=Path)
    verify_parser.add_argument("--index", required=True, type=Path)
    verify_parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.source)
    elif args.command == "build":
        build(args.source, args.samples_dir, args.index, args.stats)
    else:
        verify(args.source, args.index, args.data_root)


if __name__ == "__main__":
    main()
