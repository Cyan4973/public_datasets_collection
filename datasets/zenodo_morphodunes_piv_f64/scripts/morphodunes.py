#!/usr/bin/env python3
"""Decode and verify MorphoDunes MATLAB v5 PIV velocity fields."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
from typing import Callable, Iterator
import zlib


DATASET_ID = "zenodo_morphodunes_piv_f64"
SERIES_ID = "morphodunes_piv_uv_f64"
EXPECTED_RECORD = (
    6_738,
    "6d9f7627d523a88453dde72bc31b3dad665e18385d04df72679fe9fa02561b20",
)
EXPECTED_VALUES = 738_020
EXPECTED_BYTES = 5_904_160
EXPECTED_FINITE = 549_044
EXPECTED_NAN = 188_976
NAN_WORDS = {bytes.fromhex("000000000000f87f"), bytes.fromhex("000000000000f8ff")}
EXPECTED_PROFILES = {
    1: {"finite": 151_129, "nan": 29_035, "distinct": 151_131},
    2: {"finite": 140_272, "nan": 46_928, "distinct": 140_274},
    3: {"finite": 141_249, "nan": 47_199, "distinct": 141_251},
    4: {"finite": 116_394, "nan": 65_814, "distinct": 116_396},
}
MI_INT8 = 1
MI_INT32 = 5
MI_UINT32 = 6
MI_DOUBLE = 9
MI_MATRIX = 14
MI_COMPRESSED = 15
MX_DOUBLE = 6
Consumer = Callable[[dict[str, object], bytes, dict[str, object]], None]


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
        "experiment_id", "condition", "filename", "size_bytes", "md5", "sha256",
        "x_count", "y_count", "value_count", "output_sha256",
    }
    if len(raw) != 4 or not raw or not required.issubset(raw[0]):
        raise SystemExit("selection count or schema changed")
    rows: list[dict[str, object]] = []
    for source in raw:
        row = {
            **source,
            "experiment_id": int(source["experiment_id"]),
            "size_bytes": int(source["size_bytes"]),
            "x_count": int(source["x_count"]),
            "y_count": int(source["y_count"]),
            "value_count": int(source["value_count"]),
        }
        if row["value_count"] != row["x_count"] * row["y_count"] * 2:
            raise SystemExit(f"selection geometry mismatch: {row['filename']}")
        rows.append(row)
    if [row["experiment_id"] for row in rows] != [1, 2, 3, 4]:
        raise SystemExit("selection experiment order changed")
    if sum(int(row["size_bytes"]) for row in rows) != 5_807_387:
        raise SystemExit("selection source-byte total changed")
    if sum(int(row["value_count"]) for row in rows) != EXPECTED_VALUES:
        raise SystemExit("selection output-value total changed")
    return rows


def validate_record(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing Zenodo record metadata: {path}")
    size, digest = EXPECTED_RECORD
    if path.stat().st_size != size or file_hash(path) != digest:
        raise SystemExit("Zenodo record metadata identity mismatch")
    record = json.loads(path.read_text(encoding="utf-8"))
    if int(record.get("id", 0)) != 16_414_450:
        raise SystemExit("Zenodo record ID mismatch")
    metadata = record.get("metadata", {})
    if metadata.get("doi") != "10.5281/zenodo.16414450":
        raise SystemExit("Zenodo DOI mismatch")
    if metadata.get("license", {}).get("id", "").lower() != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    text = re.sub(
        r"\s+", " ", re.sub(r"<[^>]+>", " ", str(metadata.get("description", "")))
    ).lower()
    if "time-resolved 2d velocity fields" not in text or "streamwise and vertical components" not in text:
        raise SystemExit("Zenodo metadata lacks expected velocity-field semantics")


def elements(
    data: bytes, *, compressed_unpadded: bool = False
) -> Iterator[tuple[int, bytes]]:
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            if any(data[offset:]):
                raise ValueError("nonzero trailing bytes in MAT element stream")
            break
        word = struct.unpack_from("<I", data, offset)[0]
        if word >> 16:
            element_type = word & 0xFFFF
            size = word >> 16
            if not 0 < size <= 4:
                raise ValueError("invalid MAT small-data element")
            payload = data[offset + 4:offset + 4 + size]
            used = 8
        else:
            element_type = word
            size = struct.unpack_from("<I", data, offset + 4)[0]
            if offset + 8 + size > len(data):
                raise ValueError("truncated MAT data element")
            payload = data[offset + 8:offset + 8 + size]
            if compressed_unpadded and element_type == MI_COMPRESSED:
                used = 8 + size
            else:
                used = 8 + ((size + 7) // 8) * 8
        yield element_type, payload
        offset += used


def parse_matrix(payload: bytes) -> tuple[str, tuple[int, ...], bytes]:
    parts = list(elements(payload))
    if len(parts) != 4:
        raise ValueError(f"numeric matrix has {len(parts)} subelements; expected 4")
    if parts[0][0] != MI_UINT32 or len(parts[0][1]) != 8:
        raise ValueError("invalid MAT array flags")
    flags = struct.unpack_from("<I", parts[0][1])[0]
    if flags != MX_DOUBLE:
        raise ValueError(f"MAT array is not plain mxDOUBLE: flags={flags:#x}")
    if parts[1][0] != MI_INT32 or len(parts[1][1]) % 4:
        raise ValueError("invalid MAT dimensions")
    dimensions = struct.unpack(
        "<" + str(len(parts[1][1]) // 4) + "i", parts[1][1]
    )
    if len(dimensions) != 2 or any(value <= 0 for value in dimensions):
        raise ValueError(f"unsupported MAT dimensions: {dimensions}")
    if parts[2][0] != MI_INT8:
        raise ValueError("invalid MAT array name")
    name = parts[2][1].decode("ascii")
    if parts[3][0] != MI_DOUBLE:
        raise ValueError(f"{name}: storage is not miDOUBLE")
    expected_bytes = math.prod(dimensions) * 8
    if len(parts[3][1]) != expected_bytes:
        raise ValueError(f"{name}: numeric payload size mismatch")
    return name, dimensions, parts[3][1]


def read_mat(path: Path) -> dict[str, tuple[tuple[int, ...], bytes]]:
    raw = path.read_bytes()
    if len(raw) < 128 or not raw.startswith(b"MATLAB 5.0 MAT-file"):
        raise ValueError("not a MATLAB v5 file")
    if raw[126:128] != b"IM":
        raise ValueError("MAT file is not little-endian")
    arrays: dict[str, tuple[tuple[int, ...], bytes]] = {}
    for element_type, payload in elements(raw[128:], compressed_unpadded=True):
        if element_type == MI_COMPRESSED:
            try:
                decoded = zlib.decompress(payload)
            except zlib.error as error:
                raise ValueError(f"invalid compressed MAT element: {error}") from error
            nested = list(elements(decoded))
            if len(nested) != 1 or nested[0][0] != MI_MATRIX:
                raise ValueError("compressed MAT element does not contain one matrix")
            name, dimensions, numeric = parse_matrix(nested[0][1])
        elif element_type == MI_MATRIX:
            name, dimensions, numeric = parse_matrix(payload)
        else:
            raise ValueError(f"unexpected top-level MAT element type {element_type}")
        if name in arrays:
            raise ValueError(f"duplicate MAT variable: {name}")
        arrays[name] = (dimensions, numeric)
    if set(arrays) != {"uPIV", "vPIV", "xPIV", "yPIV", "zPIV"}:
        raise ValueError(f"unexpected MAT variables: {sorted(arrays)}")
    return arrays


def all_finite(payload: bytes) -> bool:
    return all(math.isfinite(value[0]) for value in struct.iter_unpack("<d", payload))


def validate_grid(
    arrays: dict[str, tuple[tuple[int, ...], bytes]], x_count: int, y_count: int
) -> None:
    shape = (x_count, y_count)
    for name in ("uPIV", "vPIV", "xPIV", "yPIV"):
        if arrays[name][0] != shape:
            raise ValueError(f"{name}: shape {arrays[name][0]} != {shape}")
    if arrays["zPIV"][0] != (x_count, 1):
        raise ValueError("zPIV shape mismatch")
    x_payload = arrays["xPIV"][1]
    x_column = x_payload[:x_count * 8]
    if x_payload != x_column * y_count:
        raise ValueError("xPIV is not a repeated rectilinear x-coordinate vector")
    y_payload = arrays["yPIV"][1]
    y_words = []
    for column in range(y_count):
        block = y_payload[column * x_count * 8:(column + 1) * x_count * 8]
        word = block[:8]
        if block != word * x_count:
            raise ValueError("yPIV is not a repeated rectilinear y-coordinate vector")
        y_words.append(word)
    if len(set(x_column[index:index + 8] for index in range(0, len(x_column), 8))) != x_count:
        raise ValueError("xPIV coordinate vector contains duplicates")
    if len(set(y_words)) != y_count:
        raise ValueError("yPIV coordinate vector contains duplicates")
    if not all_finite(x_payload) or not all_finite(y_payload) or not all_finite(arrays["zPIV"][1]):
        raise ValueError("coordinate metadata contains non-finite values")


def interleave_velocity(
    u_payload: bytes, v_payload: bytes
) -> tuple[bytes, dict[str, object]]:
    if len(u_payload) != len(v_payload) or len(u_payload) % 8:
        raise ValueError("uPIV/vPIV payload sizes disagree")
    output = bytearray(len(u_payload) * 2)
    finite_values: list[float] = []
    nan_counts = {word: 0 for word in NAN_WORDS}
    distinct_words: set[bytes] = set()
    cursor = 0
    for offset in range(0, len(u_payload), 8):
        for source in (u_payload, v_payload):
            word = source[offset:offset + 8]
            value = struct.unpack("<d", word)[0]
            if math.isnan(value):
                if word not in NAN_WORDS:
                    raise ValueError(f"unexpected NaN encoding: {word.hex()}")
                nan_counts[word] += 1
            elif math.isinf(value):
                raise ValueError("velocity field contains infinity")
            else:
                finite_values.append(value)
            distinct_words.add(word)
            output[cursor:cursor + 8] = word
            cursor += 8
    if not finite_values or len(distinct_words) < 1_000:
        raise ValueError("velocity field is empty or degenerate")
    return bytes(output), {
        "finite_value_count": len(finite_values),
        "nan_value_count": sum(nan_counts.values()),
        "positive_nan_count": nan_counts[bytes.fromhex("000000000000f87f")],
        "negative_nan_count": nan_counts[bytes.fromhex("000000000000f8ff")],
        "minimum_finite": min(finite_values),
        "maximum_finite": max(finite_values),
        "distinct_words": len(distinct_words),
    }


def scan(
    selection: Path, files_dir: Path, consumer: Consumer | None = None
) -> dict[str, object]:
    rows = load_selection(selection)
    profiles: list[dict[str, object]] = []
    output_hashes: set[str] = set()
    for row in rows:
        source = files_dir / str(row["filename"])
        if not source.is_file():
            raise SystemExit(f"missing selected MAT file: {source}")
        if (
            source.stat().st_size != row["size_bytes"]
            or file_hash(source, "md5") != row["md5"]
            or file_hash(source) != row["sha256"]
        ):
            raise SystemExit(f"source identity mismatch: {source.name}")
        try:
            arrays = read_mat(source)
            validate_grid(arrays, int(row["x_count"]), int(row["y_count"]))
            payload, metrics = interleave_velocity(
                arrays["uPIV"][1], arrays["vPIV"][1]
            )
        except ValueError as error:
            raise SystemExit(f"{source.name}: {error}") from error
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["output_sha256"]:
            raise SystemExit(f"output identity changed: {source.name}")
        if digest in output_hashes:
            raise SystemExit(f"duplicate vector field: {source.name}")
        output_hashes.add(digest)
        expected = EXPECTED_PROFILES[int(row["experiment_id"])]
        if (
            len(payload) // 8 != row["value_count"]
            or metrics["finite_value_count"] != expected["finite"]
            or metrics["nan_value_count"] != expected["nan"]
            or metrics["distinct_words"] != expected["distinct"]
        ):
            raise SystemExit(f"pinned field statistics changed: {source.name}")
        profile = {
            "experiment_id": row["experiment_id"],
            "condition": row["condition"],
            "source_name": source.name,
            "source_size_bytes": row["size_bytes"],
            "source_sha256": row["sha256"],
            "matlab_source_shape": [row["x_count"], row["y_count"]],
            "sample_shape": [row["y_count"], row["x_count"], 2],
            "value_count": row["value_count"],
            "sample_size_bytes": len(payload),
            "sha256": digest,
            **metrics,
        }
        profiles.append(profile)
        if consumer is not None:
            consumer(row, payload, profile)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(profiles),
        "value_count": sum(int(profile["value_count"]) for profile in profiles),
        "total_size_bytes": sum(int(profile["sample_size_bytes"]) for profile in profiles),
        "finite_value_count": sum(int(profile["finite_value_count"]) for profile in profiles),
        "nan_value_count": sum(int(profile["nan_value_count"]) for profile in profiles),
        "experiments": profiles,
    }
    if (
        summary["sample_count"] != 4
        or summary["value_count"] != EXPECTED_VALUES
        or summary["total_size_bytes"] != EXPECTED_BYTES
        or summary["finite_value_count"] != EXPECTED_FINITE
        or summary["nan_value_count"] != EXPECTED_NAN
    ):
        raise SystemExit("aggregate output statistics changed")
    return summary


def preflight(args: argparse.Namespace) -> None:
    validate_record(args.record)
    summary = scan(args.selection, args.files_dir)
    print(json.dumps({key: value for key, value in summary.items() if key != "experiments"}, indent=2, sort_keys=True))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def build(args: argparse.Namespace) -> None:
    validate_record(args.record)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    index_rows: list[dict[str, object]] = []

    def emit(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        output = series_dir / (
            f"exp_{int(row['experiment_id']):02d}_{slug(str(row['condition']))}_"
            f"uv_f64_y{int(row['y_count'])}_x{int(row['x_count'])}.bin"
        )
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": (args.files_dir / str(row["filename"])).relative_to(args.data_root).as_posix(),
            "source_field": "uPIV/vPIV interleaved",
            "experiment_id": row["experiment_id"],
            "condition": row["condition"],
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_format": "raw homogeneous IEEE-754 float64 two-component velocity field",
            "sample_geometry": "rectilinear_piv_velocity_vector_field_3d",
            "sample_rank": 3,
            "sample_shape": profile["sample_shape"],
            "sample_axes": ["y", "x", "component_uv"],
            "natural_record_kind": "complete_morphodunes_piv_experiment_velocity_field",
            "finite_value_count": profile["finite_value_count"],
            "nan_value_count": profile["nan_value_count"],
            "positive_nan_count": profile["positive_nan_count"],
            "negative_nan_count": profile["negative_nan_count"],
            "minimum_finite": profile["minimum_finite"],
            "maximum_finite": profile["maximum_finite"],
            "distinct_words": profile["distinct_words"],
            "source_sha256": profile["source_sha256"],
            "sha256": profile["sha256"],
        })

    summary = scan(args.selection, args.files_dir, emit)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "experiments"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    validate_record(args.record)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    indexed = [
        json.loads(line) for line in args.index.read_text().splitlines() if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than selected experiments")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "experiment_id": row["experiment_id"],
            "condition": row["condition"],
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_shape": profile["sample_shape"],
            "finite_value_count": profile["finite_value_count"],
            "nan_value_count": profile["nan_value_count"],
            "positive_nan_count": profile["positive_nan_count"],
            "negative_nan_count": profile["negative_nan_count"],
            "minimum_finite": profile["minimum_finite"],
            "maximum_finite": profile["maximum_finite"],
            "distinct_words": profile["distinct_words"],
            "source_sha256": profile["source_sha256"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"index mismatch for experiment {row['experiment_id']}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh MAT decode: {output}")
        expected_outputs.add(output.resolve())

    summary = scan(args.selection, args.files_dir, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text()) != summary:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']} nan_values={summary['nan_value_count']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--files-dir", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "build":
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("build requires --samples-dir, --index, --stats, and --data-root")
        build(args)
    else:
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("verify requires --samples-dir, --index, --stats, and --data-root")
        verify(args)


if __name__ == "__main__":
    main()
