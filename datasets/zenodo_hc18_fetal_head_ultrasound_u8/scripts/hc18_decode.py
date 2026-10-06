#!/usr/bin/env python3
"""Build-side decoder for the HC18 fetal-head ultrasound recipe.

Pure standard library. Parses the two pinned Zenodo ZIP archives through their
central directories (stored and raw-DEFLATE members), decodes each *HC.png
image member with a strict 800x540 8-bit grayscale PNG decoder (IDAT inflate
plus scanline unfilter for filter types 0-4), and writes one raw uint8 sample
per image together with samples.jsonl and ingest_stats.json.

Usage: hc18_decode.py build <data_root>
"""
from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hc18_pins as pins  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EOCD_SIGNATURE = b"PK\x05\x06"
CD_SIGNATURE = 0x02014B50
LOCAL_SIGNATURE = 0x04034B50


class DecodeError(ValueError):
    pass


# --------------------------------------------------------------------- ZIP


def read_central_directory(path: Path) -> list[dict]:
    """Return central-directory entries of a classic (non-ZIP64) archive."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        tail_len = min(size, 22 + 65535)
        fh.seek(size - tail_len)
        tail = fh.read(tail_len)
        eocd = tail.rfind(EOCD_SIGNATURE)
        if eocd < 0 or eocd + 22 > len(tail):
            raise DecodeError(f"{path.name}: no end-of-central-directory record")
        (_sig, disk, cd_disk, entries_disk, entries, cd_size, cd_offset, comment_len) = struct.unpack_from(
            "<IHHHHIIH", tail, eocd
        )
        if eocd + 22 + comment_len != len(tail):
            raise DecodeError(f"{path.name}: trailing bytes after EOCD comment")
        if disk or cd_disk or entries_disk != entries:
            raise DecodeError(f"{path.name}: multi-disk archive")
        if entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
            raise DecodeError(f"{path.name}: ZIP64 archive not expected")
        eocd_offset = size - tail_len + eocd
        if cd_offset + cd_size != eocd_offset:
            raise DecodeError(f"{path.name}: central directory does not end at EOCD")
        fh.seek(cd_offset)
        cd = fh.read(cd_size)
    result: list[dict] = []
    pos = 0
    for _ in range(entries):
        if pos + 46 > len(cd):
            raise DecodeError(f"{path.name}: truncated central directory")
        fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, pos)
        if fields[0] != CD_SIGNATURE:
            raise DecodeError(f"{path.name}: bad central-directory signature at {pos}")
        flags, method = fields[3], fields[4]
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        raw_name = cd[pos + 46 : pos + 46 + name_len]
        name = raw_name.decode("utf-8" if flags & 0x800 else "cp437")
        result.append(
            {
                "name": name,
                "flags": flags,
                "method": method,
                "crc32": fields[7],
                "compressed_size": fields[8],
                "uncompressed_size": fields[9],
                "local_header_offset": fields[16],
            }
        )
        pos += 46 + name_len + extra_len + comment_len
    if pos != len(cd):
        raise DecodeError(f"{path.name}: central directory has {len(cd) - pos} unparsed bytes")
    return result


def read_member(fh, entry: dict) -> bytes:
    """Read, inflate (method 8) and CRC-check one member via its local header."""
    if entry["flags"] & 0x1:
        raise DecodeError(f"{entry['name']}: encrypted member")
    if entry["method"] not in (0, 8):
        raise DecodeError(f"{entry['name']}: unsupported compression method {entry['method']}")
    fh.seek(entry["local_header_offset"])
    header = fh.read(30)
    if len(header) != 30:
        raise DecodeError(f"{entry['name']}: truncated local header")
    fields = struct.unpack("<IHHHHHIIIHH", header)
    if fields[0] != LOCAL_SIGNATURE:
        raise DecodeError(f"{entry['name']}: bad local header signature")
    if fields[3] != entry["method"]:
        raise DecodeError(f"{entry['name']}: local/central method mismatch")
    name_len, extra_len = fields[9], fields[10]
    local_name = fh.read(name_len).decode("utf-8" if fields[2] & 0x800 else "cp437")
    if local_name != entry["name"]:
        raise DecodeError(f"{entry['name']}: local header names {local_name!r}")
    fh.seek(extra_len, io.SEEK_CUR)
    payload = fh.read(entry["compressed_size"])
    if len(payload) != entry["compressed_size"]:
        raise DecodeError(f"{entry['name']}: truncated member data")
    if entry["method"] == 0:
        if entry["compressed_size"] != entry["uncompressed_size"]:
            raise DecodeError(f"{entry['name']}: stored member size mismatch")
        data = payload
    else:
        inflater = zlib.decompressobj(-15)
        data = inflater.decompress(payload) + inflater.flush()
        if not inflater.eof or inflater.unused_data:
            raise DecodeError(f"{entry['name']}: DEFLATE stream does not end at the member boundary")
    if len(data) != entry["uncompressed_size"]:
        raise DecodeError(f"{entry['name']}: inflated {len(data)} bytes, expected {entry['uncompressed_size']}")
    if zlib.crc32(data) & 0xFFFFFFFF != entry["crc32"]:
        raise DecodeError(f"{entry['name']}: CRC-32 mismatch")
    return data


# --------------------------------------------------------------------- PNG


def unfilter(raw: bytes, width: int, height: int) -> tuple[bytes, list[int]]:
    """Undo PNG scanline filters for 1 byte per pixel; returns pixels and the
    per-filter-type row counts."""
    stride = width + 1
    if len(raw) != stride * height:
        raise DecodeError(f"inflated image data has {len(raw)} bytes, expected {stride * height}")
    out = bytearray(width * height)
    prev = bytearray(width)
    filter_counts = [0, 0, 0, 0, 0]
    for y in range(height):
        start = y * stride
        ftype = raw[start]
        row = bytearray(raw[start + 1 : start + stride])
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(1, width):
                row[i] = (row[i] + row[i - 1]) & 255
        elif ftype == 2:
            for i in range(width):
                row[i] = (row[i] + prev[i]) & 255
        elif ftype == 3:
            row[0] = (row[0] + (prev[0] >> 1)) & 255
            for i in range(1, width):
                row[i] = (row[i] + ((row[i - 1] + prev[i]) >> 1)) & 255
        elif ftype == 4:
            a = (row[0] + prev[0]) & 255
            row[0] = a
            for i in range(1, width):
                b = prev[i]
                c = prev[i - 1]
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                if pa <= pb and pa <= pc:
                    predictor = a
                elif pb <= pc:
                    predictor = b
                else:
                    predictor = c
                a = (row[i] + predictor) & 255
                row[i] = a
        else:
            raise DecodeError(f"row {y}: invalid PNG filter type {ftype}")
        filter_counts[ftype] += 1
        out[y * width : (y + 1) * width] = row
        prev = row
    return bytes(out), filter_counts


def decode_png(png: bytes, width: int, height: int) -> tuple[bytes, dict]:
    """Strict decoder: 8-bit grayscale, non-interlaced, exact pinned dimensions."""
    if png[:8] != PNG_SIGNATURE:
        raise DecodeError("missing PNG signature")
    pos = 8
    idat = bytearray()
    idat_chunks = 0
    idat_closed = False
    seen_ihdr = False
    ancillary: collections.Counter = collections.Counter()
    while True:
        if pos + 12 > len(png):
            raise DecodeError("truncated PNG chunk stream (no IEND)")
        (length,) = struct.unpack_from(">I", png, pos)
        ctype = png[pos + 4 : pos + 8]
        if pos + 12 + length > len(png):
            raise DecodeError(f"chunk {ctype!r} overruns the file")
        body = png[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack_from(">I", png, pos + 8 + length)
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise DecodeError(f"chunk {ctype!r} CRC mismatch")
        pos += 12 + length
        if not seen_ihdr:
            if ctype != b"IHDR" or length != 13:
                raise DecodeError("first chunk is not a 13-byte IHDR")
            w, h, depth, color, compression, filt, interlace = struct.unpack(">IIBBBBB", body)
            if (w, h) != (width, height):
                raise DecodeError(f"image is {w}x{h}, expected {width}x{height}")
            if depth != 8 or color != 0:
                raise DecodeError(f"bit depth {depth} colour type {color}; expected 8-bit grayscale (type 0)")
            if compression != 0 or filt != 0 or interlace != 0:
                raise DecodeError(f"compression {compression} filter {filt} interlace {interlace} not supported")
            seen_ihdr = True
            continue
        if ctype == b"IDAT":
            if idat_closed:
                raise DecodeError("IDAT chunks are not consecutive")
            idat += body
            idat_chunks += 1
        elif ctype == b"IEND":
            if length != 0:
                raise DecodeError("IEND has a body")
            break
        elif ctype == b"tRNS":
            raise DecodeError("tRNS transparency chunk present")
        elif ctype[0:1].isupper():
            raise DecodeError(f"unexpected critical chunk {ctype!r}")
        else:
            ancillary[ctype.decode("latin-1")] += 1
            if idat_chunks:
                idat_closed = True
    if pos != len(png):
        raise DecodeError(f"{len(png) - pos} bytes after IEND")
    if not idat_chunks:
        raise DecodeError("no IDAT chunk")
    inflater = zlib.decompressobj()
    raw = inflater.decompress(bytes(idat)) + inflater.flush()
    if not inflater.eof or inflater.unused_data:
        raise DecodeError("IDAT zlib stream is incomplete or has trailing data")
    pixels, filter_counts = unfilter(raw, width, height)
    return pixels, {"idat_chunks": idat_chunks, "ancillary": dict(ancillary), "filter_rows": filter_counts}


# ------------------------------------------------------------------- build


def read_pixel_sizes(path: Path, split: dict) -> dict[str, str]:
    text = path.read_text(encoding="ascii")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != split["csv_header"]:
        raise DecodeError(f"{path.name}: unexpected header {rows[:1]!r}")
    sizes: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) != len(split["csv_header"]):
            raise DecodeError(f"{path.name}: malformed row {row!r}")
        name, value = row[0], row[1]
        if name in sizes:
            raise DecodeError(f"{path.name}: duplicate filename {name}")
        number = float(value)
        if not (pins.PIXEL_SIZE_MIN_MM <= number <= pins.PIXEL_SIZE_MAX_MM):
            raise DecodeError(f"{path.name}: pixel size {value} for {name} outside the published range")
        sizes[name] = value
    if len(sizes) != split["images"]:
        raise DecodeError(f"{path.name}: {len(sizes)} rows, expected {split['images']}")
    return sizes


def select_images(entries: list[dict], split: dict) -> list[dict]:
    """Classify every archive member; return the image members in natural order."""
    prefix = split["prefix"]
    images: list[dict] = []
    annotations = 0
    directories = 0
    for entry in entries:
        name = entry["name"]
        if name == prefix:
            directories += 1
            continue
        if not name.startswith(prefix) or "/" in name[len(prefix) :]:
            raise DecodeError(f"{split['archive']}: unexpected member path {name!r}")
        base = name[len(prefix) :]
        if re.match(pins.IMAGE_NAME_PATTERN, base):
            images.append(entry)
        elif re.match(pins.ANNOTATION_NAME_PATTERN, base):
            annotations += 1
        else:
            raise DecodeError(f"{split['archive']}: unexpected member {name!r}")
    if len(entries) != split["cd_entries"] or directories != 1:
        raise DecodeError(f"{split['archive']}: {len(entries)} entries / {directories} directory entries")
    if len(images) != split["images"] or annotations != split["annotations"]:
        raise DecodeError(
            f"{split['archive']}: {len(images)} images and {annotations} annotations, "
            f"expected {split['images']} and {split['annotations']}"
        )
    methods = collections.Counter(entry["method"] for entry in images)
    if methods != collections.Counter({0: split["images_stored"], 8: split["images_deflated"]}):
        raise DecodeError(f"{split['archive']}: image member methods {dict(methods)}")
    images.sort(key=lambda entry: pins.natural_key(entry["name"][len(prefix) :]))
    return images


def image_stats(pixels: bytes) -> dict:
    histogram = [0] * 256
    for value, count in collections.Counter(pixels).items():
        histogram[value] = count
    present = [value for value in range(256) if histogram[value]]
    return {
        "min_value": present[0],
        "max_value": present[-1],
        "distinct_values": len(present),
        "modal_fraction": round(max(histogram) / len(pixels), 6),
        "zero_fraction": round(histogram[0] / len(pixels), 6),
        "mean_value": round(sum(value * histogram[value] for value in present) / len(pixels), 6),
    }


def check_degenerate(name: str, stats: dict) -> None:
    if stats["min_value"] == stats["max_value"]:
        raise DecodeError(f"{name}: constant image")
    if stats["distinct_values"] < pins.MIN_DISTINCT_VALUES:
        raise DecodeError(f"{name}: only {stats['distinct_values']} distinct values")
    if stats["modal_fraction"] > pins.MAX_MODAL_FRACTION:
        raise DecodeError(f"{name}: modal value covers {stats['modal_fraction']:.3f} of the frame")


def build(data_root: Path) -> None:
    dataset_id = pins.DATASET_ID
    download_dir = data_root / "downloads" / dataset_id
    out_dir = data_root / "samples" / dataset_id / pins.SERIES_ID
    index_dir = data_root / "index" / dataset_id
    filtered_dir = data_root / "filtered" / dataset_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    seen_digests: dict[str, str] = {}
    skipped_duplicates: list[dict] = []
    originals = set(pins.SKIPPED_MEMBERS.values())
    original_pixels: dict[str, bytes] = {}
    filter_totals = [0, 0, 0, 0, 0]
    ancillary_totals: collections.Counter = collections.Counter()
    split_stats: dict = {}
    for split in pins.SPLITS:
        archive = download_dir / split["archive"]
        if archive.stat().st_size != split["archive_bytes"]:
            raise DecodeError(f"{archive.name}: size {archive.stat().st_size} != pinned {split['archive_bytes']}")
        sizes = read_pixel_sizes(download_dir / split["csv"], split)
        entries = read_central_directory(archive)
        images = select_images(entries, split)
        member_names = {entry["name"][len(split["prefix"]) :] for entry in images}
        if member_names != set(sizes):
            raise DecodeError(f"{split['archive']}: image members and {split['csv']} filenames differ")
        split_values = 0
        with archive.open("rb") as fh:
            for entry in images:
                base = entry["name"][len(split["prefix"]) :]
                png = read_member(fh, entry)
                width, height = pins.expected_size(entry["name"])
                pixels, info = decode_png(png, width, height)
                if len(pixels) != width * height:
                    raise DecodeError(f"{entry['name']}: decoded {len(pixels)} values")
                stats = image_stats(pixels)
                check_degenerate(entry["name"], stats)
                digest = hashlib.sha256(pixels).hexdigest()
                if entry["name"] in pins.SKIPPED_MEMBERS:
                    original = pins.SKIPPED_MEMBERS[entry["name"]]
                    if original not in original_pixels:
                        raise DecodeError(f"{entry['name']}: original {original} not decoded before it")
                    reference = original_pixels[original]
                    differing = sum(1 for x, y in zip(pixels, reference) if x != y) if len(pixels) == len(reference) else -1
                    if entry["name"] in pins.EXACT_DUPLICATES:
                        kind = "exact"
                        ok = differing == 0 and seen_digests.get(digest) == original
                    else:
                        kind = "near"
                        ok = (
                            pins.expected_size(entry["name"]) == pins.expected_size(original)
                            and 0 < differing < pins.NEAR_DUPLICATE_MAX_DIFF_FRACTION * len(pixels)
                        )
                    if not ok:
                        raise DecodeError(f"{entry['name']}: not a {kind} duplicate of {original} (differing={differing})")
                    skipped_duplicates.append(
                        {"member": entry["name"], "duplicate_of": original, "kind": kind, "differing_pixels": differing}
                    )
                    continue
                if entry["name"] in originals:
                    original_pixels[entry["name"]] = pixels
                if digest in seen_digests:
                    raise DecodeError(f"{entry['name']}: pixel payload duplicates {seen_digests[digest]}")
                seen_digests[digest] = entry["name"]
                for ftype, count in enumerate(info["filter_rows"]):
                    filter_totals[ftype] += count
                ancillary_totals.update(info["ancillary"])
                name = pins.sample_name(split, base)
                out_path = out_dir / name
                out_path.write_bytes(pixels)
                split_values += len(pixels)
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "series_id": pins.SERIES_ID,
                        "role": "primary",
                        "sample_path": out_path.relative_to(data_root).as_posix(),
                        "numeric_kind": "uint",
                        "bit_width": 8,
                        "endianness": "little",
                        "element_size_bytes": 1,
                        "sample_size_bytes": len(pixels),
                        "value_count": len(pixels),
                        "sample_format": "raw homogeneous uint8 B-mode ultrasound image",
                        "sample_geometry": "bmode_ultrasound_display_raster_2d",
                        "sample_rank": 2,
                        "sample_shape": [height, width],
                        "sample_axes": ["image_row_y", "image_column_x"],
                        "natural_record_kind": "hc18_fetal_head_bmode_ultrasound_png_image",
                        "split": split["split"],
                        "source_resource": split["resource"],
                        "source_member": entry["name"],
                        "source_member_method": "stored" if entry["method"] == 0 else "deflate",
                        "source_member_crc32": f"{entry['crc32']:08x}",
                        "pixel_size_mm": float(sizes[base]),
                        "sha256": digest,
                        **stats,
                    }
                )
        split_stats[split["split"]] = {
            "archive": split["archive"],
            "central_directory_entries": len(entries),
            "images": len(images),
            "emitted": sum(1 for row in rows if row["split"] == split["split"]),
            "annotation_members_skipped": split["annotations"],
            "values": split_values,
        }
    if len(rows) != pins.TOTAL_IMAGES:
        raise DecodeError(f"built {len(rows)} samples, expected {pins.TOTAL_IMAGES}")
    if sum(row["value_count"] for row in rows) != pins.TOTAL_VALUES:
        raise DecodeError(f"built {sum(row['value_count'] for row in rows)} values, expected {pins.TOTAL_VALUES}")
    if len(skipped_duplicates) != len(pins.SKIPPED_MEMBERS):
        raise DecodeError(f"skipped duplicates {skipped_duplicates} != pinned {pins.SKIPPED_MEMBERS}")
    unused = set(pins.SIZE_EXCEPTIONS) - {row["source_member"] for row in rows}
    if unused:
        raise DecodeError(f"size exceptions name unknown members: {sorted(unused)}")
    aggregate = hashlib.sha256(
        "".join(f"{Path(row['sample_path']).name}\t{row['sha256']}\n" for row in rows).encode("ascii")
    ).hexdigest()
    if pins.AGGREGATE_SHA256 and aggregate != pins.AGGREGATE_SHA256:
        raise DecodeError(f"aggregate SHA-256 {aggregate} != pinned {pins.AGGREGATE_SHA256}")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    stats = {
        "dataset_id": dataset_id,
        "series_id": pins.SERIES_ID,
        "samples": len(rows),
        "total_values": total_bytes,
        "total_bytes": total_bytes,
        "splits": split_stats,
        "published_images": pins.PUBLISHED_IMAGES,
        "skipped_duplicates": skipped_duplicates,
        "size_exceptions": len(pins.SIZE_EXCEPTIONS),
        "png_filter_rows": dict(zip(["none", "sub", "up", "average", "paeth"], filter_totals)),
        "png_ancillary_chunks": dict(sorted(ancillary_totals.items())),
        "min_distinct_values": min(row["distinct_values"] for row in rows),
        "max_modal_fraction": max(row["modal_fraction"] for row in rows),
        "mean_zero_fraction": round(sum(row["zero_fraction"] for row in rows) / len(rows), 6),
        "global_min_value": min(row["min_value"] for row in rows),
        "global_max_value": max(row["max_value"] for row in rows),
        "aggregate_sha256": aggregate,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in stats.items() if key != "splits"}, sort_keys=True))
    print(f"built samples={len(rows)} total_bytes={total_bytes} aggregate_sha256={aggregate}")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "build":
        print(__doc__, file=sys.stderr)
        return 2
    build(Path(argv[2]).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
