#!/usr/bin/env python3
"""Decode pinned wwPDB structure-factor reflection columns to float32."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct


DATASET_ID = "wwpdb_structure_factors_f32"
FIELDS = {
    "_refln.F_meas_au": {
        "series_id": "wwpdb_measured_structure_factor_amplitude_f32",
        "slug": "f_meas_au",
        "kind": "amplitude",
        "numeric_kind": "float",
    },
    "_refln.F_meas_sigma_au": {
        "series_id": "wwpdb_measured_structure_factor_uncertainty_f32",
        "slug": "f_meas_sigma_au",
        "kind": "uncertainty",
        "numeric_kind": "float",
    },
}
REQUIRED_TAGS = {
    "_refln.index_h",
    "_refln.index_k",
    "_refln.index_l",
    "_refln.F_meas_au",
}
EXPECTED_TOTAL_VALUES = 4_295_467
EXPECTED_TOTAL_BYTES = EXPECTED_TOTAL_VALUES * 4
EXPECTED_AGGREGATE_SHA256 = "16117e7501951c33722da0816b79e94f81c90d135e3bbf74ec082a9f4d03c5f8"
MIN_SAMPLE_VALUES = 1_000


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selection(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "pdb_id", "url", "filename", "size_bytes", "md5", "sha256",
        "reflection_rows", "amplitude_values", "sigma_values",
    }
    if len(raw) != 5 or not raw or not required.issubset(raw[0]):
        raise SystemExit("selection count or schema changed")
    rows = []
    for source in raw:
        rows.append({
            **source,
            "size_bytes": int(source["size_bytes"]),
            "reflection_rows": int(source["reflection_rows"]),
            "amplitude_values": int(source["amplitude_values"]),
            "sigma_values": int(source["sigma_values"]),
        })
    if [row["pdb_id"] for row in rows] != ["1AON", "1FFK", "1J5E", "2PTC", "4V9D"]:
        raise SystemExit("selection order changed")
    return rows


def validate_source(path: Path, row: dict[str, object]) -> None:
    if not path.is_file() or path.stat().st_size != row["size_bytes"]:
        raise SystemExit(f"{row['pdb_id']}: missing source or size mismatch")
    if file_hash(path, "md5") != row["md5"] or file_hash(path) != row["sha256"]:
        raise SystemExit(f"{row['pdb_id']}: source hash mismatch")
    try:
        with gzip.open(path, "rb") as handle:
            if not handle.read(64).startswith(b"data_"):
                raise ValueError("decompressed content does not start with an mmCIF data block")
    except (OSError, EOFError, ValueError) as error:
        raise SystemExit(f"{row['pdb_id']}: invalid gzip/mmCIF source: {error}") from error


def float32_bytes(token: str, field: str) -> tuple[bytes, float]:
    try:
        value = float(token)
        packed = struct.pack("<f", value)
        rounded = struct.unpack("<f", packed)[0]
    except (ValueError, OverflowError, struct.error) as error:
        raise ValueError(f"invalid {field} token: {token!r}") from error
    if not math.isfinite(value) or not math.isfinite(rounded) or value < 0.0:
        raise ValueError(f"non-finite, overflowing, or negative {field}: {token!r}")
    return packed, rounded


def parse_reflection_loop(path: Path) -> dict[str, object]:
    payloads = {tag: bytearray() for tag in FIELDS}
    minimum = {tag: math.inf for tag in FIELDS}
    maximum = {tag: -math.inf for tag in FIELDS}
    zero_count = {tag: 0 for tag in FIELDS}
    missing_count = {tag: 0 for tag in FIELDS}
    reflection_rows = 0
    hkl_min = [2**31 - 1] * 3
    hkl_max = [-(2**31)] * 3
    refln_loops = 0
    pending: str | None = None

    with gzip.open(path, "rt", encoding="utf-8", errors="strict") as handle:
        while True:
            line = pending if pending is not None else handle.readline()
            pending = None
            if not line:
                break
            if line.strip() != "loop_":
                continue

            tags = []
            while True:
                line = handle.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("_"):
                    tags.append(stripped.split()[0])
                    continue
                break
            if not tags:
                continue

            is_reflection_loop = any(tag.startswith("_refln.") for tag in tags)
            positions = {tag: index for index, tag in enumerate(tags)}
            if is_reflection_loop:
                refln_loops += 1
                if not REQUIRED_TAGS.issubset(positions):
                    raise ValueError(
                        f"reflection loop lacks required tags: {sorted(REQUIRED_TAGS - positions.keys())}"
                    )
            buffered_tokens: list[str] = []

            while line:
                stripped = line.strip()
                if (
                    not stripped
                    or stripped.startswith("#")
                    or stripped == "loop_"
                    or stripped.startswith("_")
                    or stripped.startswith("data_")
                ):
                    if stripped and not stripped.startswith("#"):
                        pending = line
                    break
                if is_reflection_loop:
                    if stripped.startswith(";") or "'" in stripped or '"' in stripped:
                        raise ValueError("quoted or multiline value in numeric reflection loop")
                    buffered_tokens.extend(stripped.split())
                    while len(buffered_tokens) >= len(tags):
                        current = buffered_tokens[:len(tags)]
                        del buffered_tokens[:len(tags)]
                        try:
                            hkl = [
                                int(current[positions["_refln.index_h"]]),
                                int(current[positions["_refln.index_k"]]),
                                int(current[positions["_refln.index_l"]]),
                            ]
                        except (ValueError, IndexError) as error:
                            raise ValueError(f"invalid Miller-index row: {current}") from error
                        for axis, value in enumerate(hkl):
                            if not -(2**31) <= value < 2**31:
                                raise ValueError("Miller index exceeds signed int32")
                            hkl_min[axis] = min(hkl_min[axis], value)
                            hkl_max[axis] = max(hkl_max[axis], value)
                        reflection_rows += 1
                        for tag in ("_refln.F_meas_au", "_refln.F_meas_sigma_au"):
                            if tag not in positions:
                                continue
                            token = current[positions[tag]]
                            if token in {".", "?"}:
                                missing_count[tag] += 1
                                continue
                            packed, rounded = float32_bytes(token, tag)
                            payloads[tag].extend(packed)
                            minimum[tag] = min(minimum[tag], rounded)
                            maximum[tag] = max(maximum[tag], rounded)
                            zero_count[tag] += int(rounded == 0.0)
                line = handle.readline()
            if is_reflection_loop and buffered_tokens:
                raise ValueError(
                    f"partial reflection row: {len(buffered_tokens)} of {len(tags)} tokens"
                )

    if refln_loops != 1:
        raise ValueError(f"expected one `_refln` loop, found {refln_loops}")
    profiles = {}
    for tag, payload in payloads.items():
        if not payload:
            continue
        count = len(payload) // 4
        if count < MIN_SAMPLE_VALUES or minimum[tag] == maximum[tag]:
            raise ValueError(f"{tag}: undersized or constant output")
        profiles[tag] = {
            "value_count": count,
            "sample_size_bytes": len(payload),
            "missing_count": missing_count[tag],
            "zero_count": zero_count[tag],
            "minimum": minimum[tag],
            "maximum": maximum[tag],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "payload": bytes(payload),
        }
    return {
        "reflection_rows": reflection_rows,
        "miller_index_min": hkl_min,
        "miller_index_max": hkl_max,
        "profiles": profiles,
    }


def scan_sources(selection_path: Path, download_dir: Path, consumer=None) -> dict[str, object]:
    selections = load_selection(selection_path)
    samples = []
    seen_hashes = set()
    aggregate = hashlib.sha256()
    for row in selections:
        source = download_dir / "sf" / str(row["filename"])
        validate_source(source, row)
        try:
            parsed = parse_reflection_loop(source)
        except ValueError as error:
            raise SystemExit(f"{row['pdb_id']}: {error}") from error
        if parsed["reflection_rows"] != row["reflection_rows"]:
            raise SystemExit(f"{row['pdb_id']}: reflection-row count changed")
        actual_amplitude = parsed["profiles"].get("_refln.F_meas_au", {}).get("value_count", 0)
        actual_sigma = parsed["profiles"].get("_refln.F_meas_sigma_au", {}).get("value_count", 0)
        if actual_amplitude != row["amplitude_values"] or actual_sigma != row["sigma_values"]:
            raise SystemExit(f"{row['pdb_id']}: selected field counts changed")
        for tag, config in FIELDS.items():
            profile = parsed["profiles"].get(tag)
            if profile is None:
                continue
            digest = str(profile["sha256"])
            if digest in seen_hashes:
                raise SystemExit(f"duplicate field payload: {row['pdb_id']} {tag}")
            seen_hashes.add(digest)
            aggregate.update(profile["payload"])
            sample = {
                "pdb_id": row["pdb_id"],
                "source_url": row["url"],
                "source_filename": row["filename"],
                "source_field": tag,
                "series_id": config["series_id"],
                "field_kind": config["kind"],
                "reflection_rows": parsed["reflection_rows"],
                "miller_index_min": parsed["miller_index_min"],
                "miller_index_max": parsed["miller_index_max"],
                **{key: value for key, value in profile.items() if key != "payload"},
            }
            samples.append(sample)
            if consumer is not None:
                consumer(row, tag, config, profile["payload"], sample)

    result = {
        "dataset_id": DATASET_ID,
        "license": "CC0-1.0",
        "source_count": len(selections),
        "sample_count": len(samples),
        "value_count": sum(int(sample["value_count"]) for sample in samples),
        "total_size_bytes": sum(int(sample["sample_size_bytes"]) for sample in samples),
        "aggregate_sha256": aggregate.hexdigest(),
        "samples": samples,
    }
    if result["sample_count"] != 9:
        raise SystemExit(f"sample count changed: {result['sample_count']}")
    if result["value_count"] != EXPECTED_TOTAL_VALUES or result["total_size_bytes"] != EXPECTED_TOTAL_BYTES:
        raise SystemExit("aggregate value or byte total changed")
    if result["aggregate_sha256"] != EXPECTED_AGGREGATE_SHA256:
        raise SystemExit("aggregate decoded-byte SHA-256 changed")
    return result


def command_build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    args.samples_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    rows = []

    def emit(row, tag, config, payload, profile):
        output_dir = args.samples_dir / config["series_id"]
        output_dir.mkdir(exist_ok=True)
        output = output_dir / f"{str(row['pdb_id']).lower()}_{config['slug']}_n{profile['value_count']:07d}.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": config["series_id"],
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": (args.download_dir / "sf" / str(row["filename"])).relative_to(args.data_root).as_posix(),
            "source_url": row["url"],
            "source_pdb_id": row["pdb_id"],
            "source_field": tag,
            "numeric_kind": config["numeric_kind"],
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_format": f"raw homogeneous little-endian {config['numeric_kind']}32 structure-factor {config['kind']} array",
            "sample_geometry": "sparse_reciprocal_lattice_reflection_attribute_1d",
            "sample_rank": 1,
            "sample_shape": [profile["value_count"]],
            "sample_axes": ["reflection_source_order"],
            "natural_record_kind": f"complete_wwpdb_crystal_reflection_{config['slug']}_field",
            "reflection_rows": profile["reflection_rows"],
            "missing_count": profile["missing_count"],
            "miller_index_min": profile["miller_index_min"],
            "miller_index_max": profile["miller_index_max"],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "zero_count": profile["zero_count"],
            "sha256": profile["sha256"],
        })

    stats = scan_sources(args.selection, args.download_dir, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built_samples={stats['sample_count']} values={stats['value_count']} "
        f"bytes={stats['total_size_bytes']}"
    )


def command_verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing sample index or ingest stats")
    indexed = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    stored_stats = json.loads(args.stats.read_text())
    cursor = 0
    expected_outputs = set()

    def compare(row, tag, config, payload, profile):
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than source fields")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": config["series_id"],
            "role": "primary",
            "source_pdb_id": row["pdb_id"],
            "source_field": tag,
            "numeric_kind": config["numeric_kind"],
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_shape": [profile["value_count"]],
            "reflection_rows": profile["reflection_rows"],
            "missing_count": profile["missing_count"],
            "miller_index_min": profile["miller_index_min"],
            "miller_index_max": profile["miller_index_max"],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "zero_count": profile["zero_count"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"sample index mismatch {row['pdb_id']} {tag}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh mmCIF extraction: {output}")
        expected_outputs.add(output.resolve())

    fresh = scan_sources(args.selection, args.download_dir, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if fresh != stored_stats:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(
        f"verified_samples={fresh['sample_count']} values={fresh['value_count']} "
        f"bytes={fresh['total_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        command_build(args)
    else:
        command_verify(args)


if __name__ == "__main__":
    main()
