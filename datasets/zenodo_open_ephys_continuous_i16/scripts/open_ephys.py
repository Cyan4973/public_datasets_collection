#!/usr/bin/env python3
"""Download, decode, build, inspect, and verify pinned Open Ephys streams."""
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import sys
import zlib


DATASET_ID = "zenodo_open_ephys_continuous_i16"
SERIES_ID = "mouse_extracellular_voltage_i16be"
RECORD_ID = 20_726_062
RECORD_TITLE = "SpikeInterface Training Dataset"
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
ARCHIVE_NAME = "1544_2023-04-21_09-55-34_of.zip"
ARCHIVE_SIZE = 2_163_918_465
ARCHIVE_MD5 = "cc6b78838ff4c48e101fe698edff1989"
ARCHIVE_URL = f"https://zenodo.org/api/records/{RECORD_ID}/files/{ARCHIVE_NAME}/content"
MEMBER_PREFIX = "1544_2023-04-21_09-55-34_of/100_"
USER_AGENT = "openzl-public-datasets-open-ephys/1.0"
HEADER_BYTES = 1024
BLOCK_SAMPLES = 1024
RECORD_BYTES = 2070
RECORD_COUNT = 65_033
SOURCE_BYTES = 134_619_334
PAYLOAD_BYTES = 133_187_584
MARKER = bytes((0, 1, 2, 3, 4, 5, 6, 7, 8, 255))
MAX_CENTRAL_BYTES = 20 * 1024 * 1024
MAX_COMPRESSED_MEMBER = 128 * 1024 * 1024

# channel, compressed bytes, CRC32, source SHA256, numeric-payload SHA256
CHANNELS = (
    ("CH1", 103_221_595, "cdc989f0", "c4e3ff9e93045603342059e9fce7b69a290de1668d8926092ad2270dd9a976cb", "308fcbc088e07b63692edfa40c834b2bc14cbb42e4856504dc63ce601cd6aa08"),
    ("CH6", 100_267_984, "1b0457a2", "0db81403dc4ec62641de21d6d55c2f07e19da8d470fa61f82235900422e67b36", "8ac1e2e196cac87c66f6b7b49ab7b5677f99cdc3ffd911962b0eefbc9be4cd93"),
    ("CH11", 103_017_290, "bad640e1", "2c5039ebfb01827f83b3a3347100369c0393daef1dd55c781ae448cf6bf8167d", "573dc7772254d8ca11b910819d63519a43cd5508a4f641dc4a8fcee4d8e33484"),
    ("CH16", 103_126_848, "c5029343", "755f6724ffcd2d07d3c17393a2c2577353065f6f48cd6747d96eb8c8ef777759", "f591334a854e566b356b3ed92589b5dff4b5f82f084d403e35d778198709b6ff"),
)


