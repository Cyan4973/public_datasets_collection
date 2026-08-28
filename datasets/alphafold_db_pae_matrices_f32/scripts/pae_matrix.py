#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct


DATASET_ID = "alphafold_db_pae_matrices_f32"
SERIES_ID = "protein_predicted_aligned_error_f32"
EXPECTED_SAMPLES = 15
EXPECTED_VALUES = 9_238_233
EXPECTED_BYTES = 36_952_932
EXPECTED_SOURCE_BYTES = 30_904_585
LICENSE_NAME = "alphafold_main-RMCDQW2G.js"
LICENSE_SIZE = 312_610
LICENSE_SHA256 = "f46325c8ef2d7e156a0f57db06f9be3e7b2eaee3579d63deb9b09033f0a9f1c9"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def load_sources(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    sources: list[dict[str, object]] = []
    for row in raw:
        sources.append(
            {
                **row,
                "version": int(row["version"]),
                "sequence_length": int(row["sequence_length"]),
                "source_bytes": int(row["source_bytes"]),
                "declared_maximum": float(row["declared_maximum"]),
            }
        )
    if len(sources) != EXPECTED_SAMPLES:
        raise ValueError(f"source count changed: {len(sources)}")
    if len({str(row["entry_id"]) for row in sources}) != len(sources):
        raise ValueError("duplicate entry IDs in source table")
    if sum(int(row["source_bytes"]) for row in sources) != EXPECTED_SOURCE_BYTES:
        raise ValueError("aggregate source bytes changed")
    values = sum(int(row["sequence_length"]) ** 2 for row in sources)
    if values != EXPECTED_VALUES:
        raise ValueError("aggregate matrix values changed")
    return sources


def source_filename(row: dict[str, object]) -> str:
    return (
        f"{row['ordinal']}_{row['entry_id']}_pae_v{row['version']}.json"
    )


def validate_license(download_dir: Path) -> None:
    path = download_dir / LICENSE_NAME
    if not path.is_file() or path.stat().st_size != LICENSE_SIZE or digest(path) != LICENSE_SHA256:
        raise ValueError("AlphaFold DB license evidence is missing or changed")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "CC-BY-4.0" not in text:
        raise ValueError("AlphaFold DB license evidence no longer contains CC-BY-4.0")


def parse_source(path: Path, row: dict[str, object]) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"missing source: {path.name}")
    if path.stat().st_size != int(row["source_bytes"]) or digest(path) != row["source_sha256"]:
        raise ValueError(f"source size or hash changed: {path.name}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise ValueError(f"unexpected PAE envelope: {path.name}")
    payload = document[0]
    matrix = payload.get("predicted_aligned_error")
    declared = payload.get("max_predicted_aligned_error")
    expected_declared = float(row["declared_maximum"])
    if isinstance(declared, bool) or not isinstance(declared, (int, float)):
        raise ValueError(f"invalid declared maximum: {path.name}")
    if not math.isclose(float(declared), expected_declared, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"declared maximum changed: {path.name}")
    length = int(row["sequence_length"])
    if not isinstance(matrix, list) or len(matrix) != length:
        raise ValueError(f"matrix row count changed: {path.name}")

    output = bytearray(length * length * 4)
    offset = 0
    minimum = math.inf
    maximum = -math.inf
    diagonal_minimum = math.inf
    diagonal_maximum = -math.inf
    zero_count = 0
    ceiling_count = 0
    fractional_count = 0
    distinct: set[float] = set()
    for i, matrix_row in enumerate(matrix):
        if not isinstance(matrix_row, list) or len(matrix_row) != length:
            raise ValueError(f"matrix column count changed at row {i}: {path.name}")
        for j, source_value in enumerate(matrix_row):
            if isinstance(source_value, bool) or not isinstance(source_value, (int, float)):
                raise ValueError(f"nonnumeric value at [{i},{j}]: {path.name}")
            value = float(source_value)
            exact_ceiling = (
                value > expected_declared + 1e-6
                and value == float(math.ceil(expected_declared))
                and value.is_integer()
            )
            if not math.isfinite(value) or value < 0 or (
                value > expected_declared + 1e-6 and not exact_ceiling
            ):
                raise ValueError(f"out-of-range value at [{i},{j}]: {path.name}")
            struct.pack_into("<f", output, offset, value)
            rounded = struct.unpack_from("<f", output, offset)[0]
            offset += 4
            if not math.isfinite(rounded):
                raise ValueError(f"float32 overflow: {path.name}")
            minimum = min(minimum, rounded)
            maximum = max(maximum, rounded)
            distinct.add(rounded)
            zero_count += rounded == 0.0
            ceiling_count += exact_ceiling
            fractional_count += not value.is_integer()
            if i == j:
                diagonal_minimum = min(diagonal_minimum, rounded)
                diagonal_maximum = max(diagonal_maximum, rounded)
    if len(distinct) < 8 or minimum == maximum:
        raise ValueError(f"degenerate PAE matrix: {path.name}")
    asymmetric_pairs = sum(
        float(matrix[i][j]) != float(matrix[j][i])
        for i in range(length)
        for j in range(i)
    )
    data = bytes(output)
    return {
        "data": data,
        "minimum": minimum,
        "maximum": maximum,
        "diagonal_minimum": diagonal_minimum,
        "diagonal_maximum": diagonal_maximum,
        "zero_count": zero_count,
        "declared_ceiling_count": ceiling_count,
        "fractional_source_value_count": fractional_count,
        "distinct_values": len(distinct),
        "asymmetric_lower_triangle_pairs": asymmetric_pairs,
        "sample_sha256": hashlib.sha256(data).hexdigest(),
    }


def materialize(
    sources_path: Path, download_dir: Path
) -> tuple[list[dict[str, object]], dict[str, object], list[tuple[str, bytes]]]:
    sources = load_sources(sources_path)
    validate_license(download_dir)
    rows: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    outputs: list[tuple[str, bytes]] = []
    seen_hashes: set[str] = set()
    for source in sources:
        source_name = source_filename(source)
        parsed = parse_source(download_dir / source_name, source)
        filename = f"{source['ordinal']}_{source['entry_id']}_pae_f32le.bin"
        data = bytes(parsed["data"])
        sample_hash = str(parsed["sample_sha256"])
        if sample_hash in seen_hashes:
            raise ValueError(f"duplicate PAE output: {source['entry_id']}")
        seen_hashes.add(sample_hash)
        length = int(source["sequence_length"])
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{filename}",
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(data),
            "value_count": length * length,
            "sample_format": "raw homogeneous IEEE-754 float32 PAE matrix",
            "sample_geometry": "protein_residue_pairwise_error_matrix_2d",
            "sample_rank": 2,
            "sample_shape": [length, length],
            "sample_axes": ["scored_residue_i", "alignment_residue_j"],
            "natural_record_kind": "complete_alphafold_protein_pae_matrix",
            "source_sample": f"downloads/{DATASET_ID}/{source_name}",
            "source_sha256": source["source_sha256"],
            "accession": source["accession"],
            "entry_id": source["entry_id"],
            "model_version": source["version"],
            "sequence_length": length,
            "declared_maximum": source["declared_maximum"],
            "minimum_f32": parsed["minimum"],
            "maximum_f32": parsed["maximum"],
            "diagonal_minimum_f32": parsed["diagonal_minimum"],
            "diagonal_maximum_f32": parsed["diagonal_maximum"],
            "zero_count": parsed["zero_count"],
            "declared_ceiling_count": parsed["declared_ceiling_count"],
            "fractional_source_value_count": parsed["fractional_source_value_count"],
            "distinct_values": parsed["distinct_values"],
            "asymmetric_lower_triangle_pairs": parsed["asymmetric_lower_triangle_pairs"],
            "sha256": sample_hash,
        }
        rows.append(row)
        outputs.append((filename, data))
        records.append(
            {
                "accession": source["accession"],
                "entry_id": source["entry_id"],
                "model_version": source["version"],
                "sequence_length": length,
                "source_file": source_name,
                "source_bytes": source["source_bytes"],
                "source_sha256": source["source_sha256"],
                "sample_bytes": len(data),
                "sample_sha256": sample_hash,
                "distinct_values": parsed["distinct_values"],
                "asymmetric_lower_triangle_pairs": parsed["asymmetric_lower_triangle_pairs"],
            }
        )
    counts = sorted(int(row["value_count"]) for row in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "samples": len(rows),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "source_bytes": sum(int(record["source_bytes"]) for record in records),
        "median_value_count": statistics.median(counts),
        "min_value_count": counts[0],
        "max_value_count": counts[-1],
        "model_versions": {
            str(version): sum(int(row["model_version"]) == version for row in rows)
            for version in sorted({int(row["model_version"]) for row in rows})
        },
        "records": records,
    }
    if (
        len(rows) != EXPECTED_SAMPLES
        or stats["primary_values"] != EXPECTED_VALUES
        or stats["primary_sample_bytes"] != EXPECTED_BYTES
        or stats["source_bytes"] != EXPECTED_SOURCE_BYTES
    ):
        raise ValueError("aggregate PAE totals changed")
    return rows, stats, outputs


