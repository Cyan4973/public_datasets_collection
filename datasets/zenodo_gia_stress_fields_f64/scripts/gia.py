#!/usr/bin/env python3
"""Preflight, build, and verify glacial-isostatic HDF5 result fields."""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import html
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
from typing import Callable
import zipfile


DATASET_ID = "zenodo_gia_stress_fields_f64"
SHAPE = (161, 4, 120, 120)
VALUE_COUNT = math.prod(SHAPE)
PAYLOAD_BYTES = VALUE_COUNT * 8
EXPECTED_VALUES = VALUE_COUNT * 7
EXPECTED_BYTES = PAYLOAD_BYTES * 7
EXPECTED_ARCHIVE = (
    79_464_343,
    "860aa1ba0eead5ecfa5db24c45b4afbd",
    "79d43df369fd4b359345f1ceb068c559fd2aa37712f035be799cb14e1bb7b4c3",
)
EXPECTED_RECORD = (
    4_196,
    "8b23d4e03136d035f8c09b1cb507c01993d07600680bcab29e73293da345ada4",
)
EXPECTED_MEMBER_NAMES = {
    "GIAmodel.zip",
    "README.txt",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_S11.nc",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_S12.nc",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_S13.nc",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_S22.nc",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_S23.nc",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_S33.nc",
    "R3vc_2000_2000_2000_2_6_30_90_VM5_U3.nc",
}
H5T_IEEE_F64LE = bytes.fromhex(
    "11203f000800000000004000340b0034ff030000"
)
PayloadConsumer = Callable[[dict[str, object], bytes, dict[str, object]], None]


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
        "field_code",
        "internal_dataset",
        "series_id",
        "units",
        "member",
        "member_size_bytes",
        "compressed_size_bytes",
        "crc32",
        "member_sha256",
        "payload_sha256",
        "zero_count",
    }
    if len(raw) != 7 or not required.issubset(raw[0]):
        raise SystemExit("selection count or schema changed")
    rows: list[dict[str, object]] = []
    for source in raw:
        row = {
            **source,
            "member_size_bytes": int(source["member_size_bytes"]),
            "compressed_size_bytes": int(source["compressed_size_bytes"]),
            "zero_count": int(source["zero_count"]),
        }
        rows.append(row)
    if [row["field_code"] for row in rows] != [
        "S11", "S12", "S13", "S22", "S23", "S33", "U3"
    ]:
        raise SystemExit("selection field order changed")
    if sum(int(row["member_size_bytes"]) for row in rows) != 519_441_384:
        raise SystemExit("selected HDF5 member-byte total changed")
    return rows


