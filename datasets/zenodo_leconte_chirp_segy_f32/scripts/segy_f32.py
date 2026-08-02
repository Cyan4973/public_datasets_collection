#!/usr/bin/env python3
"""Build and verify native IEEE-float32 traces from pinned SEG-Y files."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
from typing import Iterator


DATASET_ID = "zenodo_leconte_chirp_segy_f32"
SERIES_ID = "leconte_chirp_trace_f32"
EXPECTED = {
    "20170916063700utc_acrossfjord.jsf.sgy": (5593632, "f8659291d02e652fd0ad1b637ce6f263"),
    "20170913032800_alongfjord.002.jsf.sgy": (18188960, "7ec1ad982273e09cab26f0252fb1af77"),
    "20170912181500_alongfjord.001.jsf.sgy": (24316656, "e73bf3fb9f7bd1be8c047f15bbc10334"),
    "20170913032800_alongfjord.001.jsf.sgy": (36287840, "1cfa077b18cb7e41133d66e23837e781"),
    "20170918085900utc_acrossfjord.jsf.sgy": (42666084, "724825ec6356673a052b727f25f66b9b"),
}
MIN_TRACES = 1_000
MIN_TOTAL_BYTES = 100_000_000
MIN_DISTINCT_LENGTHS = 3


def digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_sources(download_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for name, (expected_size, expected_md5) in EXPECTED.items():
        path = download_dir / name
        if not path.is_file():
            raise SystemExit(f"missing source file: {path}")
        if path.stat().st_size != expected_size:
            raise SystemExit(f"source size mismatch for {name}")
        if digest(path, "md5") != expected_md5:
            raise SystemExit(f"source MD5 mismatch for {name}")
        paths.append(path)
    extras = sorted(p.name for p in download_dir.glob("*.sgy") if p.name not in EXPECTED)
    if extras:
        raise SystemExit(f"unexpected SEG-Y source files: {extras}")
    return paths


def parse_header(handle, path: Path) -> tuple[int, int]:
    header = handle.read(3600)
    if len(header) != 3600:
        raise ValueError(f"{path.name}: truncated 3600-byte SEG-Y header")
    if struct.unpack_from(">H", header, 3224)[0] != 5:
        raise ValueError(f"{path.name}: SEG-Y sample format is not IEEE float32 code 5")
    binary_ns = struct.unpack_from(">H", header, 3220)[0]
    binary_dt = struct.unpack_from(">H", header, 3216)[0]
    extended_headers = struct.unpack_from(">h", header, 3504)[0]
    if binary_ns <= 0 or binary_dt <= 0:
        raise ValueError(f"{path.name}: invalid binary-header sample count or interval")
    if extended_headers != 0:
        raise ValueError(f"{path.name}: unsupported extended textual header count {extended_headers}")
    return binary_ns, binary_dt


def iter_traces(path: Path) -> Iterator[tuple[int, int, int, int, bytes]]:
    with path.open("rb") as handle:
        binary_ns, binary_dt = parse_header(handle, path)
        trace_index = 0
        while handle.tell() < path.stat().st_size:
            header_offset = handle.tell()
            trace_header = handle.read(240)
            if len(trace_header) != 240:
                raise ValueError(f"{path.name}: trailing/truncated trace header at {header_offset}")
            trace_ns = struct.unpack_from(">H", trace_header, 114)[0] or binary_ns
            trace_dt = struct.unpack_from(">H", trace_header, 116)[0] or binary_dt
            if trace_ns <= 0 or trace_dt <= 0:
                raise ValueError(f"{path.name}: invalid trace dimensions at trace {trace_index}")
            payload_offset = handle.tell()
            payload = handle.read(trace_ns * 4)
            if len(payload) != trace_ns * 4:
                raise ValueError(f"{path.name}: truncated payload at trace {trace_index}")
            yield trace_index, payload_offset, trace_ns, trace_dt, payload
            trace_index += 1
        if trace_index == 0:
            raise ValueError(f"{path.name}: no traces")


def little_endian_words(payload: bytes) -> tuple[bytes, float, float]:
    if sys.byteorder != "little":
        raise SystemExit("this recipe currently requires a little-endian build host")
    values = array("f")
    values.frombytes(payload)
    values.byteswap()
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("trace contains empty or non-finite float32 data")
    return values.tobytes(), min(values), max(values)


def build(args: argparse.Namespace) -> None:
    paths = validate_sources(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    source_stats: list[dict[str, object]] = []
    total_bytes = 0
    distinct_lengths: set[int] = set()
    global_min = math.inf
    global_max = -math.inf
    for path in paths:
        source_traces = 0
        source_values = 0
        for trace_index, payload_offset, trace_ns, trace_dt, payload in iter_traces(path):
            output, trace_min, trace_max = little_endian_words(payload)
            output_name = f"{path.stem}__trace_{trace_index:06d}_n{trace_ns:05d}.bin"
            output_path = family_dir / output_name
            output_path.write_bytes(output)
            relative_output = output_path.relative_to(args.data_root).as_posix()
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": SERIES_ID,
                    "sample_path": relative_output,
                    "source_sample": path.relative_to(args.data_root).as_posix(),
                    "source_file": path.name,
                    "source_trace_index": trace_index,
                    "source_payload_offset": payload_offset,
                    "source_payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "value_count": trace_ns,
                    "size_bytes": len(output),
                    "sample_size_bytes": len(output),
                    "numeric_kind": "float",
                    "bit_width": 32,
                    "endianness": "little",
                    "sample_interval_us": trace_dt,
                    "sample_geometry": "1d_seismic_trace",
                    "natural_record_kind": "segy_trace",
                    "minimum": trace_min,
                    "maximum": trace_max,
                }
            )
            source_traces += 1
            source_values += trace_ns
            total_bytes += len(output)
            distinct_lengths.add(trace_ns)
            global_min = min(global_min, trace_min)
            global_max = max(global_max, trace_max)
        source_stats.append(
            {"source_file": path.name, "trace_count": source_traces, "value_count": source_values}
        )
    if len(rows) < MIN_TRACES:
        raise SystemExit(f"too few traces: {len(rows)} < {MIN_TRACES}")
    if total_bytes < MIN_TOTAL_BYTES:
        raise SystemExit(f"too few output bytes: {total_bytes} < {MIN_TOTAL_BYTES}")
    if len(distinct_lengths) < MIN_DISTINCT_LENGTHS:
        raise SystemExit(f"too few distinct trace lengths: {sorted(distinct_lengths)}")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_files": source_stats,
        "sample_count": len(rows),
        "value_count": total_bytes // 4,
        "total_size_bytes": total_bytes,
        "distinct_trace_lengths": sorted(distinct_lengths),
        "minimum": global_min,
        "maximum": global_max,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    paths = validate_sources(args.download_dir)
    source_by_name = {path.name: path for path in paths}
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    expected_outputs: set[Path] = set()
    total_bytes = 0
    distinct_lengths: set[int] = set()
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
            raise SystemExit("index contains a foreign dataset or series row")
        source = source_by_name.get(str(row.get("source_file")))
        if source is None:
            raise SystemExit(f"unknown indexed source: {row.get('source_file')}")
        value_count = int(row["value_count"])
        payload_offset = int(row["source_payload_offset"])
        with source.open("rb") as handle:
            handle.seek(payload_offset)
            payload = handle.read(value_count * 4)
        if len(payload) != value_count * 4:
            raise SystemExit(f"short indexed source payload: {source.name}")
        if hashlib.sha256(payload).hexdigest() != row.get("source_payload_sha256"):
            raise SystemExit(f"source payload hash mismatch: {source.name}")
        expected, _, _ = little_endian_words(payload)
        output = args.data_root / str(row["sample_path"])
        if not output.is_file() or output.read_bytes() != expected:
            raise SystemExit(f"output/source mismatch: {output}")
        if int(row["size_bytes"]) != len(expected):
            raise SystemExit(f"indexed size mismatch: {output}")
        if int(row["sample_size_bytes"]) != len(expected):
            raise SystemExit(f"audited sample-size mismatch: {output}")
        expected_outputs.add(output.resolve())
        total_bytes += len(expected)
        distinct_lengths.add(value_count)
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID / SERIES_ID).glob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    if stats.get("sample_count") != len(rows) or stats.get("total_size_bytes") != total_bytes:
        raise SystemExit("ingest stats do not match verified index totals")
    if len(rows) < MIN_TRACES or total_bytes < MIN_TOTAL_BYTES or len(distinct_lengths) < MIN_DISTINCT_LENGTHS:
        raise SystemExit("verified outputs do not meet acceptance floors")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(rows),
        "verified_bytes": total_bytes,
        "distinct_trace_lengths": sorted(distinct_lengths),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
