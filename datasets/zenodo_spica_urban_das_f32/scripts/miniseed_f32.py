#!/usr/bin/env python3
"""Decode and verify native float32 MiniSEED v2 DAS channel/day traces."""
from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import zipfile


DATASET_ID = "zenodo_spica_urban_das_f32"
SERIES_ID = "urban_das_channel_day_f32"
EXPECTED_ARCHIVE_SIZE = 92_177_152
EXPECTED_ARCHIVE_MD5 = "bd3cf8f38eeed0aadd3ebfdd1344f87d"
EXPECTED_MEMBER_COUNT = 9
EXPECTED_SAMPLE_RATE = 50.0
EXPECTED_POSITIONS = ("055", "060", "065", "070", "075", "080", "085", "090", "095")
MEMBER_PATTERN = re.compile(r"^JGR_2019-master/DS\.20171008\.(\d{3})\.mseed$")
MIN_VALUES_PER_SAMPLE = 1_000_000
MIN_TOTAL_BYTES = 100_000_000
MAX_TOTAL_BYTES = 1_000_000_000


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def validate_archive(path: Path) -> tuple[zipfile.ZipFile, list[zipfile.ZipInfo]]:
    if not path.is_file():
        raise SystemExit(f"missing source archive: {path}")
    if path.stat().st_size != EXPECTED_ARCHIVE_SIZE:
        raise SystemExit(f"source size mismatch: {path.stat().st_size} != {EXPECTED_ARCHIVE_SIZE}")
    if digest(path, "md5") != EXPECTED_ARCHIVE_MD5:
        raise SystemExit("source MD5 mismatch")
    archive = zipfile.ZipFile(path)
    bad_member = archive.testzip()
    if bad_member is not None:
        archive.close()
        raise SystemExit(f"ZIP CRC failure: {bad_member}")
    all_infos = archive.infolist()
    infos: list[zipfile.ZipInfo] = []
    for info in all_infos:
        if info.flag_bits & 1:
            archive.close()
            raise SystemExit(f"encrypted ZIP member: {info.filename}")
        if info.filename.startswith("/") or ".." in Path(info.filename).parts:
            archive.close()
            raise SystemExit(f"unsafe ZIP member path: {info.filename}")
        if MEMBER_PATTERN.fullmatch(info.filename):
            if not 1_000_000 <= info.file_size <= 100_000_000:
                archive.close()
                raise SystemExit(f"implausible MiniSEED member size: {info.filename} {info.file_size}")
            infos.append(info)
    infos.sort(key=lambda item: item.filename)
    if len(infos) != EXPECTED_MEMBER_COUNT:
        archive.close()
        raise SystemExit(f"expected {EXPECTED_MEMBER_COUNT} MiniSEED members, found {len(infos)}")
    positions = tuple(MEMBER_PATTERN.fullmatch(info.filename).group(1) for info in infos)
    if positions != EXPECTED_POSITIONS:
        archive.close()
        raise SystemExit(f"unexpected DAS virtual-station positions: {positions}")
    if sum(info.file_size for info in infos) > 500_000_000:
        archive.close()
        raise SystemExit("uncompressed MiniSEED payload exceeds safety bound")
    return archive, infos


def sample_rate(factor: int, multiplier: int) -> float:
    if factor == 0 or multiplier == 0:
        raise ValueError("zero MiniSEED sample-rate factor or multiplier")
    factor_value = float(factor) if factor > 0 else -1.0 / factor
    multiplier_value = float(multiplier) if multiplier > 0 else -1.0 / multiplier
    return factor_value * multiplier_value


def finite_little_endian_words(payload: bytes, word_order: int) -> bytes:
    if len(payload) % 4:
        raise ValueError("float32 payload is not word aligned")
    words = array("I")
    if words.itemsize != 4:
        raise SystemExit("host unsigned-int array width is not 32 bits")
    words.frombytes(payload)
    source_is_big = word_order == 1
    if source_is_big == (sys.byteorder == "little"):
        words.byteswap()
    if any((word & 0x7F800000) == 0x7F800000 for word in words):
        raise ValueError("non-finite IEEE float32 value")
    if sys.byteorder == "little":
        return words.tobytes()
    output_words = array("I", words)
    output_words.byteswap()
    return output_words.tobytes()


