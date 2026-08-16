#!/usr/bin/env python3
from __future__ import annotations

import argparse
import array
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
import zipfile


DATASET_ID = "openslr_rirs_noises_pcm16"
SERIES_ID = "measured_room_impulse_response_i16"
ARCHIVE_NAME = "rirs_noises.zip"
ARCHIVE_SHA256 = "3b50cfde915b3984738169b4beb341e9f6b8062ae4c2076146c5db71c2c05dc7"
ARCHIVE_SIZE = 1_311_166_223
ZIP_MEMBER_COUNT = 61_880
SOURCE_WAV_COUNT = 325
SAMPLE_COUNT = 3_810
PRIMARY_BYTES = 133_959_032
PRIMARY_VALUES = PRIMARY_BYTES // 2
SOURCE_WAV_BYTES = 133_979_812
SAMPLE_RATE = 16_000
PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
PREFIX = "RIRS_NOISES/real_rirs_isotropic_noises/"
PATTERNS = (
    ("AIR", re.compile(r"^air_type1_air_")),
    ("REVERB2014", re.compile(r"^RVB2014_type[12]_rir_")),
    ("RWCP", re.compile(r"^RWCP_type[1-4]_rir_")),
)
EXPECTED_SOURCE_COUNTS = {"AIR": 107, "REVERB2014": 36, "RWCP": 182}
EXPECTED_SAMPLE_COUNTS = {"AIR": 214, "REVERB2014": 288, "RWCP": 3308}
EXPECTED_SAMPLE_BYTES = {"AIR": 18_158_048, "REVERB2014": 9_216_000, "RWCP": 106_584_984}
EXPECTED_CHANNEL_LAYOUTS = {1: 38, 2: 107, 8: 36, 16: 75, 30: 69}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def family_for_path(path: str) -> str | None:
    if not path.startswith(PREFIX):
        return None
    name = PurePosixPath(path).name
    return next((label for label, pattern in PATTERNS if pattern.match(name)), None)


def validate_archive(archive: Path) -> list[tuple[str, zipfile.ZipInfo]]:
    if not archive.is_file() or archive.stat().st_size != ARCHIVE_SIZE:
        raise ValueError(f"missing or wrong-sized archive: {archive}")
    actual_hash = hash_file(archive)
    if actual_hash != ARCHIVE_SHA256:
        raise ValueError(f"archive SHA-256 mismatch: {actual_hash}")
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
    paths = [info.filename for info in infos]
    if len(infos) != ZIP_MEMBER_COUNT or len(set(paths)) != len(paths):
        raise ValueError("unexpected ZIP member count or duplicate member path")
    selected: list[tuple[str, zipfile.ZipInfo]] = []
    for info in infos:
        family = family_for_path(info.filename)
        if family is None or info.is_dir():
            continue
        if info.flag_bits & 1:
            raise ValueError(f"encrypted selected member: {info.filename}")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ValueError(f"unsupported compression method: {info.filename}")
        selected.append((family, info))
    selected.sort(key=lambda item: item[1].filename)
    counts = Counter(family for family, _ in selected)
    if counts != EXPECTED_SOURCE_COUNTS or len(selected) != SOURCE_WAV_COUNT:
        raise ValueError(f"selected source mismatch: counts={dict(counts)}")
    if sum(info.file_size for _, info in selected) != SOURCE_WAV_BYTES:
        raise ValueError("selected source WAV byte total changed")
    return selected