def curl_bytes(url: str, *, byte_range: str | None = None, maximum: int) -> bytes:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
        "--retry-delay", "2", "--max-time", "1800", "--max-filesize", str(maximum),
        "--user-agent", USER_AGENT,
    ]
    if byte_range:
        command.extend(["--range", byte_range])
    result = subprocess.run(command + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode or len(result.stdout) > maximum:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(message or f"failed to fetch {url}")
    return result.stdout


def archive_range(url: str, start: int, size: int, maximum: int) -> bytes:
    if start < 0 or not 0 < size <= maximum:
        raise ValueError(f"invalid archive range {start}+{size}")
    raw = curl_bytes(url, byte_range=f"{start}-{start + size - 1}", maximum=size)
    if len(raw) != size:
        raise ValueError(f"range response length {len(raw)} != {size}")
    return raw


def zip64_values(extra: bytes, need_u: bool, need_c: bool, need_o: bool) -> tuple[int | None, int | None, int | None]:
    position = 0
    while position + 4 <= len(extra):
        field_id, field_size = struct.unpack_from("<HH", extra, position)
        position += 4
        field = extra[position:position + field_size]
        position += field_size
        if field_id != 1:
            continue
        cursor = 0
        values: list[int | None] = []
        for needed in (need_u, need_c, need_o):
            if needed:
                if cursor + 8 > len(field):
                    raise ValueError("truncated ZIP64 extra field")
                values.append(struct.unpack_from("<Q", field, cursor)[0])
                cursor += 8
            else:
                values.append(None)
        return values[0], values[1], values[2]
    raise ValueError("ZIP64 sentinel without ZIP64 extra field")


def remote_zip_members(url: str, archive_size: int) -> list[dict[str, object]]:
    tail_size = min(archive_size, 65_557)
    tail = archive_range(url, archive_size - tail_size, tail_size, 65_557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        raise ValueError("ZIP end record not found")
    fields = struct.unpack_from("<4s4H2LH", tail, position)
    _sig, disk, central_disk, disk_entries, total, central_size, central_offset, comment = fields
    if disk or central_disk or position + 22 + comment > len(tail):
        raise ValueError("spanned or malformed ZIP")
    if total == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        locator = tail.rfind(b"PK\x06\x07", 0, position)
        if locator < 0:
            raise ValueError("ZIP64 locator not found")
        _sig, locator_disk, zip64_offset, disks = struct.unpack_from("<4sLQL", tail, locator)
        if locator_disk or disks != 1:
            raise ValueError("spanned ZIP64")
        record = archive_range(url, zip64_offset, 56, 56)
        values = struct.unpack_from("<4sQ2H2L4Q", record)
        if values[0] != b"PK\x06\x06" or values[4] or values[5]:
            raise ValueError("invalid ZIP64 end record")
        total, central_size, central_offset = values[7], values[8], values[9]
    elif disk_entries != total:
        raise ValueError("ZIP entry counts disagree")
    if not 0 < central_size <= MAX_CENTRAL_BYTES or central_offset + central_size > archive_size:
        raise ValueError("invalid or oversized ZIP central directory")
    central = archive_range(url, int(central_offset), int(central_size), MAX_CENTRAL_BYTES)
    members = []
    position = 0
    while position < len(central):
        fields = struct.unpack_from("<4s6H3L5H2L", central, position)
        if fields[0] != b"PK\x01\x02":
            raise ValueError("invalid central-directory member")
        flags, method, crc = fields[3], fields[4], fields[7]
        compressed, uncompressed = fields[8], fields[9]
        name_length, extra_length, comment_length, local_offset = fields[10], fields[11], fields[12], fields[16]
        end = position + 46 + name_length + extra_length + comment_length
        if end > len(central):
            raise ValueError("truncated central-directory member")
        name_raw = central[position + 46:position + 46 + name_length]
        extra = central[position + 46 + name_length:position + 46 + name_length + extra_length]
        if uncompressed == 0xFFFFFFFF or compressed == 0xFFFFFFFF or local_offset == 0xFFFFFFFF:
            u64, c64, o64 = zip64_values(extra, uncompressed == 0xFFFFFFFF, compressed == 0xFFFFFFFF, local_offset == 0xFFFFFFFF)
            uncompressed = u64 if u64 is not None else uncompressed
            compressed = c64 if c64 is not None else compressed
            local_offset = o64 if o64 is not None else local_offset
        encoding = "utf-8" if flags & 0x800 else "cp437"
        members.append({
            "name": name_raw.decode(encoding, "replace"), "flags": flags, "method": method,
            "crc32": crc, "compressed_size": compressed, "uncompressed_size": uncompressed,
            "local_offset": local_offset,
        })
        position = end
    if len(members) != total:
        raise ValueError(f"ZIP member count {len(members)} != {total}")
    return members


def extract_member(url: str, member: dict[str, object]) -> bytes:
    offset = int(member["local_offset"])
    fixed = archive_range(url, offset, 30, 30)
    fields = struct.unpack("<4s5H3L2H", fixed)
    if fields[0] != b"PK\x03\x04" or fields[2] != member["flags"] or fields[3] != member["method"]:
        raise ValueError("local and central ZIP headers disagree")
    flags, method, name_length, extra_length = fields[2], fields[3], fields[9], fields[10]
    if flags & 1 or method != 8:
        raise ValueError("member is encrypted or not Deflate-compressed")
    variable = archive_range(url, offset + 30, name_length + extra_length, 2 * 1024 * 1024)
    encoding = "utf-8" if flags & 0x800 else "cp437"
    if variable[:name_length].decode(encoding, "replace") != member["name"]:
        raise ValueError("local and central ZIP names disagree")
    compressed_size = int(member["compressed_size"])
    compressed = archive_range(
        url, offset + 30 + name_length + extra_length, compressed_size, MAX_COMPRESSED_MEMBER
    )
    raw = zlib.decompress(compressed, -15)
    if len(raw) != member["uncompressed_size"] or zlib.crc32(raw) & 0xFFFFFFFF != member["crc32"]:
        raise ValueError("inflated member failed size or CRC validation")
    return raw


def validate_record(record: dict[str, object]) -> None:
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict) or int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    license_info = metadata.get("license", {})
    if not isinstance(license_info, dict) or license_info.get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    description = re.sub(r"<[^>]+>", " ", str(metadata.get("description", ""))).lower()
    if "recording from a mouse" not in description or "open ephys (open ephys format)" not in description:
        raise SystemExit("record no longer documents the selected non-human Open Ephys session")
    files = record.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("Zenodo file inventory is malformed")
    items = {str(item.get("key", "")): item for item in files if isinstance(item, dict)}
    archive = items.get(ARCHIVE_NAME)
    if archive is None or int(archive.get("size", 0)) != ARCHIVE_SIZE or archive.get("checksum") != f"md5:{ARCHIVE_MD5}":
        raise SystemExit("pinned archive identity changed")


def parse_header(raw: bytes) -> dict[str, object]:
    text = raw.decode("ascii", "replace").rstrip("\x00 ")
    fields = {
        match.group(1): match.group(2).strip().strip("'")
        for match in re.finditer(r"header\.([A-Za-z0-9_]+)\s*=\s*([^;]*);", text)
    }
    try:
        result = {
            "channel": fields["channel"], "channel_type": fields["channelType"],
            "sample_rate_hz": float(fields["sampleRate"]), "bit_volts": float(fields["bitVolts"]),
            "block_length": int(float(fields["blockLength"])),
            "header_bytes": int(float(fields["header_bytes"])), "version": fields["version"],
        }
    except (KeyError, ValueError) as error:
        raise ValueError("invalid Open Ephys ASCII header") from error
    return result


def parse_records(raw: bytes) -> tuple[bytes, dict[str, object]]:
    if len(raw) != HEADER_BYTES + RECORD_COUNT * RECORD_BYTES:
        raise ValueError("fixed-record file geometry mismatch")
    payload = bytearray(PAYLOAD_BYTES)
    timestamps = []
    recording_numbers = set()
    bad_counts = bad_markers = 0
    for index in range(RECORD_COUNT):
        start = HEADER_BYTES + index * RECORD_BYTES
        timestamp, count, recording = struct.unpack_from("<qHH", raw, start)
        timestamps.append(timestamp)
        recording_numbers.add(recording)
        bad_counts += count != BLOCK_SAMPLES
        bad_markers += raw[start + RECORD_BYTES - 10:start + RECORD_BYTES] != MARKER
        output_start = index * BLOCK_SAMPLES * 2
        payload[output_start:output_start + BLOCK_SAMPLES * 2] = raw[start + 12:start + 12 + BLOCK_SAMPLES * 2]
    steps = [right - left for left, right in zip(timestamps, timestamps[1:])]
    report = {
        "bad_sample_counts": bad_counts, "bad_markers": bad_markers,
        "recording_numbers": sorted(recording_numbers), "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1], "minimum_timestamp_step": min(steps),
        "maximum_timestamp_step": max(steps),
        "timestamp_discontinuities": sum(step != BLOCK_SAMPLES for step in steps),
    }
    if bad_counts or bad_markers or report["timestamp_discontinuities"]:
        raise ValueError(f"invalid Open Ephys records: {report}")
    return bytes(payload), report


def decode_i16be(payload: bytes) -> array:
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "big":
        values.byteswap()
    return values


def source_for(download_dir: Path, channel: str) -> Path:
    return download_dir / f"100_{channel}.continuous"


def download(args: argparse.Namespace) -> None:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    record = json.loads(curl_bytes(RECORD_API, maximum=20_000_000))
    validate_record(record)
    members = remote_zip_members(ARCHIVE_URL, ARCHIVE_SIZE)
    if len(members) != 32:
        raise SystemExit(f"archive member count changed: {len(members)}")
    by_name = {str(member["name"]): member for member in members}
    inventory = []
    for number, profile in enumerate(CHANNELS, 1):
        channel, compressed_size, crc, source_sha, payload_sha = profile
        name = f"{MEMBER_PREFIX}{channel}.continuous"
        member = by_name.get(name)
        if member is None or (member["method"], member["compressed_size"], member["uncompressed_size"], f"{int(member['crc32']):08x}") != (8, compressed_size, SOURCE_BYTES, crc):
            raise SystemExit(f"pinned member identity changed: {channel}")
        target = source_for(args.download_dir, channel)
        raw = target.read_bytes() if target.is_file() else b""
        if hashlib.sha256(raw).hexdigest() != source_sha:
            print(f"[{number}/{len(CHANNELS)}] range-extracting {name}")
            raw = extract_member(ARCHIVE_URL, member)
            if hashlib.sha256(raw).hexdigest() != source_sha:
                raise SystemExit(f"source hash mismatch after extraction: {channel}")
            part = target.with_suffix(".continuous.part")
            part.write_bytes(raw)
            os.replace(part, target)
        else:
            print(f"[{number}/{len(CHANNELS)}] verified cached {target.name}")
        header = parse_header(raw[:HEADER_BYTES])
        if header != {"channel": channel, "channel_type": "Continuous", "sample_rate_hz": 30000.0, "bit_volts": 0.195, "block_length": 1024, "header_bytes": 1024, "version": "0.4"}:
            raise SystemExit(f"unexpected channel header: {channel}: {header}")
        payload, record_report = parse_records(raw)
        if hashlib.sha256(payload).hexdigest() != payload_sha:
            raise SystemExit(f"numeric payload hash mismatch: {channel}")
        inventory.append({
            "archive_name": ARCHIVE_NAME, "archive_size": ARCHIVE_SIZE, "archive_md5": ARCHIVE_MD5,
            "archive_url": ARCHIVE_URL, "member_name": name, "member_compression_method": 8,
            "member_compressed_size": compressed_size, "member_uncompressed_size": SOURCE_BYTES,
            "member_crc32": crc, "channel": channel, "sample_rate_hz": 30000,
            "bit_volts": 0.195, "record_count": RECORD_COUNT, "samples_per_record": BLOCK_SAMPLES,
            "continuous_sha256": source_sha, "numeric_payload_bytes": len(payload),
            "numeric_payload_sha256": payload_sha, "first_timestamp": record_report["first_timestamp"],
            "last_timestamp": record_report["last_timestamp"],
        })
    (args.download_dir / f"record_{RECORD_ID}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(f"validated {len(inventory)} channels totaling {len(CHANNELS) * PAYLOAD_BYTES} numeric bytes")


def local_record(download_dir: Path) -> None:
    path = download_dir / f"record_{RECORD_ID}.json"
    if not path.is_file():
        raise SystemExit("missing Zenodo metadata; run download.sh")
    validate_record(json.loads(path.read_text(encoding="utf-8")))


def parse_source(download_dir: Path, profile: tuple[object, ...]) -> tuple[dict[str, object], bytes, set[bytes]]:
    channel, _compressed, _crc, source_sha, payload_sha = profile
    path = source_for(download_dir, str(channel))
    raw = path.read_bytes() if path.is_file() else b""
    if len(raw) != SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != source_sha:
        raise SystemExit(f"missing or mismatched pinned source: {channel}")
    header = parse_header(raw[:HEADER_BYTES])
    if header["channel"] != channel or header["sample_rate_hz"] != 30000.0 or header["bit_volts"] != 0.195:
        raise SystemExit(f"source header changed: {channel}")
    payload, record_report = parse_records(raw)
    if len(payload) != PAYLOAD_BYTES or hashlib.sha256(payload).hexdigest() != payload_sha:
        raise SystemExit(f"decoded numeric payload changed: {channel}")
    values = decode_i16be(payload)
    block_hashes = set()
    minimum_distinct = BLOCK_SAMPLES
    minimum_transitions = BLOCK_SAMPLES
    constant_blocks = 0
    for index in range(RECORD_COUNT):
        value_start = index * BLOCK_SAMPLES
        value_end = value_start + BLOCK_SAMPLES
        block = values[value_start:value_end]
        distinct = len(set(block))
        transitions = sum(left != right for left, right in zip(block, block[1:]))
        minimum_distinct = min(minimum_distinct, distinct)
        minimum_transitions = min(minimum_transitions, transitions)
        constant_blocks += distinct == 1
        byte_start, byte_end = value_start * 2, value_end * 2
        block_hashes.add(hashlib.sha256(payload[byte_start:byte_end]).digest())
    report = {
        "channel": channel, "output_name": f"100_{channel}_i16be.bin",
        "sample_rate_hz": 30000, "bit_volts": 0.195, "record_count": RECORD_COUNT,
        "samples_per_record": BLOCK_SAMPLES, "value_count": len(values), "payload_bytes": len(payload),
        "minimum": min(values), "maximum": max(values), "zero_values": values.count(0),
        "minimum_saturation_values": values.count(-32768), "maximum_saturation_values": values.count(32767),
        "distinct_values": len(set(values)),
        "flattened_transitions": sum(left != right for left, right in zip(values, values[1:])),
        "minimum_block_distinct_values": minimum_distinct, "minimum_block_transitions": minimum_transitions,
        "constant_blocks": constant_blocks, "unique_block_payloads": len(block_hashes),
        "within_channel_duplicate_blocks": RECORD_COUNT - len(block_hashes),
        "numeric_payload_sha256": payload_sha, "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
        **record_report,
    }
    return report, payload, block_hashes


def scan(download_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    local_record(download_dir)
    reports = []
    channel_hashes = set()
    prior_blocks: set[bytes] = set()
    all_distinct: set[int] = set()
    timestamp_bounds = set()
    for profile in CHANNELS:
        report, payload, blocks = parse_source(download_dir, profile)
        payload_sha = str(report["numeric_payload_sha256"])
        if payload_sha in channel_hashes:
            raise SystemExit(f"duplicate channel payload: {report['channel']}")
        channel_hashes.add(payload_sha)
        cross_duplicates = len(blocks & prior_blocks)
        report["block_payloads_duplicated_from_prior_channels"] = cross_duplicates
        if report["constant_blocks"] or report["within_channel_duplicate_blocks"] or cross_duplicates:
            raise SystemExit(f"constant or duplicate blocks in {report['channel']}")
        prior_blocks.update(blocks)
        values = decode_i16be(payload)
        all_distinct.update(values)
        timestamp_bounds.add((report["first_timestamp"], report["last_timestamp"]))
        reports.append(report)
    if len(timestamp_bounds) != 1:
        raise SystemExit("selected channels are not synchronized")
    ratios = [float(report["zlib_ratio"]) for report in reports]
    total_values = sum(int(report["value_count"]) for report in reports)
    total_zero = sum(int(report["zero_values"]) for report in reports)
    bounds = next(iter(timestamp_bounds))
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "record_id": RECORD_ID, "license": "cc-by-4.0",
        "channel_count": len(reports), "channels": [report["channel"] for report in reports],
        "sample_rate_hz": 30000, "records_per_channel": RECORD_COUNT,
        "samples_per_record": BLOCK_SAMPLES, "values_per_channel": PAYLOAD_BYTES // 2,
        "value_count": total_values, "total_size_bytes": sum(int(r["payload_bytes"]) for r in reports),
        "global_minimum": min(int(r["minimum"]) for r in reports), "global_maximum": max(int(r["maximum"]) for r in reports),
        "global_distinct_values": len(all_distinct), "zero_values": total_zero,
        "zero_fraction": round(total_zero / total_values, 9),
        "minimum_saturation_values": sum(int(r["minimum_saturation_values"]) for r in reports),
        "maximum_saturation_values": sum(int(r["maximum_saturation_values"]) for r in reports),
        "minimum_block_distinct_values": min(int(r["minimum_block_distinct_values"]) for r in reports),
        "minimum_block_transitions": min(int(r["minimum_block_transitions"]) for r in reports),
        "unique_channel_payloads": len(channel_hashes), "unique_block_payloads": len(prior_blocks),
        "within_channel_duplicate_blocks": sum(int(r["within_channel_duplicate_blocks"]) for r in reports),
        "cross_channel_duplicate_blocks": sum(int(r["block_payloads_duplicated_from_prior_channels"]) for r in reports),
        "first_timestamp": bounds[0], "last_timestamp": bounds[1],
        "minimum_zlib_ratio": min(ratios), "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios), "profiles": reports,
    }
    expected = {
        "channel_count": 4, "channels": ["CH1", "CH6", "CH11", "CH16"],
        "value_count": 266375168, "total_size_bytes": 532750336,
        "global_minimum": -32767, "global_maximum": 32767, "global_distinct_values": 65534,
        "zero_values": 138005, "zero_fraction": 0.000518085,
        "minimum_saturation_values": 0, "maximum_saturation_values": 60497,
        "minimum_block_distinct_values": 24, "minimum_block_transitions": 27,
        "unique_channel_payloads": 4, "unique_block_payloads": 260132,
        "within_channel_duplicate_blocks": 0, "cross_channel_duplicate_blocks": 0,
        "first_timestamp": 107400, "last_timestamp": 66700168,
        "minimum_zlib_ratio": 0.788310403, "median_zlib_ratio": 0.8162462804999999,
        "maximum_zlib_ratio": 0.853942519,
    }
    for key, value in expected.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {summary[key]} != {value}")
    return reports, summary


def public_summary(summary: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in summary.items() if key != "profiles"}


def inspect(args: argparse.Namespace) -> None:
    _reports, summary = scan(args.download_dir)
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, summary = scan(args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report in reports:
        raw = source_for(args.download_dir, str(report["channel"])).read_bytes()
        payload, _record_report = parse_records(raw)
        output = series_dir / str(report["output_name"])
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"downloads/{DATASET_ID}/100_{report['channel']}.continuous",
            "channel": report["channel"], "sample_rate_hz": 30000, "bit_volts": 0.195,
            "numeric_kind": "int", "bit_width": 16, "endianness": "big", "element_size_bytes": 2,
            "value_count": report["value_count"], "sample_size_bytes": report["payload_bytes"],
            "sample_format": "raw homogeneous big-endian signed-int16 extracellular voltage stream",
            "sample_geometry": "1d_continuous_extracellular_voltage_channel", "sample_rank": 1,
            "sample_shape": [report["value_count"]], "sample_axes": ["time_sample"],
            "natural_record_kind": "complete_open_ephys_channel_stream",
            "minimum": report["minimum"], "maximum": report["maximum"],
            "sha256": report["numeric_payload_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(args: argparse.Namespace) -> None:
    reports, summary = scan(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(reports):
        raise SystemExit("unexpected index row count")
    expected_outputs = set()
    for row, report in zip(rows, reports, strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("channel") != report["channel"]:
            raise SystemExit(f"indexed identity mismatch: {report['channel']}")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 16 or row.get("endianness") != "big":
            raise SystemExit(f"indexed representation mismatch: {report['channel']}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.stat().st_size != PAYLOAD_BYTES or file_hash(output) != report["numeric_payload_sha256"]:
            raise SystemExit(f"output is not byte-identical to decoded source: {report['channel']}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs or json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("sample inventory or stored statistics changed")
    print(json.dumps({
        "dataset_id": DATASET_ID, "verified_samples": len(rows),
        "verified_values": summary["value_count"], "verified_bytes": summary["total_size_bytes"],
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