def decode_member(raw: bytes, member_name: str) -> tuple[bytes, dict[str, object]]:
    offset = 0
    record_count = 0
    value_count = 0
    stream_id: str | None = None
    first_start: datetime | None = None
    previous_end: datetime | None = None
    observed_word_orders: set[int] = set()
    output = bytearray()
    while offset < len(raw):
        if offset + 48 > len(raw):
            raise ValueError(f"{member_name}: truncated fixed header at {offset}")
        header = raw[offset:offset + 48]
        if not all(chr(value).isdigit() or chr(value) == " " for value in header[:6]):
            raise ValueError(f"{member_name}: invalid sequence number at {offset}")
        if header[6:7] not in b"DRQM":
            raise ValueError(f"{member_name}: invalid quality indicator at {offset}")
        samples = struct.unpack_from(">H", header, 30)[0]
        rate_factor = struct.unpack_from(">h", header, 32)[0]
        rate_multiplier = struct.unpack_from(">h", header, 34)[0]
        data_offset = struct.unpack_from(">H", header, 44)[0]
        blockette_offset = struct.unpack_from(">H", header, 46)[0]
        if samples <= 0:
            raise ValueError(f"{member_name}: empty record at {offset}")
        year, day = struct.unpack_from(">HH", header, 20)
        hour, minute, second = header[24], header[25], header[26]
        fraction_100us = struct.unpack_from(">H", header, 28)[0]
        activity_flags = header[36]
        time_correction_100us = struct.unpack_from(">i", header, 40)[0]
        if not 1900 <= year <= 2200 or not 1 <= day <= 366 or hour > 23 or minute > 59 or second > 60 or fraction_100us > 9999:
            raise ValueError(f"{member_name}: invalid record timestamp at {offset}")
        if activity_flags != 0 or time_correction_100us != 0:
            raise ValueError(f"{member_name}: unsupported activity flags or time correction at {offset}")
        record_start = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=day - 1,
            hours=hour,
            minutes=minute,
            seconds=second,
            microseconds=fraction_100us * 100,
        )
        rate = sample_rate(rate_factor, rate_multiplier)
        if rate != EXPECTED_SAMPLE_RATE:
            raise ValueError(f"{member_name}: unexpected sample rate {rate} at {offset}")
        duration_numerator = samples * 1_000_000
        if duration_numerator % int(EXPECTED_SAMPLE_RATE):
            raise ValueError(f"{member_name}: non-integral microsecond record duration at {offset}")
        record_end = record_start + timedelta(microseconds=duration_numerator // int(EXPECTED_SAMPLE_RATE))
        if first_start is None:
            first_start = record_start
        if previous_end is not None and record_start != previous_end:
            raise ValueError(f"{member_name}: gap or overlap before record at {offset}")
        previous_end = record_end

        blockette_1000: tuple[int, int, int] | None = None
        current = blockette_offset
        visited: set[int] = set()
        while current:
            if current in visited or not 48 <= current <= 4096:
                raise ValueError(f"{member_name}: invalid blockette chain at {offset}")
            visited.add(current)
            absolute = offset + current
            if absolute + 8 > len(raw):
                raise ValueError(f"{member_name}: truncated blockette at {offset}")
            blockette_type, next_offset = struct.unpack_from(">HH", raw, absolute)
            if blockette_type == 1000:
                blockette_1000 = (raw[absolute + 4], raw[absolute + 5], raw[absolute + 6])
                break
            current = next_offset
        if blockette_1000 is None:
            raise ValueError(f"{member_name}: missing blockette 1000 at {offset}")
        encoding, word_order, record_length_exponent = blockette_1000
        if encoding != 4:
            raise ValueError(f"{member_name}: expected float32 encoding 4, found {encoding}")
        if word_order not in (0, 1):
            raise ValueError(f"{member_name}: invalid word order {word_order}")
        if not 8 <= record_length_exponent <= 20:
            raise ValueError(f"{member_name}: invalid record-length exponent {record_length_exponent}")
        record_length = 1 << record_length_exponent
        if offset + record_length > len(raw):
            raise ValueError(f"{member_name}: truncated record at {offset}")
        if not 48 <= data_offset <= record_length:
            raise ValueError(f"{member_name}: invalid data offset {data_offset}")
        payload_size = samples * 4
        if payload_size > record_length - data_offset:
            raise ValueError(f"{member_name}: sample payload exceeds record at {offset}")

        network = header[18:20].decode("ascii", errors="strict").strip()
        station = header[8:13].decode("ascii", errors="strict").strip()
        location = header[13:15].decode("ascii", errors="strict").strip()
        channel = header[15:18].decode("ascii", errors="strict").strip()
        record_stream = f"{network}.{station}.{location}.{channel}"
        if stream_id is None:
            stream_id = record_stream
        elif record_stream != stream_id:
            raise ValueError(f"{member_name}: mixed stream identities {stream_id} and {record_stream}")

        payload = raw[offset + data_offset:offset + data_offset + payload_size]
        output.extend(finite_little_endian_words(payload, word_order))
        observed_word_orders.add(word_order)
        record_count += 1
        value_count += samples
        offset += record_length

    if offset != len(raw) or record_count == 0 or stream_id is None or first_start is None or previous_end is None:
        raise ValueError(f"{member_name}: no complete MiniSEED records")
    if value_count < MIN_VALUES_PER_SAMPLE:
        raise ValueError(f"{member_name}: trace too short: {value_count} values")
    return bytes(output), {
        "source_member": member_name,
        "source_member_size_bytes": len(raw),
        "source_member_sha256": hashlib.sha256(raw).hexdigest(),
        "stream_id": stream_id,
        "sample_rate_hz": EXPECTED_SAMPLE_RATE,
        "record_count": record_count,
        "value_count": value_count,
        "word_orders": sorted(observed_word_orders),
        "start_time_utc": first_start.isoformat().replace("+00:00", "Z"),
        "end_time_utc": previous_end.isoformat().replace("+00:00", "Z"),
    }


def read_decoded_members(archive_path: Path):
    archive, infos = validate_archive(archive_path)
    try:
        for info in infos:
            raw = archive.read(info)
            if len(raw) != info.file_size:
                raise ValueError(f"short ZIP member: {info.filename}")
            decoded, metadata = decode_member(raw, info.filename)
            yield info, decoded, metadata
    finally:
        archive.close()


def inspect(args: argparse.Namespace) -> None:
    members: list[dict[str, object]] = []
    total_values = 0
    for _, decoded, metadata in read_decoded_members(args.archive):
        members.append(metadata)
        total_values += len(decoded) // 4
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "member_count": len(members),
        "value_count": total_values,
        "total_decoded_bytes": total_values * 4,
        "members": members,
    }, indent=2, sort_keys=True))


