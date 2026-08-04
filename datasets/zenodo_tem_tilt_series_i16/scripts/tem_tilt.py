#!/usr/bin/env python3
"""Build, inspect, and verify the bounded native-int16 TEM tilt sequence."""
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys
import zlib


DATASET_ID = "zenodo_tem_tilt_series_i16"
SERIES_ID = "sarscov2_tem_projection_i16"
RECORD_ID = 3985424
RECORD_TITLE = "Electron microscopy of SARS-CoV-2 particles - Dataset 05"
SOURCE_NAME = "Dataset_05_SARS-CoV-2_009.mrc"
SOURCE_BYTES = 1_048_708_096
SOURCE_MD5 = "5cb0286e5a75ce2d330efa8c7e1440ae"
HEADER_BYTES = 132_096
HEADER_SHA256 = "50371751ebc9c6f011614b17ba577b1cce3db3480db13a0441fa36a6b4fb20c6"
WIDTH = 2048
HEIGHT = 2048
FRAME_VALUES = WIDTH * HEIGHT
FRAME_BYTES = FRAME_VALUES * 2
SELECTED = tuple(range(0, 125, 2))
TOTAL_VALUES = len(SELECTED) * FRAME_VALUES
TOTAL_BYTES = len(SELECTED) * FRAME_BYTES
SELECTION_SHA256 = "931d9bd9099d92bc9a50e574023eab8f52bba0d4ac006494e151c4b38ee876cb"


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_metadata(download_dir: Path) -> None:
    path = download_dir / f"record_{RECORD_ID}.json"
    if not path.is_file():
        raise SystemExit("missing Zenodo record metadata; run download.sh first")
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    if metadata.get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    description = str(metadata.get("description", "")).lower()
    if "raw image tilt series" not in description or "mrc format" not in description:
        raise SystemExit("record no longer documents the source as a raw MRC tilt series")
    matching = [item for item in record.get("files", []) if item.get("key") == SOURCE_NAME]
    if len(matching) != 1:
        raise SystemExit("pinned MRC source is absent or ambiguous")
    item = matching[0]
    if int(item.get("size", 0)) != SOURCE_BYTES or item.get("checksum") != f"md5:{SOURCE_MD5}":
        raise SystemExit("pinned MRC source identity changed")


def parse_header(download_dir: Path) -> list[float]:
    path = download_dir / "header_and_extended.bin"
    if not path.is_file() or path.stat().st_size != HEADER_BYTES or file_hash(path, "sha256") != HEADER_SHA256:
        raise SystemExit("missing or mismatched pinned MRC/FEI header range")
    raw = path.read_bytes()
    nx, ny, nz, mode = struct.unpack_from("<4i", raw, 0)
    mx, my, mz = struct.unpack_from("<3i", raw, 28)
    mapc, mapr, maps = struct.unpack_from("<3i", raw, 64)
    ispg, nsymbt = struct.unpack_from("<2i", raw, 88)
    nlabl = struct.unpack_from("<i", raw, 220)[0]
    if (nx, ny, nz, mode) != (WIDTH, HEIGHT, 125, 1) or (mx, my, mz) != (WIDTH, HEIGHT, 125):
        raise SystemExit("unexpected MRC shape, grid, or mode")
    if (mapc, mapr, maps) != (1, 2, 3) or ispg != 0 or nsymbt != 131_072 or nlabl != 1:
        raise SystemExit("unexpected MRC axis or legacy FEI header layout")
    label = raw[224:304].rstrip(b"\x00 ").decode("ascii", "replace")
    if label != "Fei Company (C) Copyright 2003" or raw[208:216] != b"\x00" * 8:
        raise SystemExit("unrecognized legacy FEI MRC signature")
    extended = raw[1024:]
    records = [extended[index * 128 : (index + 1) * 128] for index in range(1024)]
    if any(not any(record) for record in records[:125]) or any(any(record) for record in records[125:]):
        raise SystemExit("FEI extended-header occupancy changed")
    angles = [struct.unpack_from("<f", record, 0)[0] for record in records[:125]]
    steps = [right - left for left, right in zip(angles, angles[1:])]
    if (
        any(not math.isfinite(angle) for angle in angles)
        or len(set(angles)) != 125
        or any(step <= 0 for step in steps)
        or min(steps) < 0.9
        or max(steps) > 1.1
        or not -62.1 <= angles[0] <= -61.9
        or not 61.9 <= angles[-1] <= 62.1
    ):
        raise SystemExit("invalid FEI tilt-angle sequence")
    return angles


def frame_stats(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) != FRAME_BYTES:
        raise ValueError(f"unexpected frame byte count: {len(raw)}")
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    minimum = min(values)
    maximum = max(values)
    distinct = len(set(values))
    zeros = values.count(0)
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if minimum == maximum or distinct < 3_000 or transitions < FRAME_VALUES // 4:
        raise ValueError(
            f"degenerate projection: range={minimum}..{maximum} distinct={distinct} transitions={transitions}"
        )
    return {
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "zero_values": zeros,
        "flattened_transitions": transitions,
        "mean": statistics.fmean(values),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(raw, 9)) / len(raw), 9),
    }


