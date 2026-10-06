#!/usr/bin/env python3
"""Independent verifier for the HC18 fetal-head ultrasound recipe.

Deliberately shares no decoding code with hc18_decode.py: archive members are
read with the standard-library zipfile module (which checks CRC-32), PNG chunks
are walked with a separate parser, and scanlines are unfiltered by a separate
flat-buffer implementation. Every sample is re-derived from the downloaded
archives and byte-compared; index rows, statistics, the sample directory and
the manifest counts are re-checked.

Usage: hc18_verify.py <data_root> <manifest.toml>
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import statistics
import struct
import sys
import tomllib
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hc18_pins as pins  # noqa: E402

MIN_TOTAL_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def png_chunks(png: bytes):
    """Yield (type, body) pairs, checking CRCs and stopping after IEND."""
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    offset = 8
    while offset < len(png):
        length = int.from_bytes(png[offset : offset + 4], "big")
        kind = png[offset + 4 : offset + 8]
        body = png[offset + 8 : offset + 8 + length]
        stored_crc = int.from_bytes(png[offset + 8 + length : offset + 12 + length], "big")
        if len(body) != length or zlib.crc32(body, zlib.crc32(kind)) != stored_crc:
            raise ValueError(f"bad chunk {kind!r}")
        offset += 12 + length
        yield kind, body
        if kind == b"IEND":
            if offset != len(png):
                raise ValueError("data after IEND")
            return
    raise ValueError("no IEND")


def reconstruct(filtered: bytes, width: int, height: int) -> bytearray:
    """Flat-buffer PNG unfilter (bpp = 1) written independently of the build."""
    if len(filtered) != (width + 1) * height:
        raise ValueError("wrong inflated length")
    out = bytearray(width * height)
    src = 0
    for y in range(height):
        kind = filtered[src]
        src += 1
        base = y * width
        above = base - width
        if kind > 4:
            raise ValueError(f"filter type {kind}")
        for x in range(width):
            value = filtered[src + x]
            left = out[base + x - 1] if x else 0
            up = out[above + x] if y else 0
            if kind == 1:
                value += left
            elif kind == 2:
                value += up
            elif kind == 3:
                value += (left + up) // 2
            elif kind == 4:
                upper_left = out[above + x - 1] if (x and y) else 0
                d_left = abs(up - upper_left)  # |p - left|
                d_up = abs(left - upper_left)  # |p - up|
                d_ul = abs(left + up - 2 * upper_left)  # |p - upper_left|
                if d_left <= d_up and d_left <= d_ul:
                    value += left
                elif d_up <= d_ul:
                    value += up
                else:
                    value += upper_left
            out[base + x] = value & 0xFF
        src += width
    return out


def decode_grayscale_png(png: bytes, width: int, height: int) -> bytes:
    chunks = list(png_chunks(png))
    kinds = [kind for kind, _ in chunks]
    if not kinds or kinds[0] != b"IHDR":
        raise ValueError("IHDR is not first")
    header = struct.unpack(">IIBBBBB", chunks[0][1])
    if header != (width, height, 8, 0, 0, 0, 0):
        raise ValueError(f"IHDR {header} is not {width}x{height} 8-bit grayscale non-interlaced")
    positions = [i for i, kind in enumerate(kinds) if kind == b"IDAT"]
    if not positions or positions != list(range(positions[0], positions[-1] + 1)):
        raise ValueError("missing or non-consecutive IDAT")
    for kind in kinds[1:]:
        if kind in (b"IDAT", b"IEND"):
            continue
        if kind == b"tRNS" or not (kind[0] & 0x20):
            raise ValueError(f"disallowed chunk {kind!r}")
    if kinds.count(b"IHDR") != 1 or kinds[-1] != b"IEND":
        raise ValueError("bad chunk order")
    stream = b"".join(chunks[i][1] for i in positions)
    inflater = zlib.decompressobj()
    filtered = inflater.decompress(stream)
    filtered += inflater.flush()
    if not inflater.eof or inflater.unused_data:
        raise ValueError("incomplete zlib stream")
    return bytes(reconstruct(filtered, width, height))


def pixel_statistics(pixels: bytes) -> dict:
    counts = [0] * 256
    for value in pixels:
        counts[value] += 1
    nonzero = [v for v, c in enumerate(counts) if c]
    total = len(pixels)
    return {
        "min_value": min(nonzero),
        "max_value": max(nonzero),
        "distinct_values": len(nonzero),
        "modal_fraction": round(max(counts) / total, 6),
        "zero_fraction": round(counts[0] / total, 6),
        "mean_value": round(sum(v * c for v, c in enumerate(counts)) / total, 6),
    }


def load_csv(path: Path, split: dict) -> dict[str, float]:
    with path.open(newline="", encoding="ascii") as fh:
        table = list(csv.reader(fh))
    if table[0] != split["csv_header"]:
        fail(f"{path.name}: header {table[0]!r}")
    body = table[1:]
    names = [row[0] for row in body]
    if len(body) != split["images"] or len(set(names)) != len(names):
        fail(f"{path.name}: {len(body)} rows / {len(set(names))} unique names")
    result = {}
    for row in body:
        size = float(row[1])
        if not pins.PIXEL_SIZE_MIN_MM <= size <= pins.PIXEL_SIZE_MAX_MM:
            fail(f"{path.name}: pixel size {size} outside the published range")
        result[row[0]] = size
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    data_root = Path(argv[1]).resolve()
    manifest = tomllib.loads(Path(argv[2]).read_text(encoding="utf-8"))
    dataset_id = pins.DATASET_ID
    download_dir = data_root / "downloads" / dataset_id
    index_path = data_root / "index" / dataset_id / "samples.jsonl"
    sample_dir = data_root / "samples" / dataset_id / pins.SERIES_ID
    if manifest.get("dataset_id") != dataset_id:
        fail("manifest dataset_id mismatch")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != pins.TOTAL_IMAGES:
        fail(f"index has {len(rows)} rows, expected {pins.TOTAL_IMAGES}")
    by_member = {row["source_member"]: row for row in rows}
    if len(by_member) != len(rows):
        fail("duplicate source_member in index")

    expected_order: list[str] = []
    checked = 0
    digests: set[str] = set()
    member_digest: dict[str, str] = {}
    kept_pixels: dict[str, bytes] = {}
    duplicates_confirmed = 0
    for split in pins.SPLITS:
        archive_path = download_dir / split["archive"]
        if archive_path.stat().st_size != split["archive_bytes"]:
            fail(f"{archive_path.name}: size changed")
        for path, expected_md5 in ((archive_path, split["archive_md5"]), (download_dir / split["csv"], split["csv_md5"])):
            digest = hashlib.md5()
            with path.open("rb") as fh:
                while block := fh.read(8 << 20):
                    digest.update(block)
            if digest.hexdigest() != expected_md5:
                fail(f"{path.name}: MD5 {digest.hexdigest()} != pinned {expected_md5}")
        sizes = load_csv(download_dir / split["csv"], split)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) != split["cd_entries"]:
                fail(f"{split['archive']}: {len(infos)} members")
            images = []
            annotations = 0
            for info in infos:
                base = info.filename[len(split["prefix"]) :]
                if not info.filename.startswith(split["prefix"]):
                    fail(f"unexpected member {info.filename}")
                if info.is_dir():
                    continue
                if base.endswith("_Annotation.png"):
                    annotations += 1
                elif re.fullmatch(r"\d{3}_([2-9])?HC\.png", base):
                    images.append(info)
                else:
                    fail(f"unexpected member {info.filename}")
            if len(images) != split["images"] or annotations != split["annotations"]:
                fail(f"{split['archive']}: {len(images)} images / {annotations} annotations")
            if {info.filename[len(split["prefix"]) :] for info in images} != set(sizes):
                fail(f"{split['archive']}: members disagree with {split['csv']}")
            stored = sum(1 for info in images if info.compress_type == zipfile.ZIP_STORED)
            deflated = sum(1 for info in images if info.compress_type == zipfile.ZIP_DEFLATED)
            if (stored, deflated) != (split["images_stored"], split["images_deflated"]):
                fail(f"{split['archive']}: stored/deflated = {stored}/{deflated}")

            def order_key(info: zipfile.ZipInfo) -> tuple[int, int]:
                base = info.filename[len(split["prefix"]) :]
                number, _, rest = base.partition("_")
                repeat = rest[: -len("HC.png")]
                return int(number), int(repeat) if repeat else 1

            for info in sorted(images, key=order_key):
                base = info.filename[len(split["prefix"]) :]
                width, height = pins.SIZE_EXCEPTIONS.get(info.filename, (pins.WIDTH, pins.HEIGHT))
                pixels = decode_grayscale_png(archive.read(info), width, height)
                if info.filename in pins.SKIPPED_MEMBERS:
                    original = pins.SKIPPED_MEMBERS[info.filename]
                    reference = kept_pixels.get(original)
                    if reference is None or len(reference) != len(pixels):
                        fail(f"{info.filename}: original {original} missing or differently sized")
                    mismatches = sum(1 for x, y in zip(pixels, reference) if x != y)
                    if info.filename in pins.EXACT_DUPLICATES:
                        if mismatches or member_digest.get(original) != hashlib.sha256(pixels).hexdigest():
                            fail(f"{info.filename}: pinned exact duplicate differs from {original}")
                    elif not (0 < mismatches < pins.NEAR_DUPLICATE_MAX_DIFF_FRACTION * len(pixels)):
                        fail(f"{info.filename}: {mismatches} pixels differ from {original}; not a near-duplicate")
                    elif pins.SIZE_EXCEPTIONS.get(original, (pins.WIDTH, pins.HEIGHT)) != (width, height):
                        fail(f"{info.filename}: shape differs from {original}")
                    if info.filename in by_member or (sample_dir / f"{split['split']}_{base[:-4]}.bin").exists():
                        fail(f"{info.filename}: skipped duplicate was emitted")
                    duplicates_confirmed += 1
                    continue
                expected_order.append(info.filename)
                row = by_member.get(info.filename)
                if row is None:
                    fail(f"{info.filename} missing from index")
                sample_path = data_root / row["sample_path"]
                if sample_path.parent != sample_dir or sample_path.name != f"{split['split']}_{base[:-4]}.bin":
                    fail(f"{info.filename}: unexpected sample path {row['sample_path']}")
                stored_bytes = sample_path.read_bytes()
                if stored_bytes != pixels:
                    fail(f"{row['sample_path']}: bytes differ from the independent decode of {info.filename}")
                digest = hashlib.sha256(pixels).hexdigest()
                if digest in digests:
                    fail(f"{info.filename}: duplicate pixel payload")
                digests.add(digest)
                member_digest[info.filename] = digest
                if info.filename in set(pins.SKIPPED_MEMBERS.values()):
                    kept_pixels[info.filename] = pixels
                stats = pixel_statistics(pixels)
                if stats["min_value"] == stats["max_value"]:
                    fail(f"{info.filename}: constant image")
                if stats["distinct_values"] < pins.MIN_DISTINCT_VALUES:
                    fail(f"{info.filename}: {stats['distinct_values']} distinct values")
                if stats["modal_fraction"] > pins.MAX_MODAL_FRACTION:
                    fail(f"{info.filename}: modal fraction {stats['modal_fraction']}")
                expected_row = {
                    "dataset_id": dataset_id,
                    "series_id": pins.SERIES_ID,
                    "role": "primary",
                    "numeric_kind": "uint",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "sample_size_bytes": width * height,
                    "value_count": width * height,
                    "sample_rank": 2,
                    "sample_shape": [height, width],
                    "split": split["split"],
                    "source_resource": split["resource"],
                    "source_member_method": "stored" if info.compress_type == zipfile.ZIP_STORED else "deflate",
                    "source_member_crc32": f"{info.CRC:08x}",
                    "pixel_size_mm": sizes[base],
                    "sha256": digest,
                    **stats,
                }
                for key, value in expected_row.items():
                    if row.get(key) != value:
                        fail(f"{info.filename}: index {key}={row.get(key)!r}, expected {value!r}")
                checked += 1
    if duplicates_confirmed != len(pins.SKIPPED_MEMBERS):
        fail(f"confirmed {duplicates_confirmed} pinned duplicates, expected {len(pins.SKIPPED_MEMBERS)}")
    if [row["source_member"] for row in rows] != expected_order:
        fail("index order is not training-then-test natural member order")
    indexed_files = {Path(row["sample_path"]).name for row in rows}
    present_files = {path.name for path in sample_dir.iterdir()}
    if present_files != indexed_files:
        fail(f"sample directory has {len(present_files - indexed_files)} unindexed / {len(indexed_files - present_files)} missing files")

    aggregate = hashlib.sha256(
        "".join(f"{Path(row['sample_path']).name}\t{row['sha256']}\n" for row in rows).encode("ascii")
    ).hexdigest()
    if pins.AGGREGATE_SHA256 and aggregate != pins.AGGREGATE_SHA256:
        fail(f"aggregate SHA-256 {aggregate} != pinned {pins.AGGREGATE_SHA256}")

    counts = [row["value_count"] for row in rows]
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    if sum(counts) != pins.TOTAL_VALUES:
        fail(f"{sum(counts)} values, expected {pins.TOTAL_VALUES}")
    if not set(pins.SIZE_EXCEPTIONS) <= set(expected_order):
        fail("size exceptions name members that are not images")
    if sum(counts) < MIN_TOTAL_VALUES and total_bytes < MIN_PRIMARY_BYTES:
        fail("aggregate floor failed")
    if statistics.median(counts) < MIN_MEDIAN_VALUES:
        fail("median sample floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        fail("primary bytes exceed the 1 GB cap")
    series = [s for s in manifest.get("series", []) if s.get("id") == pins.SERIES_ID]
    if len(series) != 1 or len(manifest.get("series", [])) != 1:
        fail("manifest must declare exactly the one primary series")
    if series[0].get("sample_count") != len(rows) or series[0].get("total_size_bytes") != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
            f"!= realized {len(rows)}/{total_bytes}"
        )
    print(
        f"verified series={pins.SERIES_ID} samples={checked} total_bytes={total_bytes} "
        f"median_values={int(statistics.median(counts))} aggregate_sha256={aggregate}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
