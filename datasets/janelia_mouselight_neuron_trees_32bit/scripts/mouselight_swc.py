#!/usr/bin/env python3
from __future__ import annotations

import argparse
from array import array
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import sys
from typing import Any


DATASET_ID = "janelia_mouselight_neuron_trees_32bit"
EXPECTED_SOURCE_COUNT = 320
EXPECTED_SOURCE_BYTES = 108_215_773
EXPECTED_NODE_COUNT = 1_947_050
EXPECTED_SAMPLE_COUNT = 1_280
EXPECTED_VALUE_COUNT = 7_788_200
EXPECTED_OUTPUT_BYTES = 31_152_800
EXPECTED_AGGREGATE_SHA256 = "13735f2ceb37b9a0b72e6c98b92961b06b47b7c76485b79fb839ae38d631b9b9"
FIELDS = ("x", "y", "z", "parent")


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def f32_bytes(values: list[float]) -> bytes:
    output = array("f", values)
    if output.itemsize != 4:
        raise RuntimeError("platform float array item size is not four bytes")
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


def i32_bytes(values: list[int]) -> bytes:
    output = array("i", values)
    if output.itemsize != 4:
        raise RuntimeError("platform signed-int array item size is not four bytes")
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


def read_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "kind", "key", "filename", "size_bytes", "md5", "sha256",
        "last_modified", "url",
    }
    if not rows or set(rows[0]) != required:
        raise RuntimeError("sources.tsv has unexpected columns or is empty")
    if len(rows) != EXPECTED_SOURCE_COUNT:
        raise RuntimeError(f"expected {EXPECTED_SOURCE_COUNT} sources, found {len(rows)}")
    if sum(int(row["size_bytes"]) for row in rows) != EXPECTED_SOURCE_BYTES:
        raise RuntimeError("source-byte total changed")
    if len({row["key"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate source key")
    if len({row["filename"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate local filename")
    return rows


def parse_swc(path: Path) -> dict[str, Any]:
    node_ids: list[int] = []
    node_types: list[int] = []
    parents: list[int] = []
    coordinates: dict[str, list[float]] = {name: [] for name in ("x", "y", "z")}
    radii: list[float] = []
    comments = 0

    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                comments += 1
                continue
            columns = line.split()
            if len(columns) != 7:
                raise RuntimeError(f"{path.name}:{line_number}: expected seven SWC columns")
            try:
                node_id = int(columns[0])
                node_type = int(columns[1])
                x, y, z, radius = (float(value) for value in columns[2:6])
                parent = int(columns[6])
            except ValueError as error:
                raise RuntimeError(f"{path.name}:{line_number}: malformed numeric row") from error
            if node_id <= 0:
                raise RuntimeError(f"{path.name}:{line_number}: nonpositive node ID")
            if node_type < 0:
                raise RuntimeError(f"{path.name}:{line_number}: negative node type")
            if not all(math.isfinite(value) for value in (x, y, z, radius)):
                raise RuntimeError(f"{path.name}:{line_number}: non-finite field")
            if radius < 0:
                raise RuntimeError(f"{path.name}:{line_number}: negative radius")
            node_ids.append(node_id)
            node_types.append(node_type)
            coordinates["x"].append(x)
            coordinates["y"].append(y)
            coordinates["z"].append(z)
            radii.append(radius)
            parents.append(parent)

    node_count = len(node_ids)
    if node_count < 900:
        raise RuntimeError(f"{path.name}: only {node_count} nodes")
    if node_ids != list(range(1, node_count + 1)):
        raise RuntimeError(f"{path.name}: node IDs are not exactly sequential from one")
    node_set = set(node_ids)
    roots = sum(parent == -1 for parent in parents)
    missing_parents = [parent for parent in parents if parent != -1 and parent not in node_set]
    self_parents = [node for node, parent in zip(node_ids, parents) if node == parent]
    forward_parents = [parent for node, parent in zip(node_ids, parents) if parent > node]
    if roots != 1 or missing_parents or self_parents or forward_parents:
        raise RuntimeError(
            f"{path.name}: invalid rooted tree roots={roots} "
            f"missing={len(missing_parents)} self={len(self_parents)} "
            f"forward={len(forward_parents)}"
        )

    payloads = {name: f32_bytes(values) for name, values in coordinates.items()}
    payloads["parent"] = i32_bytes(parents)
    for name in ("x", "y", "z"):
        words = array("f")
        words.frombytes(payloads[name])
        if sys.byteorder != "little":
            words.byteswap()
        if len(set(words)) < 2:
            raise RuntimeError(f"{path.name}: constant coordinate field {name}")
        if not all(math.isfinite(value) for value in words):
            raise RuntimeError(f"{path.name}: float32 conversion produced non-finite {name}")
    if len(set(parents)) < 2:
        raise RuntimeError(f"{path.name}: degenerate parent field")

    return {
        "node_count": node_count,
        "comment_lines": comments,
        "root_count": roots,
        "node_type_counts": dict(sorted((str(key), value) for key, value in __import__("collections").Counter(node_types).items())),
        "radius_distinct_values": len(set(radii)),
        "radius_minimum": min(radii),
        "radius_maximum": max(radii),
        "payloads": payloads,
    }


def series_id(kind: str, field: str) -> str:
    prefix = "mouselight_axon" if kind == "axon_consensus" else "mouselight_dendrite"
    suffix = "i32" if field == "parent" else "f32"
    return f"{prefix}_{field}_{suffix}"


def sample_filename(source_filename: str, field: str, node_count: int) -> str:
    stem = source_filename.removesuffix(".swc").lower()
    return f"{stem}__{field}_n{node_count:07d}.bin"


def source_identity(row: dict[str, str], source_path: Path) -> None:
    actual_size = source_path.stat().st_size
    if actual_size != int(row["size_bytes"]):
        raise RuntimeError(f"{source_path.name}: source size mismatch")
    if hash_file(source_path, "md5") != row["md5"]:
        raise RuntimeError(f"{source_path.name}: source MD5 mismatch")
    if hash_file(source_path, "sha256") != row["sha256"]:
        raise RuntimeError(f"{source_path.name}: source SHA-256 mismatch")


def generate(repo_root: Path, data_dir: str, sources_path: Path, write: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data_root = repo_root / data_dir
    source_dir = data_root / "downloads" / DATASET_ID / "swc"
    sample_root = data_root / "samples" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    sources = read_sources(sources_path)

    if write:
        shutil.rmtree(sample_root, ignore_errors=True)
        sample_root.mkdir(parents=True)
        index_dir.mkdir(parents=True, exist_ok=True)
        filtered_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    duplicate_guard: dict[str, set[str]] = {}
    series_counts: dict[str, dict[str, int]] = {}

    for source in sources:
        source_path = source_dir / source["filename"]
        if not source_path.is_file():
            raise RuntimeError(f"missing source: {source_path}")
        source_identity(source, source_path)
        parsed = parse_swc(source_path)
        source_stats.append({
            "kind": source["kind"],
            "key": source["key"],
            "filename": source["filename"],
            "source_size_bytes": int(source["size_bytes"]),
            "source_sha256": source["sha256"],
            "node_count": parsed["node_count"],
            "comment_lines": parsed["comment_lines"],
            "root_count": parsed["root_count"],
            "node_type_counts": parsed["node_type_counts"],
            "radius_distinct_values": parsed["radius_distinct_values"],
            "radius_minimum": parsed["radius_minimum"],
            "radius_maximum": parsed["radius_maximum"],
        })

        for field in FIELDS:
            payload = parsed["payloads"][field]
            sid = series_id(source["kind"], field)
            digest = hash_bytes(payload)
            seen = duplicate_guard.setdefault(sid, set())
            if digest in seen:
                raise RuntimeError(f"duplicate payload in {sid}: {source['filename']}")
            seen.add(digest)
            aggregate.update(payload)
            output_rel = Path("samples") / DATASET_ID / sid / sample_filename(
                source["filename"], field, parsed["node_count"]
            )
            output_path = data_root / output_rel
            if write:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(payload)
            elif not output_path.is_file() or output_path.read_bytes() != payload:
                raise RuntimeError(f"output mismatch: {output_path}")

            kind = "int" if field == "parent" else "float"
            record = {
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "role": "primary",
                "numeric_kind": kind,
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_format": (
                    "raw homogeneous little-endian int32 SWC parent-reference array"
                    if field == "parent"
                    else f"raw homogeneous little-endian float32 SWC {field}-coordinate array"
                ),
                "sample_geometry": "rooted_neuron_tree_node_attribute_1d",
                "sample_rank": 1,
                "sample_axes": ["swc_node_order"],
                "sample_shape": [parsed["node_count"]],
                "natural_record_kind": f"complete_mouselight_{source['kind']}_{field}_field",
                "source_sample": f"downloads/{DATASET_ID}/swc/{source['filename']}",
                "source_url": source["url"],
                "source_key": source["key"],
                "source_kind": source["kind"],
                "source_field": field,
                "value_count": parsed["node_count"],
                "sample_size_bytes": len(payload),
                "sha256": digest,
                "sample_path": output_rel.as_posix(),
            }
            records.append(record)
            totals = series_counts.setdefault(sid, {"samples": 0, "values": 0, "bytes": 0})
            totals["samples"] += 1
            totals["values"] += parsed["node_count"]
            totals["bytes"] += len(payload)

    sample_lengths = [int(record["value_count"]) for record in records]
    summary = {
        "dataset_id": DATASET_ID,
        "license": "CC-BY-4.0",
        "source_count": len(sources),
        "source_size_bytes": sum(int(row["size_bytes"]) for row in sources),
        "sample_count": len(records),
        "value_count": sum(sample_lengths),
        "total_size_bytes": sum(int(record["sample_size_bytes"]) for record in records),
        "minimum_sample_values": min(sample_lengths),
        "median_sample_values": statistics.median(sample_lengths),
        "maximum_sample_values": max(sample_lengths),
        "aggregate_sha256": aggregate.hexdigest(),
        "series": series_counts,
        "sources": source_stats,
    }
    if sum(row["node_count"] for row in source_stats) != EXPECTED_NODE_COUNT:
        raise RuntimeError("aggregate source node count changed")
    if summary["sample_count"] != EXPECTED_SAMPLE_COUNT:
        raise RuntimeError("sample count changed")
    if summary["value_count"] != EXPECTED_VALUE_COUNT:
        raise RuntimeError("aggregate value count changed")
    if summary["total_size_bytes"] != EXPECTED_OUTPUT_BYTES:
        raise RuntimeError("aggregate output size changed")
    if EXPECTED_AGGREGATE_SHA256 and summary["aggregate_sha256"] != EXPECTED_AGGREGATE_SHA256:
        raise RuntimeError("aggregate output SHA-256 changed")
    return records, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--sources", type=Path, required=True)
    args = parser.parse_args()

    data_root = args.repo_root / args.data_dir
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    summary_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    records, summary = generate(args.repo_root, args.data_dir, args.sources, args.mode == "build")

    if args.mode == "build":
        index_path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"built_sources={summary['source_count']} samples={summary['sample_count']} "
            f"values={summary['value_count']} bytes={summary['total_size_bytes']}"
        )
        return

    if not index_path.is_file() or not summary_path.is_file():
        raise RuntimeError("build outputs are missing")
    existing_records = [
        json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if existing_records != records:
        raise RuntimeError("sample index differs from fresh source-derived records")
    if existing_summary != summary:
        raise RuntimeError("ingest statistics differ from fresh source-derived statistics")
    print(
        f"verified_sources={summary['source_count']} samples={summary['sample_count']} "
        f"values={summary['value_count']} bytes={summary['total_size_bytes']}"
    )


if __name__ == "__main__":
    main()
