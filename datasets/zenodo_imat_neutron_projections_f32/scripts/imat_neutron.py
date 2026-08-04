#!/usr/bin/env python3
"""Build, inspect, and verify the IMAT native-float32 neutron projections."""
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


DATASET_ID = "zenodo_imat_neutron_projections_f32"
SERIES_ID = "imat_neutron_projection_f32"
RECORD_ID = 4273969
RECORD_TITLE = "Neutron tomography data of high-purity metal rods using golden-ratio angular acquisition (IMAT, ISIS)"
ARCHIVE_NAME = "imat_rod_phantom_white_beam.zip"
ARCHIVE_SIZE = 168_192_038
ARCHIVE_MD5 = "9abc2df64fdf58cb4e194cbf29131b27"
PREFIX = "imat_rod_phantom_white_beam/"
ANGLE_NAME = PREFIX + "golden_ratio_angles.txt"
PARAMETERS_NAME = PREFIX + "scan_parameters.txt"
PROJECTION_COUNT = 186
WIDTH = 512
HEIGHT = 512
VALUE_COUNT = WIDTH * HEIGHT
SAMPLE_BYTES = VALUE_COUNT * 4
TOTAL_VALUES = PROJECTION_COUNT * VALUE_COUNT
TOTAL_BYTES = PROJECTION_COUNT * SAMPLE_BYTES


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def projection_member(index: int) -> str:
    return f"{PREFIX}proj_{index:04d}.tiff"


def validate_record(download_dir: Path) -> tuple[Path, dict[str, object]]:
    metadata_path = download_dir / f"zenodo_record_{RECORD_ID}.json"
    archive = download_dir / ARCHIVE_NAME
    if not metadata_path.is_file():
        raise SystemExit("missing pinned Zenodo metadata; run download.sh first")
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
    if int(record.get("id", 0)) != RECORD_ID or record.get("metadata", {}).get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    if record.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    files = record.get("files", [])
    matching = [item for item in files if item.get("key") == ARCHIVE_NAME]
    if len(matching) != 1:
        raise SystemExit("pinned archive is absent or ambiguous in record metadata")
    item = matching[0]
    if int(item.get("size", 0)) != ARCHIVE_SIZE or item.get("checksum") != f"md5:{ARCHIVE_MD5}":
        raise SystemExit("pinned archive identity changed in record metadata")
    if not archive.is_file() or archive.stat().st_size != ARCHIVE_SIZE:
        raise SystemExit("missing or size-mismatched pinned archive")
    if file_hash(archive, "md5") != ARCHIVE_MD5:
        raise SystemExit("pinned archive MD5 mismatch")
    return archive, record


def integer_values(data: bytes, endian: str, field_type: int, count: int, inline: bytes) -> tuple[int, ...]:
    sizes = {3: 2, 4: 4}
    formats = {3: "H", 4: "I"}
    if field_type not in sizes:
        raise ValueError(f"unsupported TIFF integer field type {field_type}")
    size = sizes[field_type] * count
    if size <= 4:
        raw = inline[:size]
    else:
        offset = struct.unpack(endian + "I", inline)[0]
        if offset < 0 or offset + size > len(data):
            raise ValueError("TIFF field value is out of bounds")
        raw = data[offset : offset + size]
    if len(raw) != size:
        raise ValueError("truncated TIFF field value")
    return struct.unpack(endian + f"{count}{formats[field_type]}", raw)