def validate_record(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing Zenodo record metadata: {path}")
    if path.stat().st_size != EXPECTED_RECORD[0] or file_hash(path) != EXPECTED_RECORD[1]:
        raise SystemExit("Zenodo record metadata identity mismatch")
    record = json.loads(path.read_text(encoding="utf-8"))
    if int(record.get("id", 0)) != 5_266_382:
        raise SystemExit("Zenodo record ID mismatch")
    metadata = record.get("metadata", {})
    if metadata.get("doi") != "10.5281/zenodo.5266382":
        raise SystemExit("Zenodo DOI mismatch")
    if metadata.get("title") != "Glacially induced stresses for a simple ice load":
        raise SystemExit("Zenodo title mismatch")
    if metadata.get("license", {}).get("id", "").lower() != "cc-by-4.0":
        raise SystemExit("Zenodo record does not declare CC BY 4.0")
    description = html.unescape(
        re.sub(r"<[^>]+>", " ", str(metadata.get("description", "")))
    ).lower()
    for phrase in (
        "abaqus finite element model",
        "stress tensor",
        "vertical displacement",
        "every time point and grid point",
    ):
        if phrase not in description:
            raise SystemExit(f"Zenodo metadata lacks expected statement: {phrase}")


def validate_archive_identity(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing source archive: {path}")
    size, md5, sha256 = EXPECTED_ARCHIVE
    if (
        path.stat().st_size != size
        or file_hash(path, "md5") != md5
        or file_hash(path) != sha256
    ):
        raise SystemExit("source archive identity mismatch")


def object_messages(raw: bytes, offset: int) -> list[tuple[int, bytes]]:
    if raw[offset:offset + 6] != b"OHDR\x02\x0d":
        raise ValueError("unexpected HDF5 result object-header prefix")
    chunk_size = struct.unpack_from("<H", raw, offset + 6)[0]
    if chunk_size != 256:
        raise ValueError(f"unexpected HDF5 object-header chunk size: {chunk_size}")
    cursor = offset + 8
    end = cursor + chunk_size
    if end + 4 > len(raw):
        raise ValueError("truncated HDF5 object-header chunk")
    messages: list[tuple[int, bytes]] = []
    while cursor + 6 <= end:
        message_type = raw[cursor]
        size = struct.unpack_from("<H", raw, cursor + 1)[0]
        payload_start = cursor + 6
        payload_end = payload_start + size
        if payload_end > end:
            raise ValueError("HDF5 object-header message exceeds chunk")
        if message_type:
            messages.append((message_type, raw[payload_start:payload_end]))
        cursor = payload_end
        if message_type == 0 and size == 0:
            break
    return messages


def one_message(messages: list[tuple[int, bytes]], kind: int) -> bytes:
    values = [payload for message_type, payload in messages if message_type == kind]
    if len(values) != 1:
        raise ValueError(f"expected one HDF5 message type {kind}, found {len(values)}")
    return values[0]


def decode_result_payload(raw: bytes, internal_name: str) -> bytes:
    if raw[:8] != b"\x89HDF\r\n\x1a\n":
        raise ValueError("member lacks HDF5 signature")
    offset = raw.rfind(b"OHDR")
    if offset != 4_139:
        raise ValueError(f"unexpected result object-header offset: {offset}")
    messages = object_messages(raw, offset)
    dataspace = one_message(messages, 1)
    datatype = one_message(messages, 3)
    layout = one_message(messages, 8)
    if any(message_type == 11 for message_type, _ in messages):
        raise ValueError("result dataset unexpectedly uses an HDF5 filter pipeline")
    if len(dataspace) != 72 or tuple(dataspace[:4]) != (1, 4, 1, 0):
        raise ValueError("unexpected HDF5 dataspace descriptor")
    shape = struct.unpack_from("<4Q", dataspace, 8)
    maximum_shape = struct.unpack_from("<4Q", dataspace, 40)
    if shape != SHAPE or maximum_shape != SHAPE:
        raise ValueError(f"unexpected result shape: {shape}, max={maximum_shape}")
    if datatype != H5T_IEEE_F64LE:
        raise ValueError(f"result datatype is not H5T_IEEE_F64LE: {datatype.hex()}")
    if len(layout) != 18 or tuple(layout[:2]) != (3, 1):
        raise ValueError("result dataset is not HDF5 v3 contiguous layout")
    address, size = struct.unpack_from("<QQ", layout, 2)
    if address != 17_112 or size != PAYLOAD_BYTES or address + size != len(raw):
        raise ValueError(
            f"unexpected contiguous payload extent: address={address} size={size}"
        )
    if raw[:address].count(internal_name.encode("ascii")) != 1:
        raise ValueError(f"internal dataset name mismatch: {internal_name}")
    return raw[address:address + size]


def payload_profile(payload: bytes) -> dict[str, object]:
    values = array.array("d")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != VALUE_COUNT:
        raise ValueError("decoded payload value count changed")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("result payload contains non-finite values")
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        raise ValueError("result payload is constant")
    return {
        "value_count": len(values),
        "sample_size_bytes": len(payload),
        "zero_count": values.count(0.0),
        "minimum": minimum,
        "maximum": maximum,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_zip_structure(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) != 9 or {info.filename for info in infos} != EXPECTED_MEMBER_NAMES:
        raise SystemExit("ZIP member set changed")
    indexed: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or info.is_dir():
            raise SystemExit(f"unsafe or unexpected ZIP member: {info.filename}")
        if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
            raise SystemExit(f"encrypted or linked ZIP member: {info.filename}")
        total += info.file_size
        indexed[info.filename] = info
    if total != 536_049_155:
        raise SystemExit(f"ZIP uncompressed-byte total changed: {total}")
    readme = archive.read("README.txt").decode("utf-8", errors="strict").lower()
    for phrase in (
        "the following gia stress tensor and vertical displacement are included",
        "five variables: x, y, depth, time, parameter",
        "four depth values",
        "grid size of 50 km",
        "between 0 and 160 ka",
    ):
        if phrase not in readme:
            raise SystemExit(f"archive README lacks expected statement: {phrase}")
    return indexed


def scan_source(
    selection: Path,
    record: Path,
    archive_path: Path,
    consumer: PayloadConsumer | None = None,
) -> dict[str, object]:
    rows = load_selection(selection)
    validate_record(record)
    validate_archive_identity(archive_path)
    profiles: list[dict[str, object]] = []
    output_hashes: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        infos = validate_zip_structure(archive)
        for row in rows:
            member = str(row["member"])
            info = infos[member]
            if (
                info.file_size != row["member_size_bytes"]
                or info.compress_size != row["compressed_size_bytes"]
                or f"{info.CRC:08x}" != row["crc32"]
            ):
                raise SystemExit(f"ZIP member metadata changed: {member}")
            raw = archive.read(info)
            if hashlib.sha256(raw).hexdigest() != row["member_sha256"]:
                raise SystemExit(f"HDF5 member identity changed: {member}")
            try:
                payload = decode_result_payload(raw, str(row["internal_dataset"]))
                metrics = payload_profile(payload)
            except ValueError as error:
                raise SystemExit(f"{member}: {error}") from error
            if (
                metrics["sha256"] != row["payload_sha256"]
                or metrics["zero_count"] != row["zero_count"]
            ):
                raise SystemExit(f"pinned payload profile changed: {member}")
            digest = str(metrics["sha256"])
            if digest in output_hashes:
                raise SystemExit(f"duplicate result payload: {member}")
            output_hashes.add(digest)
            profile = {
                "field_code": row["field_code"],
                "internal_dataset": row["internal_dataset"],
                "series_id": row["series_id"],
                "units": row["units"],
                "source_member": member,
                "shape": list(SHAPE),
                **metrics,
            }
            profiles.append(profile)
            if consumer is not None:
                consumer(row, payload, profile)
    result = {
        "dataset_id": DATASET_ID,
        "record_id": 5_266_382,
        "doi": "10.5281/zenodo.5266382",
        "license": "CC BY 4.0",
        "source_archive_size_bytes": archive_path.stat().st_size,
        "source_archive_sha256": file_hash(archive_path),
        "shape": list(SHAPE),
        "sample_count": len(profiles),
        "value_count": sum(int(profile["value_count"]) for profile in profiles),
        "total_size_bytes": sum(
            int(profile["sample_size_bytes"]) for profile in profiles
        ),
        "field_profiles": profiles,
    }
    if result["value_count"] != EXPECTED_VALUES or result["total_size_bytes"] != EXPECTED_BYTES:
        raise SystemExit("aggregate output totals changed")
    return result


def preflight(args: argparse.Namespace) -> None:
    result = scan_source(args.selection, args.record, args.archive)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "field_profiles"},
            indent=2,
            sort_keys=True,
        )
    )


