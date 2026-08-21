#!/usr/bin/env python3
"""Preflight, build, and verify UCI Parking Birmingham occupancy timelines."""
from __future__ import annotations

import argparse
from collections import OrderedDict
import csv
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import struct
import zipfile


DATASET_ID = "uci_parking_birmingham_occupancy_i16"
SERIES_ID = "parking_facility_occupancy_i16"
EXPECTED_HEADER = ["SystemCodeNumber", "Capacity", "Occupancy", "LastUpdated"]
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_TOTAL_BYTES = 1_000_000_000
EXPECTED_IDENTITIES = {
    "archive": (240_539, "af7d1b1b5bb85aa6cbf0e5212d06e76470a7fbe6c42c86ea01bf4c36d3a56ad8"),
    "metadata": (1_290, "f0a3495f3f957b8cf2bc0d2383258c26fbb46a91b29370509dffdd8c364bc14b"),
    "rights": (73_604, "a0a74ce8f4ed4ccfd34a8e56482c5f62b5def2024576d7915e339e133f3208e2"),
    "csv": (1_479_909, "f1e28b9c697769a1a05cd20148241b60b1a73fee4907611163efc6fd9d12770a"),
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_identity(path: Path, identity: str) -> None:
    expected_size, expected_hash = EXPECTED_IDENTITIES[identity]
    if not path.is_file() or path.stat().st_size != expected_size or file_hash(path) != expected_hash:
        raise SystemExit(f"missing or changed pinned {identity} source: {path}")


def validate_metadata(path: Path) -> dict[str, object]:
    require_identity(path, "metadata")
    data = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(data, ensure_ascii=False).lower()
    if "parking birmingham" not in text or not re.search(r'"uci_id"\s*:\s*482', text):
        raise SystemExit("UCI metadata does not identify Parking Birmingham dataset 482")
    if "uk open government licence" not in text or "10.24432/c51k5z" not in text:
        raise SystemExit("UCI metadata lacks the documented OGL source and dataset DOI")
    return data


def validate_rights(path: Path) -> None:
    require_identity(path, "rights")
    text = html.unescape(path.read_text(encoding="utf-8", errors="replace")).lower()
    text = re.sub(r"\s+", " ", text)
    if "parking birmingham" not in text or "10.24432/c51k5z" not in text:
        raise SystemExit("official UCI page identity validation failed")
    if not any(term in text for term in ("cc by 4.0", "cc-by-4.0", "creative commons attribution 4.0", "creativecommons.org/licenses/by/4.0")):
        raise SystemExit("official UCI page lacks CC BY 4.0 evidence")


def extract_archive(archive_path: Path, extracted_path: Path) -> dict[str, object]:
    require_identity(archive_path, "archive")
    if not zipfile.is_zipfile(archive_path):
        raise SystemExit(f"invalid ZIP archive: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"ZIP CRC failure: {bad}")
        candidates: list[zipfile.ZipInfo] = []
        total = 0
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"unsafe ZIP member: {info.filename}")
            total += info.file_size
            if total > 200_000_000:
                raise SystemExit("uncompressed archive exceeds safety bound")
            if not info.is_dir() and path.suffix.lower() == ".csv":
                candidates.append(info)
        if len(candidates) != 1:
            raise SystemExit(f"expected exactly one CSV member, found {[item.filename for item in candidates]}")
        info = candidates[0]
        if not 100_000 <= info.file_size <= 50_000_000:
            raise SystemExit(f"CSV member size outside expected bounds: {info.file_size}")
        extracted_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, extracted_path.open("wb") as destination:
            shutil.copyfileobj(source, destination, 1 << 20)
    require_identity(extracted_path, "csv")
    return {
        "zip_member": info.filename,
        "csv_size_bytes": extracted_path.stat().st_size,
        "csv_sha256": file_hash(extracted_path),
    }


def parse_integer(value: str, field: str, line_number: int) -> int:
    text = value.strip()
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        raise SystemExit(f"non-integer {field} at line {line_number}: {value!r}")
    return int(text)


def parse_timestamp(value: str, line_number: int) -> datetime:
    text = value.strip()
    for form in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, form)
        except ValueError:
            pass
    raise SystemExit(f"invalid LastUpdated timestamp at line {line_number}: {value!r}")


