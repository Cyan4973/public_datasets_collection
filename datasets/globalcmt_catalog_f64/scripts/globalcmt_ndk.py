#!/usr/bin/env python3
"""Strict parser, builder, and verifier for standard five-line Global CMT NDK."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct


DATASET_ID = "globalcmt_catalog_f64"
COMPONENTS = ("mrr", "mtt", "mpp", "mrt", "mrp", "mtp")
MIN_EVENTS = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def parse_source(path: Path) -> dict[str, list[float]]:
    if not path.is_file():
        raise ValueError(f"missing source file: {path}")
    raw_lines = path.read_text(encoding="ascii", errors="strict").splitlines()
    if not raw_lines:
        raise ValueError("empty NDK source")
    if any(not line.strip() for line in raw_lines):
        raise ValueError("unexpected blank line in fixed five-line NDK stream")
    if len(raw_lines) % 5:
        raise ValueError(
            f"NDK line count {len(raw_lines)} is not divisible by five"
        )

    values = {component: [] for component in COMPONENTS}
    for line_index in range(0, len(raw_lines), 5):
        record_number = line_index // 5 + 1
        line1, line2, line3, line4, line5 = raw_lines[line_index : line_index + 5]
        if not line1.strip():
            raise ValueError(f"record {record_number}: empty hypocenter line")
        if "CMT:" not in line2:
            raise ValueError(f"record {record_number}: missing CMT field on line two")
        if not line3.startswith("CENTROID:"):
            raise ValueError(f"record {record_number}: malformed centroid line")
        if not line5.startswith("V"):
            raise ValueError(f"record {record_number}: malformed principal-axis line")

        fields = line4.split()
        if len(fields) != 13:
            raise ValueError(
                f"record {record_number}: tensor line has {len(fields)} fields, expected 13"
            )
        try:
            exponent = int(fields[0])
        except ValueError as exc:
            raise ValueError(
                f"record {record_number}: invalid tensor exponent {fields[0]!r}"
            ) from exc
        if not 10 <= exponent <= 40:
            raise ValueError(
                f"record {record_number}: implausible tensor exponent {exponent}"
            )

        for component, field in zip(COMPONENTS, fields[1::2], strict=True):
            try:
                reconstructed = float(Decimal(field).scaleb(exponent))
            except (InvalidOperation, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"record {record_number}: invalid {component} mantissa {field!r}"
                ) from exc
            if not math.isfinite(reconstructed):
                raise ValueError(f"record {record_number}: non-finite {component}")
            values[component].append(reconstructed)

        # Validate the six paired standard-error fields as numeric, while keeping
        # them out of the primary output.
        for field in fields[2::2]:
            try:
                uncertainty = float(field)
            except ValueError as exc:
                raise ValueError(
                    f"record {record_number}: invalid tensor uncertainty {field!r}"
                ) from exc
            if not math.isfinite(uncertainty) or uncertainty < 0:
                raise ValueError(
                    f"record {record_number}: invalid tensor uncertainty {field!r}"
                )

    event_count = len(values["mrr"])
    if event_count < MIN_EVENTS:
        raise ValueError(f"only {event_count} events; require at least {MIN_EVENTS}")
    if any(len(values[name]) != event_count for name in COMPONENTS):
        raise AssertionError("component lengths diverged")
    if any(len(set(values[name])) <= 1 for name in COMPONENTS):
        raise ValueError("constant tensor component found")
    return values


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(path: Path) -> None:
    values = parse_source(path)
    count = len(values["mrr"])
    print(f"semantic_validation=ok events={count} tensor_values={count * 6}")


def build(source: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    values = parse_source(source)
    event_count = len(values["mrr"])
    primary_bytes = event_count * len(COMPONENTS) * 8
    if primary_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {primary_bytes}")

    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for component in COMPONENTS:
        component_dir = samples_dir / f"globalcmt_{component}_f64"
        component_dir.mkdir()
        output = component_dir / f"globalcmt_{component}_f64_n{event_count:07d}.bin"
        with output.open("wb") as handle:
            for value in values[component]:
                handle.write(struct.pack("<d", value))
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": f"globalcmt_{component}_f64",
                "role": "primary",
                "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": output.stat().st_size,
                "value_count": event_count,
                "sample_format": "raw homogeneous float64 moment tensor component series",
                "sample_geometry": "event_series",
                "sample_rank": 1,
                "sample_shape": [event_count],
                "sample_axes": ["earthquake_event"],
                "natural_record_kind": "globalcmt_tensor_component_event_series",
                "source_field": component.upper(),
                "source_sample": source.name,
            }
        )

    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "source_file": source.name,
        "source_bytes": source.stat().st_size,
        "source_sha256": source_sha256(source),
        "event_count": event_count,
        "sample_count": len(rows),
        "primary_values": event_count * len(rows),
        "primary_bytes": primary_bytes,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built events={event_count} samples={len(rows)} "
        f"primary_values={stats['primary_values']} primary_bytes={primary_bytes}"
    )


def verify(source: Path, index_path: Path, data_root: Path) -> None:
    expected = parse_source(source)
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != len(COMPONENTS):
        raise ValueError(f"expected six indexed samples, found {len(rows)}")

    counts = []
    total_bytes = 0
    seen = set()
    for row in rows:
        if row.get("dataset_id") != DATASET_ID:
            raise ValueError("index contains another dataset ID")
        if row.get("role") != "primary":
            raise ValueError("index contains non-primary row")
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 64:
            raise ValueError("index row is not float64")
        component = str(row.get("source_field", "")).lower()
        if component not in COMPONENTS or component in seen:
            raise ValueError(f"unexpected or duplicate component {component!r}")
        seen.add(component)
        count = int(row["value_count"])
        if count != len(expected[component]):
            raise ValueError(f"wrong value count for {component}: {count}")
        sample = data_root / row["sample_path"]
        payload = sample.read_bytes()
        if len(payload) != count * 8 or len(payload) != row["sample_size_bytes"]:
            raise ValueError(f"size mismatch for {component}")
        actual = [item[0] for item in struct.iter_unpack("<d", payload)]
        if actual != expected[component]:
            raise ValueError(f"source-to-output mismatch for {component}")
        counts.append(count)
        total_bytes += len(payload)

    median = statistics.median(counts)
    if median < MIN_MEDIAN_VALUES:
        raise ValueError(f"median sample below floor: {median}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} median={median:g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("source", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source", type=Path, required=True)
    build_parser.add_argument("--samples-dir", type=Path, required=True)
    build_parser.add_argument("--index", type=Path, required=True)
    build_parser.add_argument("--stats", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source", type=Path, required=True)
    verify_parser.add_argument("--index", type=Path, required=True)
    verify_parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.source)
    elif args.command == "build":
        build(args.source, args.samples_dir, args.index, args.stats)
    else:
        verify(args.source, args.index, args.data_root)


if __name__ == "__main__":
    main()