def build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    args.samples_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(
        row: dict[str, object], payload: bytes, profile: dict[str, object]
    ) -> None:
        series_id = str(row["series_id"])
        output_dir = args.samples_dir / series_id
        output_dir.mkdir(exist_ok=True)
        field_code = str(row["field_code"]).lower()
        output = output_dir / f"{field_code}_t161_d4_y120_x120.bin"
        output.write_bytes(payload)
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": series_id,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": args.archive.relative_to(args.data_root).as_posix(),
                "source_member": row["member"],
                "source_field": row["field_code"],
                "internal_dataset": row["internal_dataset"],
                "units": row["units"],
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "value_count": profile["value_count"],
                "sample_size_bytes": profile["sample_size_bytes"],
                "sample_format": (
                    "raw homogeneous IEEE-754 float64 finite-element field"
                ),
                "sample_geometry": (
                    "time_depth_horizontal_grid_stress_component_4d"
                    if series_id == "gia_stress_component_f64"
                    else "time_depth_horizontal_grid_displacement_4d"
                ),
                "sample_rank": 4,
                "sample_shape": list(SHAPE),
                "sample_axes": ["time", "depth", "y", "x"],
                "natural_record_kind": (
                    "complete_gia_stress_component_field"
                    if series_id == "gia_stress_component_f64"
                    else "complete_gia_vertical_displacement_field"
                ),
                "zero_count": profile["zero_count"],
                "minimum": profile["minimum"],
                "maximum": profile["maximum"],
                "sha256": profile["sha256"],
            }
        )

    summary = scan_source(args.selection, args.record, args.archive, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"built_samples={summary['sample_count']} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']}"
    )


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    indexed = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(
        row: dict[str, object], payload: bytes, profile: dict[str, object]
    ) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than source fields")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": row["series_id"],
            "role": "primary",
            "source_member": row["member"],
            "source_field": row["field_code"],
            "internal_dataset": row["internal_dataset"],
            "units": row["units"],
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_shape": list(SHAPE),
            "zero_count": profile["zero_count"],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"index mismatch for {row['field_code']}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh HDF5 extraction: {output}")
        expected_outputs.add(output.resolve())

    summary = scan_source(args.selection, args.record, args.archive, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        if args.profile is None:
            parser.error("preflight requires --profile")
        preflight(args)
    elif args.command == "build":
        if any(
            value is None
            for value in (args.samples_dir, args.index, args.stats, args.data_root)
        ):
            parser.error(
                "build requires --samples-dir, --index, --stats, and --data-root"
            )
        build(args)
    else:
        if any(
            value is None
            for value in (args.samples_dir, args.index, args.stats, args.data_root)
        ):
            parser.error(
                "verify requires --samples-dir, --index, --stats, and --data-root"
            )
        verify(args)


if __name__ == "__main__":
    main()