def facility_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        raise SystemExit(f"facility code cannot form a safe filename: {value!r}")
    return slug


def scan_source(path: Path) -> tuple[OrderedDict[str, list[int]], list[dict[str, object]]]:
    require_identity(path, "csv")
    values_by_facility: OrderedDict[str, list[int]] = OrderedDict()
    capacity_by_facility: dict[str, int] = {}
    last_time_by_facility: dict[str, datetime] = {}
    last_occupancy_by_facility: dict[str, int] = {}
    first_time_by_facility: dict[str, datetime] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = [value.strip() for value in next(reader)]
        except StopIteration as exc:
            raise SystemExit("empty Parking Birmingham CSV") from exc
        if header != EXPECTED_HEADER:
            raise SystemExit(f"unexpected Parking Birmingham header: {header}")
        row_count = 0
        for line_number, row in enumerate(reader, 2):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != len(EXPECTED_HEADER):
                raise SystemExit(f"field count changed at line {line_number}: {len(row)}")
            facility = row[0].strip()
            if not facility or any(ord(character) < 32 for character in facility):
                raise SystemExit(f"invalid facility code at line {line_number}: {facility!r}")
            capacity = parse_integer(row[1], "Capacity", line_number)
            occupancy = parse_integer(row[2], "Occupancy", line_number)
            timestamp = parse_timestamp(row[3], line_number)
            if not 0 < capacity <= 65535:
                raise SystemExit(f"capacity outside uint16 at line {line_number}: {capacity}")
            if not -32768 <= occupancy <= 32767:
                raise SystemExit(f"occupancy outside signed-int16 range at line {line_number}: {occupancy}")
            if facility in capacity_by_facility and capacity_by_facility[facility] != capacity:
                raise SystemExit(f"facility capacity changed for {facility}: {capacity_by_facility[facility]} -> {capacity}")
            if facility in last_time_by_facility and timestamp < last_time_by_facility[facility]:
                raise SystemExit(f"backward timestamp for {facility} at line {line_number}")
            if (
                facility in last_time_by_facility
                and timestamp == last_time_by_facility[facility]
                and occupancy != last_occupancy_by_facility[facility]
            ):
                raise SystemExit(f"conflicting same-timestamp occupancy for {facility} at line {line_number}")
            capacity_by_facility[facility] = capacity
            first_time_by_facility.setdefault(facility, timestamp)
            last_time_by_facility[facility] = timestamp
            last_occupancy_by_facility[facility] = occupancy
            values_by_facility.setdefault(facility, []).append(occupancy)
            row_count += 1
    if row_count < MIN_TOTAL_VALUES:
        raise SystemExit(f"too few total observations: {row_count}")
    lengths = [len(values) for values in values_by_facility.values()]
    if not lengths or statistics.median(lengths) < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median facility timeline below floor: {statistics.median(lengths) if lengths else 0}")
    profiles: list[dict[str, object]] = []
    hashes: set[str] = set()
    slugs: set[str] = set()
    for facility, values in values_by_facility.items():
        if len(set(values)) < 2:
            raise SystemExit(f"constant occupancy timeline: {facility}")
        payload = struct.pack(f"<{len(values)}h", *values)
        digest = hashlib.sha256(payload).hexdigest()
        if digest in hashes:
            raise SystemExit(f"duplicate occupancy timeline: {facility}")
        hashes.add(digest)
        slug = facility_slug(facility)
        if slug in slugs:
            raise SystemExit(f"facility filename collision: {facility!r} -> {slug!r}")
        slugs.add(slug)
        profiles.append({
            "facility": facility,
            "facility_slug": slug,
            "capacity": capacity_by_facility[facility],
            "value_count": len(values),
            "minimum": min(values),
            "maximum": max(values),
            "distinct_values": len(set(values)),
            "negative_values": sum(value < 0 for value in values),
            "above_capacity_values": sum(value > capacity_by_facility[facility] for value in values),
            "first_timestamp": first_time_by_facility[facility].isoformat(sep=" "),
            "last_timestamp": last_time_by_facility[facility].isoformat(sep=" "),
            "sha256": digest,
        })
    return values_by_facility, profiles