def command_build(args: argparse.Namespace) -> None:
    rows, stats, outputs = materialize(Path(args.sources), Path(args.download_dir))
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    out_dir = samples_dir / SERIES_ID
    out_dir.mkdir(parents=True)
    for filename, data in outputs:
        (out_dir / filename).write_bytes(data)
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(rows)} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_sample_bytes']} median_values={stats['median_value_count']}"
    )


def command_validate(args: argparse.Namespace) -> None:
    rows, stats, _ = materialize(Path(args.sources), Path(args.download_dir))
    print(
        f"validated dataset={DATASET_ID} samples={len(rows)} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}"
    )


def command_verify(args: argparse.Namespace) -> None:
    rows, stats, outputs = materialize(Path(args.sources), Path(args.download_dir))
    actual_rows = [
        json.loads(line)
        for line in Path(args.index).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actual_stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if actual_rows != rows:
        raise ValueError("sample index differs from independent source decode")
    if actual_stats != stats:
        raise ValueError("ingest stats differ from independent source decode")
    out_dir = Path(args.samples_dir) / SERIES_ID
    expected_files = {filename for filename, _ in outputs}
    actual_files = {path.name for path in out_dir.glob("*.bin")}
    if actual_files != expected_files:
        raise ValueError("sample file inventory mismatch")
    for filename, expected in outputs:
        actual = (out_dir / filename).read_bytes()
        if actual != expected:
            raise ValueError(f"source/output byte mismatch: {filename}")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--sources", required=True)
    validate.add_argument("--download-dir", required=True)
    validate.set_defaults(func=command_validate)
    for name, function in (("build", command_build), ("verify", command_verify)):
        command = commands.add_parser(name)
        command.add_argument("--sources", required=True)
        command.add_argument("--download-dir", required=True)
        command.add_argument("--samples-dir", required=True)
        command.add_argument("--index", required=True)
        command.add_argument("--stats", required=True)
        command.set_defaults(func=function)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
