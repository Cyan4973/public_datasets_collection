#!/usr/bin/env python3
"""Decode native-int16 XYZ landmark tensors from Xsens C3D recordings."""
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import statistics
import struct
import sys
import zipfile
import zlib


DATASET_ID = "zenodo_xsens_cymbal_landmarks_i16"
SERIES_ID = "xsens_anatomical_landmarks_xyz_i16"
RECORD_ID = 21710617
RECORD_TITLE = "Cymbal percussion: multimodal motion capture, audio and video (2011)"
ARCHIVE_NAME = "XsensC3D.zip"
ARCHIVE_SIZE = 14_540_671
ARCHIVE_MD5 = "472a8466aa7cbe42e1536412a232ba41"
PREFIX = "XsensC3D/"
TAKE_COUNT = 71
POINT_COUNT = 64
POINT_RATE = 120.0
LABELS = (
    "pHipOrigin", "pRightASI", "pLeftASI", "pRightCSI", "pLeftCSI",
    "pRightIschialTub", "pLeftIschialTub", "pSacrum", "pL5SpinalProcess",
    "pL3SpinalProcess", "pT12SpinalProcess", "pPX", "pIJ", "pT4SpinalProcess",
    "pT8SpinalProcess", "pC7SpinalProcess", "pTopOfHead", "pRightAuricularis",
    "pLeftAuricularis", "pBackOfHead", "pRightAcromion", "pLeftAcromion",
    "pRightArmLatEpicondyle", "pRightArmMedEpicondyle", "pLeftArmLatEpicondyle",
    "pLeftArmMedEpicondyle", "pRightUlnarStyloid", "pRightRadialStyloid",
    "pRightOlecranon", "pLeftUlnarStyloid", "pLeftRadialStyloid", "pLeftOlecranon",
    "pRightTopOfHand", "pRightPinky", "pRightBallHand", "pLeftTopOfHand",
    "pLeftPinky", "pLeftBallHand", "pRightGreaterTrochanter",
    "pRightKneeLatEpicondyle", "pRightKneeMedEpicondyle", "pRightMiddleKneeCap",
    "pLeftGreaterTrochanter", "pLeftKneeLatEpicondyle", "pLeftKneeMedEpicondyle",
    "pLeftMiddleKneeCap", "pRightLatMalleolus", "pRightMedMalleolus",
    "pRightTibialTub", "pLeftLatMalleolus", "pLeftMedMalleolus", "pLeftTibialTub",
    "pRightHeelFoot", "pRightFirstMetatarsal", "pRightFifthMetatarsal",
    "pRightPivotFoot", "pRightHeelCenter", "pRightToe", "pLeftHeelFoot",
    "pLeftFirstMetatarsal", "pLeftFifthMetatarsal", "pLeftPivotFoot",
    "pLeftHeelCenter", "pLeftToe",
)
TOTAL_FRAMES = 75_855
TOTAL_VALUES = 14_564_160
TOTAL_BYTES = 29_128_320


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sources(download_dir: Path) -> Path:
    metadata_path = download_dir / f"record_{RECORD_ID}.json"
    archive = download_dir / ARCHIVE_NAME
    if not metadata_path.is_file():
        raise SystemExit("missing Zenodo metadata; run download.sh first")
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    if metadata.get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    description = str(metadata.get("description", "")).lower()
    if "xsens mvn inertial suit" not in description or "c3d exports" not in description:
        raise SystemExit("record no longer documents Xsens C3D motion capture")
    matching = [item for item in record.get("files", []) if item.get("key") == ARCHIVE_NAME]
    if len(matching) != 1:
        raise SystemExit("pinned archive is absent or ambiguous")
    item = matching[0]
    if int(item.get("size", 0)) != ARCHIVE_SIZE or item.get("checksum") != f"md5:{ARCHIVE_MD5}":
        raise SystemExit("pinned archive identity changed")
    if not archive.is_file() or archive.stat().st_size != ARCHIVE_SIZE or file_hash(archive, "md5") != ARCHIVE_MD5:
        raise SystemExit("missing or mismatched pinned archive")
    return archive


def expected_members() -> set[str]:
    return {f"{PREFIX}Cymbal 1-{index:03d}.c3d" for index in range(1, TAKE_COUNT + 1)} | {
        PREFIX + "Cymbal_recording_naming.txt"
    }


