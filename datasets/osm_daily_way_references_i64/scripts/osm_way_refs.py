#!/usr/bin/env python3
"""Stream OSM change XML and emit ordered way-node references as int64."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
from typing import Callable
import xml.sax
from xml.sax import handler


DATASET_ID = "osm_daily_way_references_i64"
SERIES_ID = "osm_way_node_reference_i64"
MIN_SAMPLE_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MAX_PRIMARY_BYTES = 1_000_000_000
INT64_MAX = (1 << 63) - 1
REQUIRE_ABOVE = (1 << 32) - 1


@dataclass
class Metrics:
    way_count: int = 0
    value_count: int = 0
    minimum: int = INT64_MAX
    maximum: int = 0
    first: int | None = None
    previous: int | None = None
    nonconstant: bool = False
    repeated_adjacent: int = 0
    nondecreasing_adjacent: int = 0
    delta_count: int = 0

    def add_group(self, refs: list[int]) -> None:
        self.way_count += 1
        for ref in refs:
            if self.first is None:
                self.first = ref
            elif ref != self.first:
                self.nonconstant = True
            if self.previous is not None:
                delta = ref - self.previous
                self.repeated_adjacent += delta == 0
                self.nondecreasing_adjacent += delta >= 0
                self.delta_count += 1
            self.previous = ref
            self.minimum = min(self.minimum, ref)
            self.maximum = max(self.maximum, ref)
            self.value_count += 1

    def validate(self, source: Path) -> None:
        if self.value_count < MIN_SAMPLE_VALUES:
            raise ValueError(
                f"{source.name}: only {self.value_count} way references"
            )
        if not self.nonconstant:
            raise ValueError(f"{source.name}: constant way-reference stream")
        if self.maximum <= REQUIRE_ABOVE:
            raise ValueError(
                f"{source.name}: maximum ref {self.maximum} does not exceed uint32"
            )

    def as_dict(self) -> dict[str, int | float | bool]:
        return {
            "way_count": self.way_count,
            "value_count": self.value_count,
            "min": self.minimum,
            "max": self.maximum,
            "nonconstant": self.nonconstant,
            "repeated_adjacent_fraction": self.repeated_adjacent / self.delta_count,
            "nondecreasing_adjacent_fraction": self.nondecreasing_adjacent
            / self.delta_count,
        }


class WayReferenceHandler(xml.sax.ContentHandler):
    def __init__(self, callback: Callable[[list[int]], None]):
        super().__init__()
        self.callback = callback
        self.current: list[int] | None = None

    def startElement(self, name: str, attrs: xml.sax.xmlreader.AttributesImpl) -> None:
        if name == "way":
            if self.current is not None:
                raise ValueError("nested OSM way elements")
            self.current = []
        elif name == "nd" and self.current is not None:
            if "ref" not in attrs:
                raise ValueError("way nd element lacks ref")
            raw = attrs["ref"]
            try:
                ref = int(raw, 10)
            except ValueError as exc:
                raise ValueError(f"invalid way node ref {raw!r}") from exc
            if ref <= 0 or ref > INT64_MAX:
                raise ValueError(f"way node ref outside positive int64: {ref}")
            self.current.append(ref)

    def endElement(self, name: str) -> None:
        if name == "way":
            if self.current is None:
                raise ValueError("way close without open")
            if self.current:
                self.callback(self.current)
            self.current = None


def scan_diff(path: Path, callback: Callable[[list[int]], None]) -> None:
    if not path.is_file():
        raise ValueError(f"missing OSM diff: {path}")
    parser = xml.sax.make_parser()
    parser.setFeature(handler.feature_namespaces, False)
    for feature in (handler.feature_external_ges, handler.feature_external_pes):
        try:
            parser.setFeature(feature, False)
        except (xml.sax.SAXNotRecognizedException, xml.sax.SAXNotSupportedException):
            pass
    parser.setContentHandler(WayReferenceHandler(callback))
    try:
        with gzip.open(path, "rb") as source:
            parser.parse(source)
    except (OSError, xml.sax.SAXException) as exc:
        raise ValueError(f"cannot parse {path.name}: {exc}") from exc


def inspect(paths: list[Path]) -> None:
    if len(paths) != 3:
        raise ValueError(f"expected three daily diffs, found {len(paths)}")
    total = 0
    for path in paths:
        metrics = Metrics()

        def accept(refs: list[int]) -> None:
            metrics.add_group(refs)

        scan_diff(path, accept)
        metrics.validate(path)
        total += metrics.value_count
        print(
            f"source={path.name} ways={metrics.way_count} "
            f"refs={metrics.value_count} min={metrics.minimum} max={metrics.maximum}"
        )
    print(f"semantic_validation=ok files={len(paths)} total_refs={total}")


def build(diff_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    paths = sorted(diff_dir.glob("sequence_*.osc.gz"))
    if len(paths) != 3:
        raise ValueError(f"expected three daily diffs, found {len(paths)}")
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for path in paths:
        metrics = Metrics()
        output = output_dir / f"{path.name.removesuffix('.osc.gz')}_way_refs_i64.bin"
        with output.open("wb") as target:

            def accept(refs: list[int]) -> None:
                metrics.add_group(refs)
                target.write(struct.pack(f"<{len(refs)}q", *refs))

            scan_diff(path, accept)
        metrics.validate(path)
        expected_bytes = metrics.value_count * 8
        if output.stat().st_size != expected_bytes:
            raise ValueError(f"{output}: output size mismatch")
        sequence = int(path.name.removeprefix("sequence_").removesuffix(".osc.gz"))
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
                "numeric_kind": "int",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": expected_bytes,
                "value_count": metrics.value_count,
                "sample_format": "raw homogeneous signed int64 way-node reference array",
                "sample_geometry": "graph_topology_reference_stream",
                "sample_rank": 1,
                "sample_shape": [metrics.value_count],
                "sample_axes": ["ordered_way_reference"],
                "natural_record_kind": "osm_daily_replication_diff_way_reference_stream",
                "source_field": "way/nd/@ref",
                "source_sample": path.name,
                "replication_sequence": sequence,
                "way_count": metrics.way_count,
                "min": metrics.minimum,
                "max": metrics.maximum,
            }
        )
        records.append(
            {
                "source_name": path.name,
                "source_bytes": path.stat().st_size,
                "replication_sequence": sequence,
                **metrics.as_dict(),
            }
        )

    counts = [int(row["value_count"]) for row in rows]
    total_values = sum(counts)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES:
        raise ValueError(f"total values below floor: {total_values}")
    if median_values < MIN_SAMPLE_VALUES:
        raise ValueError(f"median sample below floor: {median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    with index_path.open("w", encoding="utf-8") as handle_out:
        for row in rows:
            handle_out.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "records": records,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built samples={len(rows)} primary_values={total_values} "
        f"primary_bytes={total_bytes} median={median_values:g}"
    )


def verify(diff_dir: Path, index_path: Path, data_root: Path) -> None:
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 3:
        raise ValueError(f"expected three indexed samples, found {len(rows)}")
    counts = []
    total_bytes = 0
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("role") != "primary":
            raise ValueError("invalid index identity or role")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 64:
            raise ValueError("indexed sample is not signed int64")
        source = diff_dir / row["source_sample"]
        sample = data_root / row["sample_path"]
        metrics = Metrics()
        with sample.open("rb") as actual:

            def accept(refs: list[int]) -> None:
                metrics.add_group(refs)
                expected = struct.pack(f"<{len(refs)}q", *refs)
                if actual.read(len(expected)) != expected:
                    raise ValueError(f"source-to-output mismatch for {source.name}")

            scan_diff(source, accept)
            if actual.read(1):
                raise ValueError(f"trailing output bytes for {source.name}")
        metrics.validate(source)
        expected_bytes = metrics.value_count * 8
        if row.get("value_count") != metrics.value_count or row.get(
            "sample_size_bytes"
        ) != expected_bytes:
            raise ValueError(f"indexed size/count mismatch for {source.name}")
        counts.append(metrics.value_count)
        total_bytes += expected_bytes
    if sum(counts) < MIN_TOTAL_VALUES or statistics.median(counts) < MIN_SAMPLE_VALUES:
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
    inspect_parser.add_argument("sources", nargs="+", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--diff-dir", required=True, type=Path)
    build_parser.add_argument("--samples-dir", required=True, type=Path)
    build_parser.add_argument("--index", required=True, type=Path)
    build_parser.add_argument("--stats", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--diff-dir", required=True, type=Path)
    verify_parser.add_argument("--index", required=True, type=Path)
    verify_parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.sources)
    elif args.command == "build":
        build(args.diff_dir, args.samples_dir, args.index, args.stats)
    else:
        verify(args.diff_dir, args.index, args.data_root)


if __name__ == "__main__":
    main()
