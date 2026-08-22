#!/usr/bin/env python3
"""Preflight, decode, build, and verify BBBC007 uint8 TIFF planes."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import struct
import zipfile


DATASET_ID = "bbbc007_fluorescence_u8"
SERIES_ID = "bbbc007_microscopy_plane_u8"
EXPECTED_ARCHIVE_SIZE = 6_435_776
EXPECTED_ARCHIVE_SHA256 = "b7009e2fce0a3152a5c9adda916eaa699d09696f4bd02a7d05d12d041e30c6d1"
EXPECTED_RIGHTS_SIZE = 32_288
EXPECTED_RIGHTS_SHA256 = "374180e569bcfb2f3b61783e8e52172bd333aecc79faf2348dba6121573ddd7e"
MIN_IMAGES = 30
MAX_IMAGES = 40
MIN_SAMPLES = 40
MAX_SAMPLES = 70
MIN_VALUES_PER_SAMPLE = 100_000
MIN_TOTAL_VALUES = 1_000_000
MAX_TOTAL_BYTES = 100_000_000
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_archive_identity(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing archive: {path}")
    actual_size = path.stat().st_size
    actual_hash = file_hash(path)
    if actual_size != EXPECTED_ARCHIVE_SIZE or actual_hash != EXPECTED_ARCHIVE_SHA256:
        raise SystemExit(f"archive identity mismatch: size={actual_size} sha256={actual_hash}")


def validate_rights(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing official BBBC007 page: {path}")
    actual_size = path.stat().st_size
    actual_hash = file_hash(path)
    if actual_size != EXPECTED_RIGHTS_SIZE or actual_hash != EXPECTED_RIGHTS_SHA256:
        raise SystemExit(f"rights-page identity mismatch: size={actual_size} sha256={actual_hash}")
    text = html.unescape(path.read_text(encoding="utf-8", errors="replace")).lower()
    text = re.sub(r"\s+", " ", text)
    if "bbbc007" not in text:
        raise SystemExit("official page does not identify BBBC007")
    license_terms = (
        "creativecommons.org/publicdomain/zero/1.0",
        "waived all copyright and related or neighboring rights",
        "cc0",
    )
    if not all(term in text for term in license_terms[:2]):
        raise SystemExit("official BBBC007 page lacks explicit CC0 waiver evidence")


def unpack_values(raw: bytes, endian: str, field_type: int, count: int, value_field: bytes) -> tuple[int, ...]:
    if field_type not in (1, 3, 4):
        raise ValueError(f"unsupported required TIFF field type {field_type}")
    size = TYPE_SIZES[field_type] * count
    if size <= 4:
        payload = value_field[:size]
    else:
        offset = struct.unpack(endian + "I", value_field)[0]
        if offset + size > len(raw):
            raise ValueError("TIFF tag value lies outside file")
        payload = raw[offset : offset + size]
    code = {1: "B", 3: "H", 4: "I"}[field_type]
    return tuple(struct.unpack(endian + str(count) + code, payload))


def read_tags(raw: bytes) -> tuple[str, dict[int, tuple[int, ...]]]:
    if len(raw) < 8 or raw[:2] not in (b"II", b"MM"):
        raise ValueError("not a byte-ordered TIFF")
    endian = "<" if raw[:2] == b"II" else ">"
    if struct.unpack_from(endian + "H", raw, 2)[0] != 42:
        raise ValueError("unsupported TIFF magic")
    ifd_offset = struct.unpack_from(endian + "I", raw, 4)[0]
    if ifd_offset + 2 > len(raw):
        raise ValueError("TIFF IFD offset outside file")
    entry_count = struct.unpack_from(endian + "H", raw, ifd_offset)[0]
    end_entries = ifd_offset + 2 + entry_count * 12
    if end_entries + 4 > len(raw):
        raise ValueError("truncated TIFF IFD")
    tags: dict[int, tuple[int, ...]] = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, field_type, count = struct.unpack_from(endian + "HHI", raw, offset)
        if count > 10_000_000 or field_type not in TYPE_SIZES:
            raise ValueError(f"invalid TIFF tag {tag}")
        if tag in {256, 257, 258, 259, 262, 266, 273, 274, 277, 278, 279, 284, 317, 339}:
            tags[tag] = unpack_values(raw, endian, field_type, count, raw[offset + 8 : offset + 12])
    if struct.unpack_from(endian + "I", raw, end_entries)[0] != 0:
        raise ValueError("multi-image TIFF is outside recipe scope")
    return endian, tags


def one(tags: dict[int, tuple[int, ...]], tag: int, default: int | None = None) -> int:
    values = tags.get(tag)
    if values is None:
        if default is None:
            raise ValueError(f"missing required TIFF tag {tag}")
        return default
    if len(values) != 1:
        raise ValueError(f"TIFF tag {tag} must contain one value")
    return values[0]


def decode_packbits(payload: bytes, expected: int) -> bytes:
    output = bytearray()
    cursor = 0
    while cursor < len(payload):
        control = payload[cursor]
        cursor += 1
        if control <= 127:
            count = control + 1
            if cursor + count > len(payload):
                raise ValueError("truncated PackBits literal")
            output.extend(payload[cursor : cursor + count])
            cursor += count
        elif control >= 129:
            if cursor >= len(payload):
                raise ValueError("truncated PackBits repeat")
            output.extend(payload[cursor : cursor + 1] * (257 - control))
            cursor += 1
        if len(output) > expected:
            raise ValueError("PackBits strip expands past expected size")
    if len(output) != expected:
        raise ValueError(f"PackBits strip size mismatch: {len(output)} != {expected}")
    return bytes(output)


def decode_tiff(raw: bytes, member: str) -> tuple[list[bytes], dict[str, object]]:
    endian, tags = read_tags(raw)
    width = one(tags, 256)
    height = one(tags, 257)
    samples_per_pixel = one(tags, 277, 1)
    bits = tags.get(258, (1,))
    compression = one(tags, 259, 1)
    photometric = one(tags, 262)
    rows_per_strip = one(tags, 278, height)
    if not 100 <= width <= 4096 or not 100 <= height <= 4096:
        raise ValueError(f"implausible dimensions {width}x{height}")
    if samples_per_pixel not in (1, 3) or bits not in ((8,), (8, 8, 8)):
        raise ValueError(f"not unsigned 8-bit grayscale/RGB: bits={bits} spp={samples_per_pixel}")
    if (samples_per_pixel == 1 and photometric not in (0, 1)) or (samples_per_pixel == 3 and photometric != 2):
        raise ValueError(f"unsupported photometric interpretation {photometric}")
    if compression not in (1, 32773):
        raise ValueError(f"unsupported TIFF compression {compression}")
    if one(tags, 266, 1) != 1 or one(tags, 274, 1) != 1 or one(tags, 284, 1) != 1:
        raise ValueError("unsupported fill order, orientation, or planar layout")
    if one(tags, 317, 1) != 1:
        raise ValueError("TIFF predictor is outside recipe scope")
    sample_format = tags.get(339, (1,) * samples_per_pixel)
    if sample_format not in ((1,), (1, 1, 1)):
        raise ValueError(f"not unsigned-integer SampleFormat: {sample_format}")
    offsets = tags.get(273)
    byte_counts = tags.get(279)
    if not offsets or not byte_counts or len(offsets) != len(byte_counts):
        raise ValueError("invalid TIFF strip tables")
    expected_strips = math.ceil(height / rows_per_strip)
    if len(offsets) != expected_strips or rows_per_strip <= 0:
        raise ValueError("TIFF strip count disagrees with row geometry")
    raster = bytearray()
    for strip_index, (offset, byte_count) in enumerate(zip(offsets, byte_counts, strict=True)):
        if offset + byte_count > len(raw):
            raise ValueError("TIFF strip lies outside file")
        rows = min(rows_per_strip, height - strip_index * rows_per_strip)
        expected = rows * width * samples_per_pixel
        encoded = raw[offset : offset + byte_count]
        if compression == 1:
            if len(encoded) != expected:
                raise ValueError(f"uncompressed strip size mismatch: {len(encoded)} != {expected}")
            decoded = encoded
        else:
            decoded = decode_packbits(encoded, expected)
        raster.extend(decoded)
    expected_raster = width * height * samples_per_pixel
    if len(raster) != expected_raster:
        raise ValueError("decoded TIFF raster size mismatch")
    if samples_per_pixel == 1:
        planes = [bytes(raster)]
        channel_names = ["gray"]
    else:
        planes = [bytes(raster[index::3]) for index in range(3)]
        channel_names = ["red", "green", "blue"]
    if any(len(plane) < MIN_VALUES_PER_SAMPLE or len(set(plane)) < 2 for plane in planes):
        raise ValueError("short or constant microscopy plane")
    return planes, {
        "source_member": member,
        "source_size_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "tiff_byte_order": "little" if endian == "<" else "big",
        "width": width,
        "height": height,
        "samples_per_pixel": samples_per_pixel,
        "channel_names": channel_names,
        "compression": "none" if compression == 1 else "packbits",
        "strip_count": len(offsets),
    }


def scan_archive(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    validate_archive_identity(path)
    if not zipfile.is_zipfile(path):
        raise SystemExit("pinned source is not a ZIP archive")
    samples: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []
    seen: dict[str, tuple[str, int]] = {}
    image_count = 0
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"ZIP CRC failure: {bad}")
        total_uncompressed = 0
        members = []
        for info in archive.infolist():
            member_path = PurePosixPath(info.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise SystemExit(f"unsafe ZIP member: {info.filename}")
            if info.flag_bits & 1:
                raise SystemExit(f"encrypted ZIP member: {info.filename}")
            total_uncompressed += info.file_size
            if total_uncompressed > 100_000_000:
                raise SystemExit("uncompressed archive exceeds 100 MB")
            if not info.is_dir() and member_path.suffix.lower() in {".tif", ".tiff"}:
                members.append(info)
        members.sort(key=lambda info: info.filename)
        if not MIN_IMAGES <= len(members) <= MAX_IMAGES:
            raise SystemExit(f"TIFF image count outside bounds: {len(members)}")
        for image_index, info in enumerate(members):
            raw = archive.read(info)
            try:
                planes, metadata = decode_tiff(raw, info.filename)
            except ValueError as exc:
                raise SystemExit(f"TIFF decode failed for {info.filename}: {exc}") from exc
            image_count += 1
            for channel_index, (channel_name, payload) in enumerate(
                zip(metadata["channel_names"], planes, strict=True)
            ):
                digest = hashlib.sha256(payload).hexdigest()
                if digest in seen:
                    kept_member, kept_channel = seen[digest]
                    duplicates.append({
                        "source_member": info.filename,
                        "channel_index": channel_index,
                        "channel_name": channel_name,
                        "sha256": digest,
                        "kept_source_member": kept_member,
                        "kept_channel_index": kept_channel,
                    })
                    continue
                seen[digest] = (info.filename, channel_index)
                samples.append({
                    "payload": payload,
                    "image_index": image_index,
                    "channel_index": channel_index,
                    "channel_name": channel_name,
                    **metadata,
                })
    if not MIN_SAMPLES <= len(samples) <= MAX_SAMPLES:
        raise SystemExit(f"unique plane count outside bounds: {len(samples)}")
    lengths = [len(sample["payload"]) for sample in samples]
    if sum(lengths) < MIN_TOTAL_VALUES or statistics.median(lengths) < MIN_VALUES_PER_SAMPLE:
        raise SystemExit("decoded primary payload does not meet acceptance floors")
    if sum(lengths) > MAX_TOTAL_BYTES:
        raise SystemExit("decoded primary payload exceeds 100 MB")
    return samples, duplicates, image_count


def summary(samples: list[dict[str, object]], duplicates: list[dict[str, object]], image_count: int) -> dict[str, object]:
    lengths = [len(sample["payload"]) for sample in samples]
    dimensions: dict[str, int] = {}
    compressions: dict[str, int] = {}
    for sample in samples:
        geometry = f"{sample['width']}x{sample['height']}"
        dimensions[geometry] = dimensions.get(geometry, 0) + 1
        compression = str(sample["compression"])
        compressions[compression] = compressions.get(compression, 0) + 1
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_image_count": image_count,
        "sample_count": len(samples),
        "duplicate_plane_count": len(duplicates),
        "value_count": sum(lengths),
        "total_size_bytes": sum(lengths),
        "minimum_sample_value_count": min(lengths),
        "median_sample_value_count": statistics.median(lengths),
        "maximum_sample_value_count": max(lengths),
        "sample_geometry_counts": dict(sorted(dimensions.items())),
        "source_compression_sample_counts": dict(sorted(compressions.items())),
        "duplicate_planes": duplicates,
    }


def slug(index: int, member: str, channel: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", str(PurePosixPath(member).with_suffix("")).lower()).strip("_")[-70:]
    suffix = hashlib.sha256((member + "\0" + channel).encode()).hexdigest()[:8]
    return f"image_{index:03d}_{stem}_{channel}_{suffix}"


def preflight(args: argparse.Namespace) -> None:
    validate_rights(args.rights)
    samples, duplicates, image_count = scan_archive(args.archive)
    result = {
        **summary(samples, duplicates, image_count),
        "license": "CC0 1.0",
        "archive_size_bytes": args.archive.stat().st_size,
        "archive_sha256": file_hash(args.archive),
        "rights_size_bytes": args.rights.stat().st_size,
        "rights_sha256": file_hash(args.rights),
    }
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    samples, duplicates, image_count = scan_archive(args.archive)
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for sample_index, sample in enumerate(samples):
        payload = sample["payload"]
        name = slug(sample_index, str(sample["source_member"]), str(sample["channel_name"]))
        output = series_dir / f"{name}_u8_{sample['width']}x{sample['height']}.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": args.archive.relative_to(args.data_root).as_posix(),
            "source_member": sample["source_member"],
            "source_member_sha256": sample["source_sha256"],
            "image_index": sample["image_index"],
            "channel_index": sample["channel_index"],
            "channel_name": sample["channel_name"],
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": len(payload),
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous uint8 microscopy intensity plane",
            "sample_geometry": "2d_microscopy_intensity_plane",
            "sample_rank": 2,
            "sample_shape": [sample["height"], sample["width"]],
            "sample_axes": ["image_y", "image_x"],
            "natural_record_kind": "decoded_tiff_microscopy_image_plane",
            "minimum": min(payload),
            "maximum": max(payload),
            "distinct_values": len(set(payload)),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = summary(samples, duplicates, image_count)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    samples, duplicates, image_count = scan_archive(args.archive)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(samples):
        raise SystemExit("index row count differs from fresh decode")
    expected_outputs: set[Path] = set()
    for sample, row in zip(samples, rows, strict=True):
        payload = sample["payload"]
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit("dataset/series/role mismatch")
        if row.get("source_member") != sample["source_member"] or row.get("channel_index") != sample["channel_index"]:
            raise SystemExit("source member/channel mismatch")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8 or row.get("endianness") != "little" or row.get("element_size_bytes") != 1:
            raise SystemExit("numeric schema mismatch")
        if row.get("sample_shape") != [sample["height"], sample["width"]] or row.get("value_count") != len(payload):
            raise SystemExit("sample geometry mismatch")
        output = args.data_root / str(row["sample_path"])
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh TIFF decode: {output}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch: {output}")
        expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    expected_summary = summary(samples, duplicates, image_count)
    if json.loads(args.stats.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("ingest stats differ from fresh archive parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_images": image_count,
        "verified_samples": len(samples),
        "verified_values": expected_summary["value_count"],
        "verified_bytes": expected_summary["total_size_bytes"],
        "duplicate_planes_excluded": len(duplicates),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--archive", type=Path, required=True)
    pre.add_argument("--rights", type=Path, required=True)
    pre.add_argument("--profile", type=Path, required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--archive", type=Path, required=True)
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