def parse_wav(raw: bytes, source_path: str) -> tuple[int, int, bytes, int]:
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"not a little-endian RIFF/WAVE file: {source_path}")
    if struct.unpack_from("<I", raw, 4)[0] + 8 != len(raw):
        raise ValueError(f"RIFF size mismatch: {source_path}")

    offset = 12
    chunks: list[bytes] = []
    fmt_payload: bytes | None = None
    fact_frames: int | None = None
    pcm: bytes | None = None
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise ValueError(f"truncated chunk header: {source_path}")
        chunk_id = raw[offset : offset + 4]
        size = struct.unpack_from("<I", raw, offset + 4)[0]
        start = offset + 8
        end = start + size
        if end > len(raw):
            raise ValueError(f"truncated chunk: {source_path} {chunk_id!r}")
        payload = raw[start:end]
        chunks.append(chunk_id)
        if chunk_id == b"fmt ":
            if fmt_payload is not None:
                raise ValueError(f"duplicate fmt chunk: {source_path}")
            fmt_payload = payload
        elif chunk_id == b"fact":
            if fact_frames is not None or len(payload) < 4:
                raise ValueError(f"invalid fact chunk: {source_path}")
            fact_frames = struct.unpack_from("<I", payload)[0]
        elif chunk_id == b"data":
            if pcm is not None:
                raise ValueError(f"duplicate data chunk: {source_path}")
            pcm = payload
        else:
            raise ValueError(f"unexpected WAV chunk {chunk_id!r}: {source_path}")
        offset = end + (size & 1)
    if offset != len(raw) or chunks not in ([b"fmt ", b"data"], [b"fmt ", b"fact", b"data"]):
        raise ValueError(f"unexpected WAV chunk layout: {source_path} {chunks!r}")
    if fmt_payload is None or pcm is None or len(fmt_payload) < 16:
        raise ValueError(f"missing fmt or data chunk: {source_path}")

    tag, channels, rate, byte_rate, block_align, bits = struct.unpack_from("<HHIIHH", fmt_payload)
    valid_bits = bits
    if tag == 0xFFFE:
        if len(fmt_payload) < 40 or struct.unpack_from("<H", fmt_payload, 16)[0] < 22:
            raise ValueError(f"truncated WAVE_FORMAT_EXTENSIBLE fmt: {source_path}")
        valid_bits = struct.unpack_from("<H", fmt_payload, 18)[0]
        if fmt_payload[24:40] != PCM_GUID:
            raise ValueError(f"non-PCM extensible subformat: {source_path}")
    elif tag != 1:
        raise ValueError(f"non-PCM WAV format tag {tag}: {source_path}")
    if bits != 16 or valid_bits != 16:
        raise ValueError(f"non-PCM16 WAV: {source_path}")
    if rate != SAMPLE_RATE or channels not in EXPECTED_CHANNEL_LAYOUTS:
        raise ValueError(f"unexpected rate/channels: {source_path} rate={rate} channels={channels}")
    if block_align != channels * 2 or byte_rate != rate * block_align:
        raise ValueError(f"inconsistent WAV format geometry: {source_path}")
    if not pcm or len(pcm) % block_align:
        raise ValueError(f"empty or unaligned WAV payload: {source_path}")
    frames = len(pcm) // block_align
    if fact_frames is not None and fact_frames != frames:
        raise ValueError(f"fact/data frame mismatch: {source_path}")
    return channels, frames, pcm, tag


def decode_le_i16(payload: bytes) -> array.array[int]:
    if len(payload) % 2:
        raise ValueError("odd-length int16 payload")
    values = array.array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def encode_le_i16(values: array.array[int]) -> bytes:
    if values.typecode != "h" or values.itemsize != 2:
        raise ValueError("expected native signed-int16 array")
    if sys.byteorder == "little":
        return values.tobytes()
    copy = array.array("h", values)
    copy.byteswap()
    return copy.tobytes()


