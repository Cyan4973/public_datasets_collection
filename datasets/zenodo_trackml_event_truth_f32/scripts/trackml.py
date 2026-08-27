#!/usr/bin/env python3
"""Build and independently verify reduced TrackML event truth matrices."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import tarfile
from typing import Callable, Iterator


DATASET_ID = "zenodo_trackml_event_truth_f32"
SERIES_ID = "trackml_event_truth_f32"
MEMBER = "trackml_40k-events-10-to-50-tracks.csv"
APPLEDOUBLE_MEMBER = "._trackml_40k-events-10-to-50-tracks.csv"
HEADER = (
    "x", "y", "z", "volume_id", "vx", "vy", "vz", "px", "py", "pz",
    "q", "particle_id", "weight", "event_id",
)
FLOAT_FIELDS = ("x", "y", "z", "vx", "vy", "vz", "px", "py", "pz", "weight")
FLOAT_INDICES = tuple(HEADER.index(name) for name in FLOAT_FIELDS)
EXPECTED_IDENTITIES = {
    "record": (6_931, "2f2eb477d9c12eb96963c77b8607d1a6beacc08184f3f1a511b83e18443da3df"),
    "archive": (134_638_012, "92a03226575887f2301582632ad00fad26a379b2dfe5926dd25de4f64c14c7a8"),
}
EXPECTED_ARCHIVE_MD5 = "dce9f5596f3525e7af4aec2f99b037be"
EXPECTED_MEMBER_SIZE = 1_203_431_441
EXPECTED_SOURCE_ROWS = 9_949_945
EXPECTED_SOURCE_EVENTS = 43_725
EXPECTED_UNIQUE_EVENTS = 19_558
EXPECTED_DUPLICATE_EVENTS = 24_167
EXPECTED_UNIQUE_VALUES = 51_052_080
EXPECTED_UNIQUE_BYTES = 204_208_320
EXPECTED_SOURCE_CONCAT_SHA256 = "978dbaf8f52226fae82fb27e9ed72f6c23d19de5090a5264b1bdf24bb7a379a6"
EXPECTED_UNIQUE_CONCAT_SHA256 = "91f92ac04782ec4174a038c185bd7fe3fbba2ff4907f1f61f658b56839d9e6ff"
EXPECTED_GAPS = (
    (1_999, 2_250),
    (3_249, 3_500),
    (6_749, 7_000),
    (9_999, 10_500),
    (10_784, 10_810),
)
EXPECTED_VOLUMES = {7, 8, 9, 12, 13, 14, 16, 17, 18}
EXPECTED_CHARGES = {-1, 1}
EventConsumer = Callable[[int, int, int, bytes, str], None]


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_identity(path: Path, identity: str, max_bytes: int) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {identity}: {path}")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise SystemExit(f"{identity} size outside bounds: {size}")
    expected_size, expected_hash = EXPECTED_IDENTITIES[identity]
    actual_hash = file_hash(path)
    if size != expected_size or actual_hash != expected_hash:
        raise SystemExit(f"{identity} identity mismatch: size={size} sha256={actual_hash}")


def validate_record(path: Path) -> None:
    validate_identity(path, "record", 20_000_000)
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if str(record.get("id")) != "14386134" or not isinstance(metadata, dict):
        raise SystemExit("Zenodo record identity mismatch")
    if str(metadata.get("doi")) != "10.5281/zenodo.14386134":
        raise SystemExit("Zenodo DOI mismatch")
    if "trackformers - collision event data sets" not in str(metadata.get("title", "")).lower():
        raise SystemExit("Zenodo title mismatch")
    license_object = metadata.get("license", {})
    if not isinstance(license_object, dict) or str(license_object.get("id", "")).lower() != "cc-by-4.0":
        raise SystemExit("Zenodo record lacks expected CC BY 4.0 license")
    files = record.get("files", [])
    matches = [
        item for item in files
        if isinstance(item, dict)
        and item.get("key") == "trackml_40k-events-10-to-50-tracks.tar.gz"
    ] if isinstance(files, list) else []
    if len(matches) != 1:
        raise SystemExit("Zenodo record lacks exactly one selected TrackML archive")
    selected = matches[0]
    if int(selected.get("size", 0)) != EXPECTED_IDENTITIES["archive"][0]:
        raise SystemExit("Zenodo archive size metadata mismatch")
    if str(selected.get("checksum", "")).lower() != f"md5:{EXPECTED_ARCHIVE_MD5}":
        raise SystemExit("Zenodo archive checksum metadata mismatch")


def validate_archive(path: Path) -> None:
    validate_identity(path, "archive", 1_000_000_000)
    if file_hash(path, "md5") != EXPECTED_ARCHIVE_MD5:
        raise SystemExit("archive MD5 mismatch")


def iter_events(archive_path: Path) -> Iterator[tuple[int, int, int, bytes]]:
    validate_archive(archive_path)
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            regular = {member.name: member for member in archive.getmembers() if member.isfile()}
            if set(regular) != {MEMBER, APPLEDOUBLE_MEMBER}:
                raise SystemExit(f"unexpected regular archive members: {sorted(regular)}")
            member = regular[MEMBER]
            if member.size != EXPECTED_MEMBER_SIZE:
                raise SystemExit(f"CSV member size mismatch: {member.size}")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit("cannot open TrackML CSV member")
            reader = csv.reader(io.TextIOWrapper(source, encoding="utf-8", newline=""))
            try:
                actual_header = tuple(next(reader))
            except StopIteration:
                raise SystemExit("TrackML CSV is empty")
            if actual_header != HEADER:
                raise SystemExit(f"unexpected CSV header: {actual_header!r}")

            current_event: int | None = None
            current_rows = 0
            current_particles: set[int] = set()
            payload = bytearray()
            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(HEADER):
                    raise SystemExit(f"line {line_number}: expected {len(HEADER)} columns")
                try:
                    event_id = int(row[13])
                    volume_id = int(row[3])
                    charge = int(row[10])
                    particle_id = int(row[11])
                    values = [float(row[index]) for index in FLOAT_INDICES]
                except ValueError as error:
                    raise SystemExit(f"line {line_number}: invalid numeric value: {error}") from error
                if volume_id not in EXPECTED_VOLUMES:
                    raise SystemExit(f"line {line_number}: unexpected detector volume {volume_id}")
                if charge not in EXPECTED_CHARGES:
                    raise SystemExit(f"line {line_number}: unexpected charge {charge}")
                if not all(math.isfinite(value) for value in values):
                    raise SystemExit(f"line {line_number}: non-finite source value")
                if current_event is None:
                    current_event = event_id
                elif event_id != current_event:
                    if event_id <= current_event:
                        raise SystemExit(f"line {line_number}: event blocks are not strictly ordered")
                    yield current_event, current_rows, len(current_particles), bytes(payload)
                    current_event = event_id
                    current_rows = 0
                    current_particles.clear()
                    payload.clear()
                try:
                    packed = struct.pack("<10f", *values)
                except (OverflowError, struct.error) as error:
                    raise SystemExit(f"line {line_number}: float32 conversion failed: {error}") from error
                if any(not math.isfinite(value) for value in struct.unpack("<10f", packed)):
                    raise SystemExit(f"line {line_number}: float32 conversion became non-finite")
                payload.extend(packed)
                current_rows += 1
                current_particles.add(particle_id)
            if current_event is None:
                raise SystemExit("TrackML CSV has no data rows")
            yield current_event, current_rows, len(current_particles), bytes(payload)
    except (UnicodeDecodeError, tarfile.TarError) as error:
        raise SystemExit(f"cannot decode TrackML archive: {error}") from error


def index_row(
    event_id: int,
    hit_count: int,
    particle_count: int,
    payload: bytes,
    output: Path,
    archive: Path,
    data_root: Path,
) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": output.relative_to(data_root).as_posix(),
        "source_sample": archive.relative_to(data_root).as_posix(),
        "source_member": MEMBER,
        "source_field": ",".join(FLOAT_FIELDS),
        "event_id": event_id,
        "hit_count": hit_count,
        "particle_count": particle_count,
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "value_count": hit_count * len(FLOAT_FIELDS),
        "sample_size_bytes": len(payload),
        "sample_sha256": hashlib.sha256(payload).hexdigest(),
        "sample_format": "raw row-major IEEE-754 float32 detector-event matrix",
        "sample_geometry": "particle_tracking_event_hit_truth_matrix",
        "sample_rank": 2,
        "sample_shape": [hit_count, len(FLOAT_FIELDS)],
        "sample_axes": ["detector_hit", "physical_feature"],
    }


def scan_archive(archive_path: Path, consumer: EventConsumer | None = None) -> dict[str, object]:
    seen: set[str] = set()
    source_hash = hashlib.sha256()
    unique_hash = hashlib.sha256()
    source_event_ids: list[int] = []
    unique_value_counts: list[int] = []
    source_rows = 0
    duplicate_events = 0
    for event_id, hit_count, particle_count, payload in iter_events(archive_path):
        if not payload or len(payload) != hit_count * len(FLOAT_FIELDS) * 4:
            raise SystemExit(f"event {event_id}: invalid payload size")
        if len(set(struct.iter_unpack("<I", payload))) < 2:
            raise SystemExit(f"event {event_id}: constant float32 payload")
        source_event_ids.append(event_id)
        source_rows += hit_count
        source_hash.update(payload)
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen:
            duplicate_events += 1
            continue
        seen.add(digest)
        unique_hash.update(payload)
        unique_value_counts.append(hit_count * len(FLOAT_FIELDS))
        if consumer is not None:
            consumer(event_id, hit_count, particle_count, payload, digest)

    gaps = tuple(
        (left, right)
        for left, right in zip(source_event_ids, source_event_ids[1:])
        if right != left + 1
    )
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_row_count": source_rows,
        "source_event_count": len(source_event_ids),
        "source_event_id_min": source_event_ids[0],
        "source_event_id_max": source_event_ids[-1],
        "source_event_id_gaps": [list(pair) for pair in gaps],
        "duplicate_event_count": duplicate_events,
        "sample_count": len(unique_value_counts),
        "value_count": sum(unique_value_counts),
        "total_size_bytes": sum(unique_value_counts) * 4,
        "minimum_sample_value_count": min(unique_value_counts),
        "median_sample_value_count": statistics.median(unique_value_counts),
        "maximum_sample_value_count": max(unique_value_counts),
        "samples_below_1000_values": sum(value < 1_000 for value in unique_value_counts),
        "source_concatenated_f32_sha256": source_hash.hexdigest(),
        "unique_concatenated_f32_sha256": unique_hash.hexdigest(),
        "primary_float_fields": list(FLOAT_FIELDS),
    }
    expected = {
        "source_row_count": EXPECTED_SOURCE_ROWS,
        "source_event_count": EXPECTED_SOURCE_EVENTS,
        "source_event_id_min": 0,
        "source_event_id_max": 44_999,
        "source_event_id_gaps": [list(pair) for pair in EXPECTED_GAPS],
        "duplicate_event_count": EXPECTED_DUPLICATE_EVENTS,
        "sample_count": EXPECTED_UNIQUE_EVENTS,
        "value_count": EXPECTED_UNIQUE_VALUES,
        "total_size_bytes": EXPECTED_UNIQUE_BYTES,
        "minimum_sample_value_count": 550,
        "median_sample_value_count": 2_350.0,
        "maximum_sample_value_count": 5_920,
        "samples_below_1000_values": 369,
        "source_concatenated_f32_sha256": EXPECTED_SOURCE_CONCAT_SHA256,
    }
    for key, value in expected.items():
        if result[key] != value:
            raise SystemExit(f"source profile mismatch for {key}: {result[key]!r} != {value!r}")
    if result["unique_concatenated_f32_sha256"] != EXPECTED_UNIQUE_CONCAT_SHA256:
        raise SystemExit("unique aggregate float32 hash mismatch")
    return result


def build(args: argparse.Namespace) -> None:
    validate_record(args.record)
    if args.samples_dir.name != DATASET_ID:
        raise SystemExit("refusing to replace an unexpected samples directory")
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    def emit(event_id: int, hit_count: int, particle_count: int, payload: bytes, digest: str) -> None:
        output = series_dir / f"event_{event_id:05d}_f32_r{hit_count}_c10.bin"
        output.write_bytes(payload)
        rows.append(index_row(event_id, hit_count, particle_count, payload, output, args.archive, args.data_root))

    summary = scan_archive(args.archive, emit)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built_samples={summary['sample_count']} values={summary['value_count']} bytes={summary['total_size_bytes']} unique_sha256={summary['unique_concatenated_f32_sha256']}")


def verify(args: argparse.Namespace) -> None:
    validate_record(args.record)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing generated index or statistics")
    actual_rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line]
    expected_rows: list[dict[str, object]] = []
    expected_paths: set[Path] = set()

    def check(event_id: int, hit_count: int, particle_count: int, payload: bytes, digest: str) -> None:
        output = args.samples_dir / SERIES_ID / f"event_{event_id:05d}_f32_r{hit_count}_c10.bin"
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"sample mismatch: {output}")
        expected_paths.add(output.resolve())
        expected_rows.append(index_row(event_id, hit_count, particle_count, payload, output, args.archive, args.data_root))

    summary = scan_archive(args.archive, check)
    actual_paths = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_paths != expected_paths:
        raise SystemExit("sample output set contains missing or stale files")
    if actual_rows != expected_rows:
        raise SystemExit("sample index does not match regenerated source records")
    if json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("ingest statistics do not match regenerated source profile")
    print(f"verified_samples={summary['sample_count']} values={summary['value_count']} bytes={summary['total_size_bytes']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
