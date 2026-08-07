#!/usr/bin/env python3
"""Download, inspect, build, and verify one pinned fUS float32 tensor."""
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
import sys
import zlib


DATASET_ID = "zenodo_rat_fus_image_sequence_f32"
SERIES_ID = "rat_fus_intensity_sequence_f32"
RECORD_ID = 10_074_382
RECORD_TITLE = "Functional ultrasound imaging of stroke in awake rats"
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
FILE_NAME = "Rat3_181205-AwakeStroke_PreStroke.mat"
FILE_SIZE = 430_884_352
FILE_MD5 = "b42f8b101498efeee14383f6f4c59ad7"
FILE_URL = f"https://zenodo.org/api/records/{RECORD_ID}/files/{FILE_NAME}/content"
OUTPUT_NAME = "Rat3_PreStroke_I_f32le.bin"
ARRAY_NAME = "I"
SHAPE = (187, 128, 4500)
VALUES_PER_FRAME = SHAPE[0] * SHAPE[1]
FRAME_BYTES = VALUES_PER_FRAME * 4
VALUE_COUNT = VALUES_PER_FRAME * SHAPE[2]
ARRAY_OFFSET = 192
PAYLOAD_BYTES = VALUE_COUNT * 4
EXPECTED_SHA256 = "b557b23474022d2d0cd5ca1c40e9e891213379b95f6f3ab1c944cf5400c12118"
GLOBAL_SAMPLE_STRIDE = 64
USER_AGENT = "openzl-public-datasets-rat-fus-f32/1.0"
MI_TYPES = {
    1: "miINT8", 2: "miUINT8", 3: "miINT16", 4: "miUINT16",
    5: "miINT32", 6: "miUINT32", 7: "miSINGLE", 9: "miDOUBLE",
    12: "miINT64", 13: "miUINT64", 14: "miMATRIX", 15: "miCOMPRESSED",
    16: "miUTF8", 17: "miUTF16", 18: "miUTF32",
}
MX_CLASSES = {
    1: "mxCELL_CLASS", 2: "mxSTRUCT_CLASS", 3: "mxOBJECT_CLASS",
    4: "mxCHAR_CLASS", 5: "mxSPARSE_CLASS", 6: "mxDOUBLE_CLASS",
    7: "mxSINGLE_CLASS", 8: "mxINT8_CLASS", 9: "mxUINT8_CLASS",
    10: "mxINT16_CLASS", 11: "mxUINT16_CLASS", 12: "mxINT32_CLASS",
    13: "mxUINT32_CLASS", 14: "mxINT64_CLASS", 15: "mxUINT64_CLASS",
}


def align8(value: int) -> int:
    return (value + 7) & ~7


def ordinary_tag(raw: bytes, offset: int = 0) -> tuple[int, int]:
    if offset + 8 > len(raw):
        raise ValueError("truncated MATLAB data-element tag")
    data_type, byte_count = struct.unpack_from("<II", raw, offset)
    if data_type not in MI_TYPES or byte_count > (1 << 40):
        raise ValueError(f"invalid MATLAB tag type={data_type} bytes={byte_count}")
    return data_type, byte_count


def subelement(raw: bytes, offset: int) -> tuple[int, bytes, int, int]:
    if offset + 8 > len(raw):
        raise ValueError("truncated MATLAB matrix subelement")
    first = struct.unpack_from("<I", raw, offset)[0]
    small_type = first & 0xFFFF
    small_bytes = first >> 16
    if 0 < small_bytes <= 4 and small_type in MI_TYPES:
        return small_type, raw[offset + 4:offset + 4 + small_bytes], offset + 8, small_bytes
    data_type, byte_count = ordinary_tag(raw, offset)
    data_start = offset + 8
    data_end = data_start + byte_count
    if data_end > len(raw):
        return data_type, b"", offset + 8 + align8(byte_count), byte_count
    return data_type, raw[data_start:data_end], offset + 8 + align8(byte_count), byte_count