def build(args: argparse.Namespace) -> None:
    archive = args.download_dir / ARCHIVE_NAME
    selected = validate_archive(archive)
    out_dir = args.samples_root / SERIES_ID
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    source_counts: Counter[str] = Counter()
    sample_counts: Counter[str] = Counter()
    sample_bytes: Counter[str] = Counter()
    channel_layouts: Counter[int] = Counter()
    frame_lengths: Counter[int] = Counter()
    output_hashes: set[str] = set()

    with zipfile.ZipFile(archive) as source:
        for family, info in selected:
            raw = source.read(info)
            channels, frames, pcm, format_tag = parse_wav(raw, info.filename)
            values = decode_le_i16(pcm)
            if len(values) != channels * frames:
                raise ValueError(f"decoded value count mismatch: {info.filename}")
            source_counts[family] += 1
            channel_layouts[channels] += 1
            for channel_index in range(channels):
                channel = array.array("h", values[channel_index::channels])
                if len(channel) != frames:
                    raise ValueError(f"deinterleave mismatch: {info.filename}")
                minimum, maximum = min(channel), max(channel)
                if minimum == maximum:
                    raise ValueError(f"constant channel: {info.filename} channel={channel_index}")
                payload = encode_le_i16(channel)
                sha256 = hashlib.sha256(payload).hexdigest()
                if sha256 in output_hashes:
                    raise ValueError(f"duplicate output channel: {info.filename} channel={channel_index}")
                output_hashes.add(sha256)
                stem = PurePosixPath(info.filename).stem
                output_name = f"{family.lower()}__{stem}__ch{channel_index + 1:02d}.bin"
                output = out_dir / output_name
                if output.exists():
                    raise ValueError(f"output name collision: {output_name}")
                output.write_bytes(payload)
                row = {
                    "dataset_id": DATASET_ID,
                    "series_id": SERIES_ID,
                    "role": "primary",
                    "sample_path": output.relative_to(args.data_root).as_posix(),
                    "numeric_kind": "int",
                    "bit_width": 16,
                    "endianness": "little",
                    "element_size_bytes": 2,
                    "sample_size_bytes": len(payload),
                    "value_count": frames,
                    "sample_format": "raw homogeneous little-endian signed-int16 acoustic impulse-response array",
                    "sample_geometry": "variable_length_room_impulse_response_1d",
                    "sample_rank": 1,
                    "sample_shape": [frames],
                    "sample_axes": ["time_sample"],
                    "natural_record_kind": "complete_measured_room_impulse_response_wav_channel",
                    "sample_rate_hz": SAMPLE_RATE,
                    "source_family": family,
                    "source_wav": info.filename,
                    "source_crc32": f"{info.CRC:08x}",
                    "source_format_tag": format_tag,
                    "source_channel_count": channels,
                    "source_channel_index": channel_index,
                    "min": int(minimum),
                    "max": int(maximum),
                    "sha256": sha256,
                }
                rows.append(row)
                sample_counts[family] += 1
                sample_bytes[family] += len(payload)
                frame_lengths[frames] += 1

    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    total_values = sum(int(row["value_count"]) for row in rows)
    if source_counts != EXPECTED_SOURCE_COUNTS:
        raise ValueError(f"source-family count drift: {dict(source_counts)}")
    if sample_counts != EXPECTED_SAMPLE_COUNTS or sample_bytes != EXPECTED_SAMPLE_BYTES:
        raise ValueError(f"output-family aggregate drift: counts={dict(sample_counts)} bytes={dict(sample_bytes)}")
    if channel_layouts != EXPECTED_CHANNEL_LAYOUTS:
        raise ValueError(f"channel-layout drift: {dict(channel_layouts)}")
    if len(rows) != SAMPLE_COUNT or total_bytes != PRIMARY_BYTES or total_values != PRIMARY_VALUES:
        raise ValueError(
            f"output aggregate drift: samples={len(rows)} values={total_values} bytes={total_bytes}"
        )

    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "archive_sha256": ARCHIVE_SHA256,
        "source_wav_count": sum(source_counts.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "source_channel_layouts": {str(key): value for key, value in sorted(channel_layouts.items())},
        "sample_count": len(rows),
        "sample_counts": dict(sorted(sample_counts.items())),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "sample_bytes": dict(sorted(sample_bytes.items())),
        "frame_length_min": min(frame_lengths),
        "frame_length_max": max(frame_lengths),
        "distinct_frame_lengths": len(frame_lengths),
        "frame_length_counts": {str(key): value for key, value in sorted(frame_lengths.items())},
        "all_samples_nonconstant": True,
        "all_sample_hashes_unique": True,
    }
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built_samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes} "
        f"length_range={min(frame_lengths)}..{max(frame_lengths)}"
    )


