#!/usr/bin/env python3
"""Build and independently check deterministic Nanopore sample metadata."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


DATASET_ID = "zenodo_nanopore_slow5_i16"
SERIES_ID = "nanopore_raw_signal_i16"
SOURCE_NAME = "SIRV_from_MNXKXX240359.blow5"
SOURCE_SHA256 = "8d1e9caa3712780283fb66609268027e837992de0ba7e106a7a6061f72b34e4a"
BYTE_CAP = 900_000_000
MIN_PRIMARY_BYTES = 64 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict[str, object]]:
    expected = [
        "sequence", "read_id", "value_count", "sample_size_bytes", "minimum",
        "maximum", "zero_count", "transition_count", "sample_name",
    ]
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != expected:
            raise SystemExit("raw inventory TSV columns changed")
        rows: list[dict[str, object]] = []
        for raw in reader:
            rows.append({
                "sequence": int(raw["sequence"]),
                "read_id": raw["read_id"],
                "value_count": int(raw["value_count"]),
                "sample_size_bytes": int(raw["sample_size_bytes"]),
                "minimum": int(raw["minimum"]),
                "maximum": int(raw["maximum"]),
                "zero_count": int(raw["zero_count"]),
                "transition_count": int(raw["transition_count"]),
                "sample_name": raw["sample_name"],
            })
    if [row["sequence"] for row in rows] != list(range(1, len(rows) + 1)):
        raise SystemExit("raw inventory sequence is not contiguous")
    if len({row["read_id"] for row in rows}) != len(rows):
        raise SystemExit("duplicate BLOW5 read IDs in selected prefix")
    return rows


def collect(
    rows: list[dict[str, object]], samples_dir: Path, data_root: Path,
    source_path: Path, slow5tools_sha256: str, slow5lib_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if sha256_file(source_path) != SOURCE_SHA256:
        raise SystemExit("pinned BLOW5 source SHA256 mismatch")
    expected_names = {str(row["sample_name"]) for row in rows}
    actual_names = {path.name for path in samples_dir.iterdir() if path.is_file()}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)[:5]
        extra = sorted(actual_names - expected_names)[:5]
        raise SystemExit(f"sample inventory mismatch: missing={missing} extra={extra}")

    entries: list[dict[str, object]] = []
    hashes: set[str] = set()
    for row in rows:
        name = str(row["sample_name"])
        path = samples_dir / name
        size = path.stat().st_size
        value_count = int(row["value_count"])
        if size != int(row["sample_size_bytes"]) or size != value_count * 2:
            raise SystemExit(f"sample size mismatch: {name}")
        if value_count == 0 or int(row["minimum"]) >= int(row["maximum"]):
            raise SystemExit(f"empty or constant raw signal: {name}")
        if not 0 < int(row["transition_count"]) < value_count:
            raise SystemExit(f"invalid transition count: {name}")
        digest = sha256_file(path)
        if digest in hashes:
            raise SystemExit(f"duplicate complete raw-signal sample: {name}")
        hashes.add(digest)
        relative = path.relative_to(data_root).as_posix()
        entries.append({
            "bit_width": 16,
            "dataset_id": DATASET_ID,
            "element_size_bytes": 2,
            "endianness": "little",
            "maximum": int(row["maximum"]),
            "minimum": int(row["minimum"]),
            "natural_record_kind": "complete_nanopore_read_raw_signal",
            "numeric_kind": "int",
            "read_id": row["read_id"],
            "role": "primary",
            "sample_axes": ["adc_time_sample"],
            "sample_format": "raw homogeneous little-endian signed-int16 array",
            "sample_geometry": "variable_length_nanopore_read_signal_1d",
            "sample_path": relative,
            "sample_rank": 1,
            "sample_shape": [value_count],
            "sample_size_bytes": size,
            "semantic_field": "raw_ionic_current_adc_code",
            "series_id": SERIES_ID,
            "sha256": digest,
            "source_record_index": int(row["sequence"]) - 1,
            "source_sample": f"downloads/{DATASET_ID}/{SOURCE_NAME}",
            "transition_count": int(row["transition_count"]),
            "value_count": value_count,
            "zero_count": int(row["zero_count"]),
        })

    sizes = [int(row["sample_size_bytes"]) for row in rows]
    values = [int(row["value_count"]) for row in rows]
    total_bytes = sum(sizes)
    total_values = sum(values)
    if len(rows) < 2 or not MIN_PRIMARY_BYTES <= total_bytes <= BYTE_CAP:
        raise SystemExit("bounded prefix does not meet size policy")
    stats: dict[str, object] = {
        "byte_cap": BYTE_CAP,
        "dataset_id": DATASET_ID,
        "global_maximum": max(int(row["maximum"]) for row in rows),
        "global_minimum": min(int(row["minimum"]) for row in rows),
        "maximum_sample_bytes": max(sizes),
        "maximum_values_per_read": max(values),
        "median_sample_bytes": int(statistics.median(sizes)),
        "median_values_per_read": int(statistics.median(values)),
        "minimum_sample_bytes": min(sizes),
        "minimum_values_per_read": min(values),
        "primary_bytes": total_bytes,
        "primary_values": total_values,
        "records": len(rows),
        "selection": "longest source-order prefix of complete reads whose decoded int16 arrays fit within byte_cap",
        "series_id": SERIES_ID,
        "slow5lib_archive_sha256": slow5lib_sha256,
        "slow5tools_binary_sha256": slow5tools_sha256,
        "source_file": SOURCE_NAME,
        "source_sha256": SOURCE_SHA256,
        "total_transition_count": sum(int(row["transition_count"]) for row in rows),
        "total_zero_count": sum(int(row["zero_count"]) for row in rows),
    }
    return entries, stats


def write_jsonl(path: Path, entries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--raw-inventory", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--slow5tools-sha256", required=True)
    parser.add_argument("--slow5lib-sha256", required=True)
    args = parser.parse_args()

    rows = load_rows(args.raw_inventory)
    entries, stats = collect(
        rows, args.samples_dir, args.data_root, args.source,
        args.slow5tools_sha256, args.slow5lib_sha256,
    )
    if args.mode == "build":
        write_jsonl(args.index, entries)
        write_json(args.stats, stats)
    else:
        if read_jsonl(args.index) != entries:
            raise SystemExit("sample index differs from independently reconstructed metadata")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("ingest stats differ from independently reconstructed metadata")
    print(
        f"mode={args.mode} records={stats['records']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} median_values_per_read={stats['median_values_per_read']}"
    )


if __name__ == "__main__":
    main()