def decode_parameter_value(endian: str, field_type: int, dims: list[int], raw: bytes) -> object:
    count = 1
    for dim in dims:
        count *= dim
    if field_type == -1:
        if not dims:
            return raw.decode("ascii", "replace")
        width = dims[0]
        return tuple(
            raw[index * width : (index + 1) * width].decode("ascii", "replace").rstrip()
            for index in range(count // width)
        )
    formats = {1: "b", 2: "h", 4: "f"}
    if field_type not in formats:
        raise ValueError(f"unsupported C3D parameter type {field_type}")
    return tuple(struct.unpack(endian + f"{count}{formats[field_type]}", raw))


def parse_parameters(raw: bytes, endian: str, parameter_offset: int, data_offset: int) -> dict[tuple[str, str], object]:
    groups: dict[int, str] = {}
    pending: list[tuple[int, str, int, list[int], bytes]] = []
    position = parameter_offset + 4
    while position + 4 <= data_offset:
        name_length = struct.unpack_from("b", raw, position)[0]
        group_id = struct.unpack_from("b", raw, position + 1)[0]
        if name_length == 0 or group_id == 0:
            break
        length = abs(name_length)
        name = raw[position + 2 : position + 2 + length].decode("ascii", "replace").upper()
        offset_position = position + 2 + length
        jump = struct.unpack_from(endian + "H", raw, offset_position)[0]
        next_position = data_offset if jump == 0 else offset_position + jump
        if next_position <= position or next_position > data_offset:
            raise ValueError(f"invalid C3D parameter record offset for {name}")
        cursor = offset_position + 2
        if group_id < 0:
            groups[-group_id] = name
        else:
            field_type = struct.unpack_from("b", raw, cursor)[0]
            dimension_count = raw[cursor + 1]
            dims = list(raw[cursor + 2 : cursor + 2 + dimension_count])
            cursor += 2 + dimension_count
            count = 1
            for dim in dims:
                count *= dim
            size = abs(field_type) * count
            value_raw = raw[cursor : cursor + size]
            if len(value_raw) != size:
                raise ValueError(f"truncated C3D parameter value for {name}")
            pending.append((group_id, name, field_type, dims, value_raw))
        if jump == 0:
            break
        position = next_position
    values = {}
    for group_id, name, field_type, dims, value_raw in pending:
        if group_id not in groups:
            raise ValueError(f"unknown C3D parameter group {group_id}")
        values[(groups[group_id], name)] = decode_parameter_value(
            endian, field_type, dims, value_raw
        )
    return values


def scalar(params: dict[tuple[str, str], object], group: str, name: str) -> int | float:
    value = params.get((group, name))
    if not isinstance(value, tuple) or len(value) != 1 or not isinstance(value[0], (int, float)):
        raise ValueError(f"missing scalar C3D parameter {group}:{name}")
    return value[0]


def parse_c3d(raw: bytes, member: str) -> tuple[dict[str, object], bytes]:
    if len(raw) < 6144 or raw[1] != 0x50 or raw[0] < 2:
        raise ValueError(f"{member}: invalid C3D header")
    parameter_offset = (raw[0] - 1) * 512
    if raw[parameter_offset : parameter_offset + 2] != b"\x00\x00" or raw[parameter_offset + 3] != 84:
        raise ValueError(f"{member}: not Intel C3D parameter storage")
    endian = "<"
    point_count, analog_values, first_frame, last_frame, max_gap = struct.unpack_from(
        "<5H", raw, 2
    )
    point_scale = struct.unpack_from("<f", raw, 12)[0]
    data_block, analog_samples = struct.unpack_from("<2H", raw, 16)
    frame_rate = struct.unpack_from("<f", raw, 20)[0]
    frame_count = last_frame - first_frame + 1
    data_offset = (data_block - 1) * 512
    if (
        point_count != POINT_COUNT
        or analog_values != 0
        or first_frame != 1
        or last_frame < first_frame
        or max_gap != 0
        or not math.isfinite(point_scale)
        or point_scale <= 0
        or analog_samples != 0
        or frame_rate != POINT_RATE
        or data_block <= raw[0]
    ):
        raise ValueError(f"{member}: unexpected integer C3D geometry")
    bytes_per_frame = point_count * 8
    numeric_end = data_offset + frame_count * bytes_per_frame
    if len(raw) - numeric_end != 512 or any(raw[numeric_end:]):
        raise ValueError(f"{member}: expected one zero trailing C3D block")
    params = parse_parameters(raw, endian, parameter_offset, data_offset)
    if int(scalar(params, "POINT", "USED")) != POINT_COUNT:
        raise ValueError(f"{member}: POINT:USED changed")
    if float(scalar(params, "POINT", "SCALE")) != point_scale:
        raise ValueError(f"{member}: POINT:SCALE disagrees with header")
    if int(scalar(params, "POINT", "DATA_START")) != data_block:
        raise ValueError(f"{member}: POINT:DATA_START disagrees with header")
    if int(scalar(params, "POINT", "FRAMES")) != frame_count:
        raise ValueError(f"{member}: POINT:FRAMES disagrees with header")
    parameter_rate = params.get(("POINT", "RATE"))
    if parameter_rate is not None and parameter_rate != (POINT_RATE,):
        raise ValueError(f"{member}: optional POINT:RATE contradicts the C3D header")
    if params.get(("POINT", "LABELS")) != LABELS or params.get(("POINT", "DESCRIPTIONS")) != LABELS:
        raise ValueError(f"{member}: anatomical landmark labels changed")
    if params.get(("POINT", "UNITS")) != ("mm",):
        raise ValueError(f"{member}: POINT:UNITS changed")
    if int(scalar(params, "ANALOG", "USED")) != 0 or int(scalar(params, "FORCE_PLATFORM", "USED")) != 0:
        raise ValueError(f"{member}: unexpected analog or force-platform channels")
    expected_manufacturer = {
        ("MANUFACTURER", "COMPANY"): ("Xsens Technologies B.V.",),
        ("MANUFACTURER", "SOFTWARE"): ("MVN Studio C3D Exporter",),
        ("MANUFACTURER", "VERSION"): ("3.0",),
    }
    for key, expected in expected_manufacturer.items():
        if params.get(key) != expected:
            raise ValueError(f"{member}: manufacturer parameter changed: {key}")
    output = bytearray(frame_count * POINT_COUNT * 6)
    cursor = 0
    for frame in range(frame_count):
        base = data_offset + frame * bytes_per_frame
        for point in range(POINT_COUNT):
            source = base + point * 8
            output[cursor : cursor + 6] = raw[source : source + 6]
            cursor += 6
            if struct.unpack_from("<h", raw, source + 6)[0] != 0:
                raise ValueError(f"{member}: nonzero residual/camera word")
    payload = bytes(output)
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if distinct < 4_000 or transitions < len(values) // 2:
        raise ValueError(f"{member}: degenerate coordinate tensor")
    report = {
        "source_member": member,
        "frame_count": frame_count,
        "point_count": POINT_COUNT,
        "point_scale_mm_per_word": point_scale,
        "point_rate_hz": POINT_RATE,
        "value_count": len(values),
        "sample_size_bytes": len(payload),
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": distinct,
        "zero_values": values.count(0),
        "flattened_transitions": transitions,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
    }
    return report, payload


def scan(download_dir: Path) -> tuple[list[dict[str, object]], list[bytes]]:
    archive = validate_sources(download_dir)
    reports = []
    payloads = []
    hashes: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if any(info.flag_bits & 1 for info in infos):
            raise SystemExit("encrypted ZIP members are not supported")
        files = {info.filename for info in infos if not info.is_dir()}
        if files != expected_members():
            raise SystemExit("archive member set changed")
        for info in infos:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"unsafe archive member path: {info.filename}")
        for take in range(1, TAKE_COUNT + 1):
            member = f"{PREFIX}Cymbal 1-{take:03d}.c3d"
            try:
                report, payload = parse_c3d(bundle.read(member), member)
            except ValueError as error:
                raise SystemExit(str(error)) from error
            digest = str(report["sha256"])
            if digest in hashes:
                raise SystemExit(f"duplicate coordinate payload: {member}")
            hashes.add(digest)
            report["take_index"] = take
            reports.append(report)
            payloads.append(payload)
    return reports, payloads