def verify(args: argparse.Namespace) -> None:
    validate_archive(args.download_dir / ARCHIVE_NAME)
    if not args.index.is_file() or not args.stats.is_file():
        raise ValueError("missing sample index or ingest stats")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    stats = json.loads(args.stats.read_text())
    if len(rows) != SAMPLE_COUNT or int(stats.get("sample_count", -1)) != SAMPLE_COUNT:
        raise ValueError("sample count mismatch")

    expected_prefix = f"samples/{DATASET_ID}/{SERIES_ID}/"
    indexed_paths: set[str] = set()
    hashes: set[str] = set()
    family_counts: Counter[str] = Counter()
    family_bytes: Counter[str] = Counter()
    channel_layouts: Counter[int] = Counter()
    source_channels: dict[str, set[int]] = {}
    source_channel_counts: dict[str, int] = {}
    total_values = 0
    total_bytes = 0
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise ValueError(f"unexpected row identity: {row}")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 16 or row.get("endianness") != "little":
            raise ValueError(f"unexpected numeric representation: {row}")
        sample_path = str(row.get("sample_path", ""))
        if not sample_path.startswith(expected_prefix) or sample_path in indexed_paths:
            raise ValueError(f"invalid or duplicate sample path: {sample_path}")
        indexed_paths.add(sample_path)
        path = args.data_root / sample_path
        if not path.is_file():
            raise ValueError(f"missing sample: {path}")
        payload = path.read_bytes()
        values = decode_le_i16(payload)
        count = int(row.get("value_count", -1))
        if len(payload) != int(row.get("sample_size_bytes", -1)) or len(values) != count:
            raise ValueError(f"sample size mismatch: {path}")
        if row.get("sample_shape") != [count] or row.get("sample_rank") != 1 or row.get("sample_axes") != ["time_sample"]:
            raise ValueError(f"sample geometry mismatch: {path}")
        if row.get("sample_geometry") != "variable_length_room_impulse_response_1d":
            raise ValueError(f"sample geometry class mismatch: {path}")
        if row.get("natural_record_kind") != "complete_measured_room_impulse_response_wav_channel":
            raise ValueError(f"natural boundary mismatch: {path}")
        if int(row.get("sample_rate_hz", 0)) != SAMPLE_RATE:
            raise ValueError(f"sample rate mismatch: {path}")
        sha256 = hashlib.sha256(payload).hexdigest()
        if sha256 != row.get("sha256") or sha256 in hashes:
            raise ValueError(f"sample hash mismatch or duplicate: {path}")
        hashes.add(sha256)
        if min(values) != row.get("min") or max(values) != row.get("max") or min(values) == max(values):
            raise ValueError(f"sample extrema mismatch or constant sample: {path}")
        family = str(row.get("source_family"))
        if family not in EXPECTED_SOURCE_COUNTS:
            raise ValueError(f"unknown source family: {family}")
        source_wav = str(row.get("source_wav", ""))
        if family_for_path(source_wav) != family:
            raise ValueError(f"source selection mismatch: {source_wav}")
        source_channel_count = int(row.get("source_channel_count", -1))
        source_channel_index = int(row.get("source_channel_index", -1))
        if not 0 <= source_channel_index < source_channel_count:
            raise ValueError(f"source channel index mismatch: {path}")
        previous_count = source_channel_counts.setdefault(source_wav, source_channel_count)
        if previous_count != source_channel_count:
            raise ValueError(f"inconsistent source channel count: {source_wav}")
        channels = source_channels.setdefault(source_wav, set())
        if source_channel_index in channels:
            raise ValueError(f"duplicate source channel: {source_wav} {source_channel_index}")
        channels.add(source_channel_index)
        family_counts[family] += 1
        family_bytes[family] += len(payload)
        total_values += count
        total_bytes += len(payload)

    if any(len(channels) != source_channel_counts[path] for path, channels in source_channels.items()):
        raise ValueError("incomplete source-channel coverage")
    for path, count in source_channel_counts.items():
        channel_layouts[count] += 1
    if len(source_channels) != SOURCE_WAV_COUNT or channel_layouts != EXPECTED_CHANNEL_LAYOUTS:
        raise ValueError(f"source coverage drift: sources={len(source_channels)} layouts={dict(channel_layouts)}")
    if family_counts != EXPECTED_SAMPLE_COUNTS or family_bytes != EXPECTED_SAMPLE_BYTES:
        raise ValueError(f"family aggregate drift: counts={dict(family_counts)} bytes={dict(family_bytes)}")
    if total_values != PRIMARY_VALUES or total_bytes != PRIMARY_BYTES:
        raise ValueError(f"primary aggregate drift: values={total_values} bytes={total_bytes}")

    actual_paths = {
        path.relative_to(args.data_root).as_posix()
        for path in (args.samples_root / SERIES_ID).rglob("*")
        if path.is_file()
    }
    if actual_paths != indexed_paths:
        raise ValueError("sample directory and index differ")
    if stats.get("archive_sha256") != ARCHIVE_SHA256 or int(stats.get("primary_bytes", -1)) != PRIMARY_BYTES:
        raise ValueError("ingest stats mismatch")
    print(
        f"verified_samples={len(rows)} source_wavs={len(source_channels)} "
        f"primary_values={total_values} primary_bytes={total_bytes} unique_hashes={len(hashes)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args)
        else:
            verify(args)
    except (OSError, ValueError, zipfile.BadZipFile, struct.error) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