def decode_tiff(data: bytes, member: str) -> bytes:
    if len(data) != 1_048_710 or data[:2] != b"II":
        raise ValueError(f"{member}: unexpected TIFF size or byte order")
    if struct.unpack_from("<H", data, 2)[0] != 42:
        raise ValueError(f"{member}: not classic TIFF")
    ifd_offset = struct.unpack_from("<I", data, 4)[0]
    if ifd_offset != 8 or ifd_offset + 2 > len(data):
        raise ValueError(f"{member}: unexpected IFD offset")
    entry_count = struct.unpack_from("<H", data, ifd_offset)[0]
    if entry_count != 10 or ifd_offset + 2 + entry_count * 12 + 4 > len(data):
        raise ValueError(f"{member}: unexpected or truncated IFD")
    entries: dict[int, tuple[int, int, bytes]] = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, field_type, count = struct.unpack_from("<HHI", data, offset)
        if tag in entries:
            raise ValueError(f"{member}: duplicate TIFF tag {tag}")
        entries[tag] = (field_type, count, data[offset + 8 : offset + 12])
    next_ifd = struct.unpack_from("<I", data, ifd_offset + 2 + entry_count * 12)[0]
    if next_ifd != 0:
        raise ValueError(f"{member}: multiple TIFF images are not supported")

    def values(tag: int) -> tuple[int, ...]:
        if tag not in entries:
            raise ValueError(f"{member}: missing TIFF tag {tag}")
        return integer_values(data, "<", *entries[tag])

    expected = {
        256: (WIDTH,),
        257: (HEIGHT,),
        258: (32,),
        259: (1,),
        262: (1,),
        273: (134,),
        278: (HEIGHT,),
        279: (SAMPLE_BYTES,),
        284: (1,),
        339: (3,),
    }
    if set(entries) != set(expected):
        raise ValueError(f"{member}: unexpected TIFF tag set")
    for tag, wanted in expected.items():
        actual = values(tag)
        if actual != wanted:
            raise ValueError(f"{member}: TIFF tag {tag} changed: {actual} != {wanted}")
    payload = data[134 : 134 + SAMPLE_BYTES]
    if len(payload) != SAMPLE_BYTES or 134 + SAMPLE_BYTES != len(data):
        raise ValueError(f"{member}: invalid pixel-strip bounds")
    return payload


def payload_stats(payload: bytes) -> dict[str, object]:
    values = array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != VALUE_COUNT:
        raise ValueError("unexpected decoded float32 value count")
    nonfinite = sum(not math.isfinite(value) for value in values)
    if nonfinite:
        raise ValueError(f"non-finite detector values: {nonfinite}")
    minimum = min(values)
    maximum = max(values)
    distinct = len(set(values))
    zeros = values.count(0.0)
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if minimum == maximum or distinct < 250_000 or transitions < 250_000:
        raise ValueError(
            f"degenerate detector plane: range={minimum}..{maximum} distinct={distinct} transitions={transitions}"
        )
    return {
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "zero_values": zeros,
        "flattened_transitions": transitions,
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_archive(download_dir: Path) -> tuple[Path, list[float]]:
    archive, _record = validate_record(download_dir)
    expected_files = {ANGLE_NAME, PARAMETERS_NAME} | {
        projection_member(index) for index in range(PROJECTION_COUNT)
    }
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if any(info.flag_bits & 1 for info in infos):
            raise SystemExit("encrypted ZIP members are not supported")
        files = {info.filename for info in infos if not info.is_dir()}
        if files != expected_files:
            missing = sorted(expected_files - files)
            extra = sorted(files - expected_files)
            raise SystemExit(f"unexpected ZIP member set: missing={missing[:5]} extra={extra[:5]}")
        for info in infos:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"unsafe ZIP member path: {info.filename}")
        angles_text = bundle.read(ANGLE_NAME).decode("ascii")
        parameters = bundle.read(PARAMETERS_NAME).decode("ascii")
    if parameters != (
        "detector_pixels_horizontal = 512 # pixels\n"
        "detector_pixels_vertical = 512 # pixels\n"
        "detector_pixels_size = 0.055 # mm\n"
        "angle_count = 186 # angles in degrees in separate file\n\n"
    ):
        raise SystemExit("scan parameters changed")
    try:
        angles = [float(line) for line in angles_text.splitlines() if line.strip()]
    except ValueError as error:
        raise SystemExit(f"malformed angle list: {error}") from error
    if len(angles) != PROJECTION_COUNT or len(set(angles)) != PROJECTION_COUNT:
        raise SystemExit("unexpected angle count or duplicate acquisition angles")
    for index, angle in enumerate(angles):
        expected = ((math.sqrt(5.0) - 1.0) / 2.0 * 180.0 * index) % 180.0
        if not 0.0 <= angle < 180.0 or abs(angle - expected) > 0.0001:
            raise SystemExit(f"unexpected golden-ratio angle at index {index}: {angle} != {expected:.4f}")
    return archive, angles