def output_name(member_name: str) -> str:
    match = MEMBER_PATTERN.fullmatch(member_name)
    if match is None:
        raise ValueError(f"unexpected member name: {member_name}")
    return f"DS_20171008_{match.group(1)}.bin"


def build(args: argparse.Namespace) -> None:
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    total_bytes = 0
    for info, decoded, metadata in read_decoded_members(args.archive):
        path = family_dir / output_name(info.filename)
        path.write_bytes(decoded)
        relative_path = path.relative_to(args.data_root).as_posix()
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": relative_path,
            "source_sample": args.archive.relative_to(args.data_root).as_posix(),
            **metadata,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "size_bytes": len(decoded),
            "sample_size_bytes": len(decoded),
            "sample_sha256": hashlib.sha256(decoded).hexdigest(),
            "sample_geometry": "synchronized_1d_das_channel_day",
            "natural_record_kind": "deposited_daily_das_channel_trace",
        }
        rows.append(row)
        total_bytes += len(decoded)
    if len(rows) != EXPECTED_MEMBER_COUNT:
        raise SystemExit(f"wrong output count: {len(rows)}")
    if len({(row["start_time_utc"], row["end_time_utc"]) for row in rows}) != 1:
        raise SystemExit("DAS channel traces are not synchronized to one common interval")
    if not MIN_TOTAL_BYTES <= total_bytes <= MAX_TOTAL_BYTES:
        raise SystemExit(f"decoded byte total outside bounds: {total_bytes}")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "value_count": total_bytes // 4,
        "total_size_bytes": total_bytes,
        "streams": [row["stream_id"] for row in rows],
        "source_members": [row["source_member"] for row in rows],
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    row_by_member = {str(row.get("source_member")): row for row in rows}
    if len(rows) != EXPECTED_MEMBER_COUNT or len(row_by_member) != len(rows):
        raise SystemExit("index has the wrong number of unique source members")
    expected_outputs: set[Path] = set()
    total_bytes = 0
    verified_streams: list[str] = []
    for info, decoded, metadata in read_decoded_members(args.archive):
        row = row_by_member.get(info.filename)
        if row is None:
            raise SystemExit(f"source member absent from index: {info.filename}")
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
            raise SystemExit("index contains a foreign dataset or series row")
        for key in ("source_member_size_bytes", "source_member_sha256", "stream_id", "sample_rate_hz", "record_count", "value_count", "word_orders", "start_time_utc", "end_time_utc"):
            if row.get(key) != metadata.get(key):
                raise SystemExit(f"indexed {key} mismatch for {info.filename}")
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 32 or row.get("endianness") != "little" or row.get("element_size_bytes") != 4:
            raise SystemExit(f"invalid numeric schema for {info.filename}")
        output = args.data_root / str(row["sample_path"])
        if not output.is_file() or output.read_bytes() != decoded:
            raise SystemExit(f"output/source mismatch: {output}")
        if int(row.get("size_bytes", -1)) != len(decoded) or int(row.get("sample_size_bytes", -1)) != len(decoded):
            raise SystemExit(f"indexed size mismatch: {output}")
        if row.get("sample_sha256") != hashlib.sha256(decoded).hexdigest():
            raise SystemExit(f"indexed output hash mismatch: {output}")
        expected_outputs.add(output.resolve())
        total_bytes += len(decoded)
        verified_streams.append(str(metadata["stream_id"]))
    actual_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    actual_outputs = {path.resolve() for path in actual_dir.glob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if stats.get("sample_count") != len(rows) or stats.get("value_count") != total_bytes // 4 or stats.get("total_size_bytes") != total_bytes:
        raise SystemExit("ingest stats do not match verified totals")
    if stats.get("streams") != verified_streams:
        raise SystemExit("ingest stream list does not match verified sources")
    if not MIN_TOTAL_BYTES <= total_bytes <= MAX_TOTAL_BYTES:
        raise SystemExit("verified output does not meet size bounds")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(rows),
        "verified_values": total_bytes // 4,
        "verified_bytes": total_bytes,
        "streams": verified_streams,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--archive", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--archive", type=Path, required=True)
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