def inspect_matrix(prefix: bytes, matrix_bytes: int) -> dict[str, object]:
    offset = 0
    flags_type, flags_data, offset, flags_bytes = subelement(prefix, offset)
    if flags_type != 6 or flags_bytes != 8 or len(flags_data) != 8:
        raise ValueError("MATLAB matrix lacks standard array flags")
    flags_word = struct.unpack_from("<I", flags_data)[0]
    class_id = flags_word & 0xFF
    dims_type, dims_data, offset, dims_bytes = subelement(prefix, offset)
    if dims_type != 5 or dims_bytes < 8 or dims_bytes % 4 or len(dims_data) != dims_bytes:
        raise ValueError("MATLAB matrix lacks readable dimensions")
    dimensions = list(struct.unpack("<" + "i" * (dims_bytes // 4), dims_data))
    name_type, name_data, offset, name_bytes = subelement(prefix, offset)
    if name_type not in {1, 16} or len(name_data) != name_bytes:
        raise ValueError("MATLAB matrix lacks readable array name")
    name = name_data.decode("utf-8" if name_type == 16 else "latin-1", "replace")
    real_type, real_data, next_offset, real_bytes = subelement(prefix, offset)
    value_count = math.prod(dimensions)
    item_size = {1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 4, 9: 8, 12: 8, 13: 8}.get(real_type)
    return {
        "name": name, "matrix_bytes": matrix_bytes, "class_id": class_id,
        "class_name": MX_CLASSES.get(class_id, f"unknown_{class_id}"),
        "complex": bool(flags_word & 0x0800), "logical": bool(flags_word & 0x0200),
        "dimensions": dimensions, "value_count": value_count,
        "real_storage_type_id": real_type,
        "real_storage_type": MI_TYPES.get(real_type, f"unknown_{real_type}"),
        "real_storage_bytes": real_bytes,
        "expected_real_storage_bytes": value_count * item_size if item_size else None,
        "real_tag_offset_within_matrix": offset,
        "real_payload_offset_within_matrix": offset + 8,
        "metadata_prefix_bytes_used": next_offset if real_data else offset + 8,
        "native_int16": real_type in {3, 4} and class_id in {10, 11},
    }


def validate_mat_prefix(raw: bytes) -> dict[str, object]:
    if len(raw) != ARRAY_OFFSET:
        raise SystemExit("MAT prefix response is incomplete")
    description = raw[:116].rstrip(b" \x00").decode("ascii", "replace")
    if not description.startswith("MATLAB 5.0 MAT-file") or raw[126:128] != b"IM":
        raise SystemExit("source is no longer little-endian MATLAB v5")
    data_type, matrix_bytes = struct.unpack_from("<II", raw, 128)
    if data_type != 14 or matrix_bytes != 430_848_056:
        raise SystemExit("top-level MATLAB matrix tag changed")
    matrix = inspect_matrix(raw[136:192], matrix_bytes)
    expected = {
        "name": ARRAY_NAME, "class_name": "mxSINGLE_CLASS", "complex": False,
        "logical": False, "dimensions": list(SHAPE), "value_count": VALUE_COUNT,
        "real_storage_type": "miSINGLE", "real_storage_bytes": PAYLOAD_BYTES,
        "real_payload_offset_within_matrix": 56, "native_int16": False,
    }
    for key, value in expected.items():
        if matrix.get(key) != value:
            raise SystemExit(f"MAT array metadata changed for {key}: {matrix.get(key)!r} != {value!r}")
    if 136 + int(matrix["real_payload_offset_within_matrix"]) != ARRAY_OFFSET:
        raise SystemExit("computed MAT array offset changed")
    return matrix


def curl_bytes(url: str, *, byte_range: str | None = None, maximum: int) -> bytes:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
        "--retry-delay", "2", "--max-time", "300", "--max-filesize", str(maximum),
        "--user-agent", USER_AGENT,
    ]
    if byte_range:
        command.extend(["--range", byte_range])
    result = subprocess.run(command + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode or len(result.stdout) > maximum:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(message or f"failed to fetch {url}")
    return result.stdout


def curl_range_to_file(url: str, start: int, size: int, output: Path) -> None:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
        "--retry-delay", "2", "--max-time", "3600", "--max-filesize", str(size),
        "--user-agent", USER_AGENT, "--range", f"{start}-{start + size - 1}",
        "--output", str(output), url,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(f"curl failed with exit status {result.returncode}: {url}")
    actual = output.stat().st_size if output.is_file() else 0
    if actual != size:
        raise SystemExit(f"range response size {actual} != {size}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_record(record: dict[str, object]) -> None:
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict) or int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    license_info = metadata.get("license", {})
    if not isinstance(license_info, dict) or license_info.get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    if "rat" not in str(metadata.get("description", "")).lower():
        raise SystemExit("record no longer documents non-human rat data")
    files = record.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("Zenodo file inventory is malformed")
    items = {str(item.get("key", "")): item for item in files if isinstance(item, dict)}
    item = items.get(FILE_NAME)
    if item is None or int(item.get("size", 0)) != FILE_SIZE or item.get("checksum") != f"md5:{FILE_MD5}":
        raise SystemExit("pinned MATLAB file identity changed")


def download(args: argparse.Namespace) -> None:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    record = json.loads(curl_bytes(RECORD_API, maximum=20_000_000))
    validate_record(record)
    matrix = validate_mat_prefix(curl_bytes(FILE_URL, byte_range=f"0-{ARRAY_OFFSET - 1}", maximum=ARRAY_OFFSET))
    target = args.download_dir / OUTPUT_NAME
    if not target.is_file() or target.stat().st_size != PAYLOAD_BYTES or sha256_file(target) != EXPECTED_SHA256:
        part = target.with_suffix(".bin.part")
        part.unlink(missing_ok=True)
        print(f"range-downloading {PAYLOAD_BYTES} numeric bytes from {FILE_NAME} at offset {ARRAY_OFFSET}")
        curl_range_to_file(FILE_URL, ARRAY_OFFSET, PAYLOAD_BYTES, part)
        if sha256_file(part) != EXPECTED_SHA256:
            part.unlink(missing_ok=True)
            raise SystemExit("downloaded numeric field SHA256 changed")
        os.replace(part, target)
    (args.download_dir / f"record_{RECORD_ID}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory = {
        "dataset_id": DATASET_ID, "record_id": RECORD_ID, "record_title": RECORD_TITLE,
        "license": "cc-by-4.0", "source_file_name": FILE_NAME,
        "source_file_size": FILE_SIZE, "source_file_md5": FILE_MD5,
        "source_file_url": FILE_URL, "array_name": ARRAY_NAME,
        "array_shape": list(SHAPE), "array_order": "matlab_column_major_source_order",
        "array_dtype": "<f4", "array_value_count": VALUE_COUNT,
        "array_offset": ARRAY_OFFSET, "array_bytes": PAYLOAD_BYTES,
        "array_sha256": EXPECTED_SHA256, "matrix_metadata": matrix,
    }
    (args.download_dir / "source_inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(inventory, indent=2, sort_keys=True))


def local_inputs(download_dir: Path) -> tuple[Path, dict[str, object]]:
    record_path = download_dir / f"record_{RECORD_ID}.json"
    inventory_path = download_dir / "source_inventory.json"
    payload_path = download_dir / OUTPUT_NAME
    if not record_path.is_file() or not inventory_path.is_file() or not payload_path.is_file():
        raise SystemExit("missing cached record, source inventory, or tensor; run download.sh")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    validate_record(record)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected = {
        "dataset_id": DATASET_ID, "record_id": RECORD_ID, "record_title": RECORD_TITLE,
        "license": "cc-by-4.0", "source_file_name": FILE_NAME,
        "source_file_size": FILE_SIZE, "source_file_md5": FILE_MD5,
        "source_file_url": FILE_URL, "array_name": ARRAY_NAME,
        "array_shape": list(SHAPE), "array_order": "matlab_column_major_source_order",
        "array_dtype": "<f4", "array_value_count": VALUE_COUNT,
        "array_offset": ARRAY_OFFSET, "array_bytes": PAYLOAD_BYTES,
        "array_sha256": EXPECTED_SHA256,
    }
    for key, value in expected.items():
        if inventory.get(key) != value:
            raise SystemExit(f"source inventory changed for {key}: {inventory.get(key)!r} != {value!r}")
    matrix = inventory.get("matrix_metadata", {})
    expected_matrix = {
        "name": ARRAY_NAME, "matrix_bytes": 430_848_056, "class_id": 7,
        "class_name": "mxSINGLE_CLASS", "complex": False, "logical": False,
        "dimensions": list(SHAPE), "value_count": VALUE_COUNT,
        "real_storage_type_id": 7, "real_storage_type": "miSINGLE",
        "real_storage_bytes": PAYLOAD_BYTES, "expected_real_storage_bytes": PAYLOAD_BYTES,
        "real_tag_offset_within_matrix": 48, "real_payload_offset_within_matrix": 56,
        "metadata_prefix_bytes_used": 56, "native_int16": False,
    }
    if matrix != expected_matrix:
        raise SystemExit("source inventory MATLAB matrix metadata changed")
    if payload_path.stat().st_size != PAYLOAD_BYTES:
        raise SystemExit("tensor byte size changed")
    return payload_path, inventory


def decode_f32le(raw: bytes) -> array:
    values = array("f")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def scan(download_dir: Path) -> dict[str, object]:
    payload_path, _inventory = local_inputs(download_dir)
    digest = hashlib.sha256()
    compressor = zlib.compressobj(9)
    compressed_bytes = 0
    frame_hashes: set[bytes] = set()
    sampled_bit_patterns: set[bytes] = set()
    frame_reports: list[dict[str, object]] = []
    global_minimum = math.inf
    global_maximum = -math.inf
    total_zero = total_positive = total_negative = total_spatial_transitions = 0
    prior_frame: array | None = None
    temporal_transitions = 0
    with payload_path.open("rb") as handle:
        for frame_index in range(SHAPE[2]):
            raw = handle.read(FRAME_BYTES)
            if len(raw) != FRAME_BYTES:
                raise SystemExit(f"truncated frame {frame_index}")
            digest.update(raw)
            compressed_bytes += len(compressor.compress(raw))
            frame_hash = hashlib.sha256(raw).digest()
            frame_hashes.add(frame_hash)
            values = decode_f32le(raw)
            if not all(math.isfinite(value) for value in values):
                raise SystemExit(f"non-finite value in frame {frame_index}")
            minimum, maximum = min(values), max(values)
            distinct = len(set(values))
            transitions = sum(left != right for left, right in zip(values, values[1:]))
            zero = values.count(0.0)
            if distinct < 16 or transitions < 16:
                raise SystemExit(f"degenerate frame {frame_index}: distinct={distinct} transitions={transitions}")
            if prior_frame is not None:
                temporal_transitions += sum(previous != current for previous, current in zip(prior_frame, values))
            prior_frame = values
            sampled_bit_patterns.update(raw[offset:offset + 4] for offset in range(0, len(raw), GLOBAL_SAMPLE_STRIDE * 4))
            global_minimum = min(global_minimum, minimum)
            global_maximum = max(global_maximum, maximum)
            total_zero += zero
            total_positive += sum(value > 0 for value in values)
            total_negative += sum(value < 0 for value in values)
            total_spatial_transitions += transitions
            frame_reports.append({
                "frame_index": frame_index, "minimum": minimum, "maximum": maximum,
                "zero_values": zero, "distinct_values": distinct,
                "flattened_spatial_transitions": transitions, "sha256": frame_hash.hex(),
            })
        if handle.read(1):
            raise SystemExit("tensor contains trailing bytes")
    compressed_bytes += len(compressor.flush())
    payload_sha256 = digest.hexdigest()
    if payload_sha256 != EXPECTED_SHA256:
        raise SystemExit("tensor SHA256 changed")
    if len(frame_hashes) != SHAPE[2]:
        raise SystemExit(f"duplicate complete frames: {SHAPE[2] - len(frame_hashes)}")
    distinct_counts = [int(report["distinct_values"]) for report in frame_reports]
    transition_counts = [int(report["flattened_spatial_transitions"]) for report in frame_reports]
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "record_id": RECORD_ID,
        "license": "cc-by-4.0", "array_name": ARRAY_NAME, "dtype": "<f4",
        "shape": list(SHAPE), "axis_interpretation": ["image_row", "image_column", "time_frame"],
        "array_order": "matlab_column_major_source_order", "frame_count": SHAPE[2],
        "values_per_frame": VALUES_PER_FRAME, "value_count": VALUE_COUNT,
        "total_size_bytes": PAYLOAD_BYTES, "global_minimum": global_minimum,
        "global_maximum": global_maximum, "zero_values": total_zero,
        "zero_fraction": round(total_zero / VALUE_COUNT, 9), "positive_values": total_positive,
        "negative_values": total_negative, "sampled_distinct_bit_patterns": len(sampled_bit_patterns),
        "global_sample_stride": GLOBAL_SAMPLE_STRIDE, "unique_frame_payloads": len(frame_hashes),
        "minimum_frame_distinct_values": min(distinct_counts),
        "median_frame_distinct_values": statistics.median(distinct_counts),
        "maximum_frame_distinct_values": max(distinct_counts),
        "minimum_frame_spatial_transitions": min(transition_counts),
        "median_frame_spatial_transitions": statistics.median(transition_counts),
        "maximum_frame_spatial_transitions": max(transition_counts),
        "total_spatial_transitions": total_spatial_transitions,
        "temporal_pixel_transitions": temporal_transitions,
        "temporal_transition_fraction": round(temporal_transitions / ((SHAPE[2] - 1) * VALUES_PER_FRAME), 9),
        "zlib_ratio": round(compressed_bytes / PAYLOAD_BYTES, 9), "sha256": payload_sha256,
        "frames": frame_reports,
    }
    expected = {
        "global_minimum": 276883.0, "global_maximum": 12316307456.0,
        "zero_values": 0, "zero_fraction": 0.0, "positive_values": 107712000,
        "negative_values": 0, "sampled_distinct_bit_patterns": 1635222,
        "unique_frame_payloads": 4500, "minimum_frame_distinct_values": 23912,
        "median_frame_distinct_values": 23925.0, "maximum_frame_distinct_values": 23935,
        "minimum_frame_spatial_transitions": 23934,
        "median_frame_spatial_transitions": 23935.0,
        "maximum_frame_spatial_transitions": 23935,
        "total_spatial_transitions": 107707477,
        "temporal_pixel_transitions": 107688032,
        "temporal_transition_fraction": 0.999999703, "zlib_ratio": 0.891360905,
    }
    for key, value in expected.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {summary[key]} != {value}")
    return summary


def public_summary(summary: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in summary.items() if key != "frames"}


def inspect(args: argparse.Namespace) -> None:
    print(json.dumps(public_summary(scan(args.download_dir)), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    summary = scan(args.download_dir)
    payload_path, _inventory = local_inputs(args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    output = series_dir / OUTPUT_NAME
    shutil.copyfile(payload_path, output)
    row = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
        "sample_path": output.relative_to(args.data_root).as_posix(),
        "source_sample": f"downloads/{DATASET_ID}/{OUTPUT_NAME}",
        "numeric_kind": "float", "bit_width": 32, "endianness": "little",
        "element_size_bytes": 4, "value_count": VALUE_COUNT,
        "sample_size_bytes": PAYLOAD_BYTES,
        "sample_format": "raw homogeneous little-endian float32 functional-ultrasound intensity tensor",
        "sample_geometry": "3d_functional_ultrasound_image_time_tensor", "sample_rank": 3,
        "sample_shape": list(SHAPE), "sample_axes": ["image_row", "image_column", "time_frame"],
        "array_order": "matlab_column_major_source_order",
        "natural_record_kind": "complete_functional_ultrasound_acquisition_tensor",
        "minimum": summary["global_minimum"], "maximum": summary["global_maximum"],
        "sha256": EXPECTED_SHA256,
    }
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    summary = scan(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        raise SystemExit("unexpected index row count")
    row = rows[0]
    expected_fields = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float",
        "bit_width": 32, "endianness": "little", "value_count": VALUE_COUNT,
        "sample_size_bytes": PAYLOAD_BYTES, "sample_shape": list(SHAPE),
        "sample_axes": ["image_row", "image_column", "time_frame"],
        "array_order": "matlab_column_major_source_order", "sha256": EXPECTED_SHA256,
    }
    for key, value in expected_fields.items():
        if row.get(key) != value:
            raise SystemExit(f"indexed field changed for {key}: {row.get(key)!r} != {value!r}")
    output = args.data_root / str(row["sample_path"])
    if not output.is_file() or output.stat().st_size != PAYLOAD_BYTES or sha256_file(output) != EXPECTED_SHA256:
        raise SystemExit("output is not byte-identical to the source numeric field")
    expected_output = output.resolve()
    actual_outputs = {
        path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != {expected_output} or json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("sample inventory or stored statistics changed")
    print(json.dumps({
        "dataset_id": DATASET_ID, "verified_samples": 1,
        "verified_values": VALUE_COUNT, "verified_bytes": PAYLOAD_BYTES,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("--download-dir", type=Path, required=True)
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
    if args.command == "download":
        download(args)
    elif args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