def scan_projections(download_dir: Path) -> tuple[list[dict[str, object]], list[bytes]]:
    archive, angles = validate_archive(download_dir)
    reports: list[dict[str, object]] = []
    payloads: list[bytes] = []
    hashes: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        for index in range(PROJECTION_COUNT):
            member = projection_member(index)
            payload = decode_tiff(bundle.read(member), member)
            stats = payload_stats(payload)
            digest = str(stats["sha256"])
            if digest in hashes:
                raise SystemExit(f"duplicate decoded projection payload: {member}")
            hashes.add(digest)
            reports.append(
                {
                    "projection_index": index,
                    "angle_degrees": angles[index],
                    "source_member": member,
                    **stats,
                }
            )
            payloads.append(payload)
    return reports, payloads


def aggregate(reports: list[dict[str, object]]) -> dict[str, object]:
    ratios = [float(report["zlib_ratio"]) for report in reports]
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "value_count": len(reports) * VALUE_COUNT,
        "total_size_bytes": len(reports) * SAMPLE_BYTES,
        "unique_payloads": len({str(report["sha256"]) for report in reports}),
        "global_minimum": min(float(report["minimum"]) for report in reports),
        "global_maximum": max(float(report["maximum"]) for report in reports),
        "minimum_distinct_values": min(int(report["distinct_values"]) for report in reports),
        "zero_values": sum(int(report["zero_values"]) for report in reports),
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios),
    }
    expected = {
        "sample_count": PROJECTION_COUNT,
        "value_count": TOTAL_VALUES,
        "total_size_bytes": TOTAL_BYTES,
        "unique_payloads": PROJECTION_COUNT,
        "global_minimum": 0.0,
        "global_maximum": 2154.28515625,
        "minimum_distinct_values": 252_842,
        "zero_values": 4_258,
    }
    for key, wanted in expected.items():
        if result[key] != wanted:
            raise SystemExit(f"aggregate source statistic changed for {key}: {result[key]} != {wanted}")
    return result


def inspect(args: argparse.Namespace) -> None:
    reports, _payloads = scan_projections(args.download_dir)
    print(json.dumps(aggregate(reports), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, payloads = scan_projections(args.download_dir)
    summary = aggregate(reports)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for report, payload in zip(reports, payloads, strict=True):
        index = int(report["projection_index"])
        output = series_dir / f"proj_{index:04d}_h512_w512_f32le.bin"
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": f"downloads/{DATASET_ID}/{ARCHIVE_NAME}",
                "source_member": report["source_member"],
                "projection_index": index,
                "angle_degrees": report["angle_degrees"],
                "value_count": VALUE_COUNT,
                "sample_size_bytes": SAMPLE_BYTES,
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_format": "raw homogeneous float32 neutron detector plane",
                "sample_geometry": "2d_neutron_tomography_projection",
                "sample_rank": 2,
                "sample_shape": [HEIGHT, WIDTH],
                "sample_axes": ["detector_y", "detector_x"],
                "natural_record_kind": "complete_angular_projection_frame",
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
    summary["projections"] = reports
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "projections"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, payloads = scan_projections(args.download_dir)
    expected_summary = aggregate(reports)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != PROJECTION_COUNT:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    for index, (row, report, payload) in enumerate(zip(rows, reports, payloads, strict=True)):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"unexpected dataset/series/role at row {index}")
        if int(row.get("projection_index", -1)) != index or row.get("source_member") != projection_member(index):
            raise SystemExit(f"projection ordering mismatch at row {index}")
        if row.get("numeric_kind") != "float" or int(row.get("bit_width", 0)) != 32 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch at row {index}")
        if row.get("sample_shape") != [HEIGHT, WIDTH] or int(row.get("value_count", 0)) != VALUE_COUNT:
            raise SystemExit(f"sample geometry mismatch at row {index}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.stat().st_size != SAMPLE_BYTES:
            raise SystemExit(f"missing or size-mismatched output at row {index}")
        if output.read_bytes() != payload:
            raise SystemExit(f"output is not byte-identical to source TIFF pixels at row {index}")
        if row.get("sha256") != report["sha256"] or float(row.get("angle_degrees")) != report["angle_degrees"]:
            raise SystemExit(f"indexed hash or angle mismatch at row {index}")
    actual_outputs = {
        path.resolve()
        for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    for key, value in expected_summary.items():
        if stored.get(key) != value:
            raise SystemExit(f"ingest statistic mismatch for {key}: {stored.get(key)} != {value}")
    if stored.get("source_archive_md5") != ARCHIVE_MD5 or stored.get("projections") != reports:
        raise SystemExit("stored source identity or per-projection reports differ")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": PROJECTION_COUNT,
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