def summary(profiles: list[dict[str, object]]) -> dict[str, object]:
    total_values = sum(int(profile["value_count"]) for profile in profiles)
    lengths = [int(profile["value_count"]) for profile in profiles]
    total_bytes = total_values * 2
    if not MIN_TOTAL_VALUES <= total_values or not total_bytes <= MAX_TOTAL_BYTES:
        raise SystemExit("output aggregate outside acceptance bounds")
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(profiles),
        "value_count": total_values,
        "total_size_bytes": total_bytes,
        "median_sample_value_count": statistics.median(lengths),
        "minimum_sample_value_count": min(lengths),
        "maximum_sample_value_count": max(lengths),
        "negative_value_count": sum(int(profile["negative_values"]) for profile in profiles),
        "above_capacity_value_count": sum(int(profile["above_capacity_values"]) for profile in profiles),
        "facilities": profiles,
    }


def preflight(args: argparse.Namespace) -> None:
    metadata = validate_metadata(args.metadata)
    validate_rights(args.rights)
    archive_info = extract_archive(args.archive, args.extracted)
    _values, profiles = scan_source(args.extracted)
    result = {
        **summary(profiles),
        "uci_dataset_id": 482,
        "license": "CC BY 4.0",
        "archive_size_bytes": args.archive.stat().st_size,
        "archive_sha256": file_hash(args.archive),
        "metadata_size_bytes": args.metadata.stat().st_size,
        "metadata_sha256": file_hash(args.metadata),
        "rights_size_bytes": args.rights.stat().st_size,
        "rights_sha256": file_hash(args.rights),
        **archive_info,
    }
    # Keep a small semantic fingerprint from metadata without copying the full
    # source object into the profile.
    result["metadata_identity_valid"] = bool(metadata)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    values_by_facility, profiles = scan_source(args.source)
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    profile_by_facility = {str(profile["facility"]): profile for profile in profiles}
    rows: list[dict[str, object]] = []
    for facility, values in values_by_facility.items():
        payload = struct.pack(f"<{len(values)}h", *values)
        profile = profile_by_facility[facility]
        output = series_dir / f"{profile['facility_slug']}_occupancy_i16_n{len(values)}.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": args.source.relative_to(args.data_root).as_posix(),
            "source_field": "Occupancy",
            "facility_code": facility,
            "facility_capacity": profile["capacity"],
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "value_count": len(values),
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous signed-int16 facility-utilization timeline",
            "sample_geometry": "parking_facility_time_series_1d",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["observation_time"],
            "natural_record_kind": "complete_parking_facility_timeline",
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "negative_values": profile["negative_values"],
            "above_capacity_values": profile["above_capacity_values"],
            "first_timestamp": profile["first_timestamp"],
            "last_timestamp": profile["last_timestamp"],
            "sha256": profile["sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = summary(profiles)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    values_by_facility, profiles = scan_source(args.source)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(values_by_facility):
        raise SystemExit("index row count does not match facility count")
    expected_outputs: set[Path] = set()
    for row, (facility, values) in zip(rows, values_by_facility.items(), strict=True):
        payload = struct.pack(f"<{len(values)}h", *values)
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"dataset/series/role mismatch for {facility}")
        if row.get("facility_code") != facility or row.get("source_field") != "Occupancy":
            raise SystemExit(f"facility/source-field mismatch for {facility}")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 16 or row.get("endianness") != "little" or row.get("element_size_bytes") != 2:
            raise SystemExit(f"numeric schema mismatch for {facility}")
        if row.get("value_count") != len(values) or row.get("sample_size_bytes") != len(payload):
            raise SystemExit(f"sample geometry mismatch for {facility}")
        output = args.data_root / str(row["sample_path"])
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh source parse: {output}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch for {facility}")
        expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    expected_summary = summary(profiles)
    if json.loads(args.stats.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("ingest stats differ from fresh source parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(rows),
        "verified_values": expected_summary["value_count"],
        "verified_bytes": expected_summary["total_size_bytes"],
        "median_sample_value_count": expected_summary["median_sample_value_count"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--archive", type=Path, required=True)
    preflight_parser.add_argument("--metadata", type=Path, required=True)
    preflight_parser.add_argument("--rights", type=Path, required=True)
    preflight_parser.add_argument("--extracted", type=Path, required=True)
    preflight_parser.add_argument("--profile", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--source", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