def scan_sources(download_dir: Path) -> tuple[list[dict[str, object]], list[float]]:
    validate_metadata(download_dir)
    angles = parse_header(download_dir)
    digest = hashlib.sha256()
    reports: list[dict[str, object]] = []
    hashes: set[str] = set()
    for index in SELECTED:
        path = download_dir / f"frame_{index:04d}.i16le"
        if not path.is_file() or path.stat().st_size != FRAME_BYTES:
            raise SystemExit(f"missing or size-mismatched selected frame: {index}")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        try:
            stats = frame_stats(path)
        except ValueError as error:
            raise SystemExit(f"frame {index}: {error}") from error
        frame_hash = str(stats["sha256"])
        if frame_hash in hashes:
            raise SystemExit(f"duplicate selected frame payload: {index}")
        hashes.add(frame_hash)
        reports.append(
            {
                "frame_index": index,
                "tilt_angle_degrees": angles[index],
                "source_range_start": HEADER_BYTES + index * FRAME_BYTES,
                "source_range_end": HEADER_BYTES + (index + 1) * FRAME_BYTES - 1,
                **stats,
            }
        )
    if digest.hexdigest() != SELECTION_SHA256:
        raise SystemExit(f"selected concatenated SHA-256 mismatch: {digest.hexdigest()}")
    return reports, angles


def aggregate(reports: list[dict[str, object]]) -> dict[str, object]:
    ratios = [float(row["zlib_ratio"]) for row in reports]
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "value_count": len(reports) * FRAME_VALUES,
        "total_size_bytes": len(reports) * FRAME_BYTES,
        "unique_payloads": len({str(row["sha256"]) for row in reports}),
        "global_minimum": min(int(row["minimum"]) for row in reports),
        "global_maximum": max(int(row["maximum"]) for row in reports),
        "minimum_distinct_values": min(int(row["distinct_values"]) for row in reports),
        "zero_values": sum(int(row["zero_values"]) for row in reports),
        "minimum_tilt_angle_degrees": min(float(row["tilt_angle_degrees"]) for row in reports),
        "maximum_tilt_angle_degrees": max(float(row["tilt_angle_degrees"]) for row in reports),
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios),
        "selection_sha256": SELECTION_SHA256,
    }
    expected = {
        "sample_count": 63,
        "value_count": TOTAL_VALUES,
        "total_size_bytes": TOTAL_BYTES,
        "unique_payloads": 63,
        "global_minimum": -32768,
        "global_maximum": 32767,
        "minimum_distinct_values": 3807,
        "zero_values": 0,
    }
    for key, value in expected.items():
        if result[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {result[key]} != {value}")
    return result


def inspect(args: argparse.Namespace) -> None:
    reports, _angles = scan_sources(args.download_dir)
    print(json.dumps(aggregate(reports), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, _angles = scan_sources(args.download_dir)
    summary = aggregate(reports)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report in reports:
        index = int(report["frame_index"])
        source = args.download_dir / f"frame_{index:04d}.i16le"
        output = series_dir / f"tilt_{index:04d}_h2048_w2048_i16le.bin"
        output.write_bytes(source.read_bytes())
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": f"downloads/{DATASET_ID}/frame_{index:04d}.i16le",
                "source_range_start": report["source_range_start"],
                "source_range_end": report["source_range_end"],
                "frame_index": index,
                "tilt_angle_degrees": report["tilt_angle_degrees"],
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "value_count": FRAME_VALUES,
                "sample_size_bytes": FRAME_BYTES,
                "sample_format": "raw homogeneous signed-int16 electron-microscope detector plane",
                "sample_geometry": "2d_tem_tilt_projection",
                "sample_rank": 2,
                "sample_shape": [HEIGHT, WIDTH],
                "sample_axes": ["detector_y", "detector_x"],
                "natural_record_kind": "complete_tilt_projection_frame",
                "minimum": report["minimum"],
                "maximum": report["maximum"],
                "distinct_values": report["distinct_values"],
                "zero_values": report["zero_values"],
                "sha256": report["sha256"],
            }
        )
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary["source_name"] = SOURCE_NAME
    summary["source_md5"] = SOURCE_MD5
    summary["header_sha256"] = HEADER_SHA256
    summary["frames"] = reports
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "frames"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, _angles = scan_sources(args.download_dir)
    expected_summary = aggregate(reports)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(SELECTED):
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    for row, report, index in zip(rows, reports, SELECTED, strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"unexpected dataset/series/role for frame {index}")
        if int(row.get("frame_index", -1)) != index or row.get("sample_shape") != [HEIGHT, WIDTH]:
            raise SystemExit(f"frame ordering or shape mismatch: {index}")
        if row.get("numeric_kind") != "int" or int(row.get("bit_width", 0)) != 16 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch: {index}")
        source = args.download_dir / f"frame_{index:04d}.i16le"
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.stat().st_size != FRAME_BYTES or output.read_bytes() != source.read_bytes():
            raise SystemExit(f"output is not byte-identical to source range: {index}")
        if row.get("sha256") != report["sha256"] or float(row.get("tilt_angle_degrees")) != report["tilt_angle_degrees"]:
            raise SystemExit(f"indexed hash or angle mismatch: {index}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    for key, value in expected_summary.items():
        if stored.get(key) != value:
            raise SystemExit(f"ingest statistic mismatch for {key}: {stored.get(key)} != {value}")
    if stored.get("frames") != reports or stored.get("source_md5") != SOURCE_MD5 or stored.get("header_sha256") != HEADER_SHA256:
        raise SystemExit("stored source identity or per-frame reports differ")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(SELECTED),
        "verified_values": TOTAL_VALUES,
        "verified_bytes": TOTAL_BYTES,
        "selection_sha256": SELECTION_SHA256,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