def aggregate(reports: list[dict[str, object]]) -> dict[str, object]:
    frames = [int(row["frame_count"]) for row in reports]
    ratios = [float(row["zlib_ratio"]) for row in reports]
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "frame_count": sum(frames),
        "minimum_sample_frames": min(frames),
        "median_sample_frames": statistics.median(frames),
        "maximum_sample_frames": max(frames),
        "value_count": sum(int(row["value_count"]) for row in reports),
        "total_size_bytes": sum(int(row["sample_size_bytes"]) for row in reports),
        "unique_payloads": len({str(row["sha256"]) for row in reports}),
        "global_minimum": min(int(row["minimum"]) for row in reports),
        "global_maximum": max(int(row["maximum"]) for row in reports),
        "minimum_distinct_values": min(int(row["distinct_values"]) for row in reports),
        "zero_values": sum(int(row["zero_values"]) for row in reports),
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios),
    }
    expected = {
        "sample_count": TAKE_COUNT,
        "frame_count": TOTAL_FRAMES,
        "minimum_sample_frames": 81,
        "median_sample_frames": 965,
        "maximum_sample_frames": 2721,
        "value_count": TOTAL_VALUES,
        "total_size_bytes": TOTAL_BYTES,
        "unique_payloads": TAKE_COUNT,
        "global_minimum": -32767,
        "global_maximum": 32767,
        "minimum_distinct_values": 4852,
        "zero_values": 60_835,
    }
    for key, value in expected.items():
        if result[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {result[key]} != {value}")
    return result


def inspect(args: argparse.Namespace) -> None:
    reports, _payloads = scan(args.download_dir)
    print(json.dumps(aggregate(reports), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, payloads = scan(args.download_dir)
    summary = aggregate(reports)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report, payload in zip(reports, payloads, strict=True):
        take = int(report["take_index"])
        frames = int(report["frame_count"])
        output = series_dir / f"cymbal_{take:03d}_frames{frames}_points64_xyz_i16le.bin"
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": f"downloads/{DATASET_ID}/{ARCHIVE_NAME}",
                "source_member": report["source_member"],
                "take_index": take,
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "value_count": report["value_count"],
                "sample_size_bytes": report["sample_size_bytes"],
                "sample_format": "raw homogeneous signed-int16 anatomical-landmark XYZ tensor",
                "sample_geometry": "xsens_landmark_trajectory_tensor",
                "sample_rank": 3,
                "sample_shape": [frames, POINT_COUNT, 3],
                "sample_axes": ["time_frame", "anatomical_landmark", "coordinate_xyz"],
                "natural_record_kind": "complete_motion_capture_take",
                "point_rate_hz": POINT_RATE,
                "point_scale_mm_per_word": report["point_scale_mm_per_word"],
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
    summary["source_archive"] = ARCHIVE_NAME
    summary["source_archive_md5"] = ARCHIVE_MD5
    summary["landmark_labels"] = list(LABELS)
    summary["recordings"] = reports
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in {"recordings", "landmark_labels"}}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, payloads = scan(args.download_dir)
    expected_summary = aggregate(reports)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != TAKE_COUNT:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    for row, report, payload in zip(rows, reports, payloads, strict=True):
        take = int(report["take_index"])
        frames = int(report["frame_count"])
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"unexpected dataset/series/role for take {take}")
        if int(row.get("take_index", 0)) != take or row.get("sample_shape") != [frames, POINT_COUNT, 3]:
            raise SystemExit(f"take ordering or shape mismatch: {take}")
        if row.get("numeric_kind") != "int" or int(row.get("bit_width", 0)) != 16 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch: {take}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output is not byte-identical to decoded source XYZ words: {take}")
        if row.get("sha256") != report["sha256"] or float(row.get("point_scale_mm_per_word")) != report["point_scale_mm_per_word"]:
            raise SystemExit(f"indexed hash or point scale mismatch: {take}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    for key, value in expected_summary.items():
        if stored.get(key) != value:
            raise SystemExit(f"ingest statistic mismatch for {key}: {stored.get(key)} != {value}")
    if stored.get("source_archive_md5") != ARCHIVE_MD5 or stored.get("landmark_labels") != list(LABELS) or stored.get("recordings") != reports:
        raise SystemExit("stored source identity, labels, or per-recording reports differ")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": TAKE_COUNT,
        "verified_values": TOTAL_VALUES,
        "verified_bytes": TOTAL_BYTES,
        "source_archive_md5": ARCHIVE_MD5,
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
