#!/usr/bin/env python3
"""Stream and characterize the reduced TrackML collision-event CSV."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import struct
import tarfile


MEMBER = "trackml_40k-events-10-to-50-tracks.csv"
HEADER = (
    "x", "y", "z", "volume_id", "vx", "vy", "vz", "px", "py", "pz",
    "q", "particle_id", "weight", "event_id",
)
FLOAT_FIELDS = ("x", "y", "z", "vx", "vy", "vz", "px", "py", "pz", "weight")
FLOAT_INDICES = tuple(HEADER.index(name) for name in FLOAT_FIELDS)


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    event_rows: list[dict[str, object]] = []
    event_hashes: set[str] = set()
    duplicate_event_payloads = 0
    global_hash = hashlib.sha256()
    minima = [math.inf] * len(FLOAT_FIELDS)
    maxima = [-math.inf] * len(FLOAT_FIELDS)
    zero_counts = [0] * len(FLOAT_FIELDS)
    negative_counts = [0] * len(FLOAT_FIELDS)
    volume_ids: set[int] = set()
    charge_values: set[int] = set()
    row_count = 0
    current_event: int | None = None
    current_rows = 0
    current_particles: set[int] = set()
    current_hash = hashlib.sha256()
    previous_event: int | None = None
    event_id_gaps: list[dict[str, int]] = []

    def finish_event() -> None:
        nonlocal duplicate_event_payloads, current_rows, current_particles, current_hash
        if current_event is None:
            return
        digest = current_hash.hexdigest()
        if digest in event_hashes:
            duplicate_event_payloads += 1
        event_hashes.add(digest)
        event_rows.append({
            "event_id": current_event,
            "hit_count": current_rows,
            "float_value_count": current_rows * len(FLOAT_FIELDS),
            "sample_size_bytes": current_rows * len(FLOAT_FIELDS) * 4,
            "particle_count": len(current_particles),
            "sample_sha256": digest,
        })
        current_rows = 0
        current_particles = set()
        current_hash = hashlib.sha256()

    with tarfile.open(args.archive, mode="r:gz") as archive:
        for member in archive:
            if member.name != MEMBER:
                continue
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit("cannot open TrackML CSV member")
            text_source = io.TextIOWrapper(source, encoding="utf-8", newline="")
            reader = csv.reader(text_source)
            try:
                actual_header = tuple(next(reader))
            except StopIteration:
                raise SystemExit("TrackML CSV is empty")
            if actual_header != HEADER:
                raise SystemExit(f"unexpected CSV header: {actual_header!r}")

            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(HEADER):
                    raise SystemExit(f"line {line_number}: expected {len(HEADER)} columns")
                try:
                    event_id = int(row[13])
                    volume_id = int(row[3])
                    charge = int(row[10])
                    particle_id = int(row[11])
                    source_values = [float(row[index]) for index in FLOAT_INDICES]
                except ValueError as error:
                    raise SystemExit(f"line {line_number}: invalid numeric value: {error}")
                if not all(math.isfinite(value) for value in source_values):
                    raise SystemExit(f"line {line_number}: non-finite float value")

                if current_event is None:
                    current_event = event_id
                elif event_id != current_event:
                    if event_id <= current_event:
                        raise SystemExit(f"line {line_number}: event IDs are not strictly grouped")
                    finish_event()
                    previous_event = current_event
                    current_event = event_id
                    if previous_event is not None and event_id != previous_event + 1:
                        event_id_gaps.append({
                            "after_event_id": previous_event,
                            "before_event_id": event_id,
                            "missing_event_count": event_id - previous_event - 1,
                        })

                packed = struct.pack("<10f", *source_values)
                rounded = struct.unpack("<10f", packed)
                if not all(math.isfinite(value) for value in rounded):
                    raise SystemExit(f"line {line_number}: float32 conversion became non-finite")
                current_hash.update(packed)
                global_hash.update(packed)
                current_rows += 1
                current_particles.add(particle_id)
                volume_ids.add(volume_id)
                charge_values.add(charge)
                row_count += 1
                for index, value in enumerate(rounded):
                    minima[index] = min(minima[index], value)
                    maxima[index] = max(maxima[index], value)
                    zero_counts[index] += value == 0.0
                    negative_counts[index] += value < 0.0
            finish_event()
            break
        else:
            raise SystemExit(f"archive lacks expected member {MEMBER!r}")

    hit_counts = [int(row["hit_count"]) for row in event_rows]
    value_counts = [int(row["float_value_count"]) for row in event_rows]
    particle_counts = [int(row["particle_count"]) for row in event_rows]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    event_path = args.output_dir / "event_profile.tsv"
    with event_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "event_id", "hit_count", "float_value_count", "sample_size_bytes",
                "particle_count", "sample_sha256",
            ),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(event_rows)

    fields = {
        name: {
            "min_f32": minima[index],
            "max_f32": maxima[index],
            "zero_count": zero_counts[index],
            "negative_count": negative_counts[index],
        }
        for index, name in enumerate(FLOAT_FIELDS)
    }
    summary = {
        "member": MEMBER,
        "schema": list(HEADER),
        "primary_float_fields": list(FLOAT_FIELDS),
        "source_representation": "decimal CSV",
        "output_representation": "derived little-endian IEEE-754 float32",
        "row_count": row_count,
        "event_count": len(event_rows),
        "event_id_min": int(event_rows[0]["event_id"]),
        "event_id_max": int(event_rows[-1]["event_id"]),
        "event_id_gaps": event_id_gaps,
        "missing_event_id_count": sum(gap["missing_event_count"] for gap in event_id_gaps),
        "hit_count": {
            "min": min(hit_counts),
            "median": statistics.median(hit_counts),
            "p95": percentile(hit_counts, 0.95),
            "max": max(hit_counts),
        },
        "float_values_per_event": {
            "min": min(value_counts),
            "median": statistics.median(value_counts),
            "p95": percentile(value_counts, 0.95),
            "max": max(value_counts),
        },
        "particles_per_event": {
            "min": min(particle_counts),
            "median": statistics.median(particle_counts),
            "p95": percentile(particle_counts, 0.95),
            "max": max(particle_counts),
        },
        "total_float_values": row_count * len(FLOAT_FIELDS),
        "total_output_bytes": row_count * len(FLOAT_FIELDS) * 4,
        "duplicate_event_payloads": duplicate_event_payloads,
        "volume_ids": sorted(volume_ids),
        "charge_values": sorted(charge_values),
        "fields": fields,
        "concatenated_event_payload_sha256": global_hash.hexdigest(),
    }
    (args.output_dir / "numeric_profile.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"events={event_path}")


if __name__ == "__main__":
    main()
