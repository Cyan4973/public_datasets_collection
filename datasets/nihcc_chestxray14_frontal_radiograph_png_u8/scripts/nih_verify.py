#!/usr/bin/env python3
"""Independent verifier for the NIH ChestX-ray14 8-bit radiograph recipe.

Shares no decoding code with nih_decode.py: the gzip prefix is read through
the standard-library gzip module, tar members through tarfile, PNG chunks
through a separate walker, and scanlines are unfiltered by a separate
flat-buffer implementation. Every sample is re-derived from the local prefixes
and byte-compared; the skip list, index rows, statistics, the sample directory
and the manifest counts are re-checked.

Usage: nih_verify.py <data_root> <manifest.toml>
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import statistics
import struct
import sys
import tarfile
import tomllib
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nih_pins as pins  # noqa: E402

MIN_TOTAL_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def whole_tar_members(prefix: bytes) -> list[tuple[str, int, bytes]]:
    """(name, data offset, data) of every regular member wholly inside the prefix."""
    # Parse the RFC 1952 member header here, then raw-inflate (wbits=-15); the
    # build side lets zlib parse the header itself (wbits=31).
    if prefix[:2] != b"\x1f\x8b" or prefix[2] != 8:
        raise ValueError("not a gzip deflate stream")
    flags = prefix[3]
    pos = 10
    if flags & 0x04:  # FEXTRA
        pos += 2 + int.from_bytes(prefix[pos : pos + 2], "little")
    for bit in (0x08, 0x10):  # FNAME, FCOMMENT
        if flags & bit:
            pos = prefix.index(b"\x00", pos) + 1
    if flags & 0x02:  # FHCRC
        pos += 2
    raw = zlib.decompressobj(-15)
    data = raw.decompress(prefix[pos:])
    if raw.eof:
        raise ValueError("gzip stream ended inside the prefix")
    result = []
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.ReadError:
        return result  # not even one whole header in the prefix
    with tf:
        while True:
            try:
                info = tf.next()
            except tarfile.ReadError:
                break  # truncated member at the end of the prefix
            if info is None:
                break
            if info.isdir():
                continue
            if not info.isreg():
                raise ValueError(f"unexpected tar member type for {info.name}")
            end = info.offset_data + info.size
            if end > len(data):
                break
            result.append((info.name, info.offset_data, data[info.offset_data : end]))
    return result


def png_chunks(png: bytes):
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
                d_left = abs(up - upper_left)
                d_up = abs(left - upper_left)
                d_ul = abs(left + up - 2 * upper_left)
                if d_left <= d_up and d_left <= d_ul:
                    value += left
                elif d_up <= d_ul:
                    value += up
                else:
                    value += upper_left
            out[base + x] = value & 0xFF
        src += width
    return out


def ihdr_of(png: bytes) -> tuple:
    for kind, body in png_chunks(png):
        if kind != b"IHDR" or len(body) != 13:
            raise ValueError("IHDR is not first")
        return struct.unpack(">IIBBBBB", body)
    raise ValueError("empty PNG")


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
    present = [v for v, c in enumerate(counts) if c]
    total = len(pixels)
    return {
        "min_value": min(present),
        "max_value": max(present),
        "distinct_values": len(present),
        "modal_fraction": round(max(counts) / total, 6),
        "zero_fraction": round(counts[0] / total, 6),
        "mean_value": round(sum(v * c for v, c in enumerate(counts)) / total, 6),
    }


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
    stats_path = data_root / "filtered" / dataset_id / "ingest_stats.json"
    if manifest.get("dataset_id") != dataset_id:
        fail("manifest dataset_id mismatch")

    faq = (download_dir / pins.FAQ_NAME).read_bytes()
    if len(faq) != pins.FAQ_BYTES or hashlib.sha256(faq).hexdigest() != pins.FAQ_SHA256:
        fail("FAQ_CHESTXRAY.pdf licence evidence is missing or changed")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ingest = json.loads(stats_path.read_text(encoding="utf-8"))
    by_key = {(row["source_tarball"], row["source_member"]): row for row in rows}
    if len(by_key) != len(rows):
        fail("duplicate (tarball, member) in index")

    expected_order: list[tuple[str, str]] = []
    expected_skips: list[dict] = []
    digests: set[str] = set()
    patients: set[str] = set()
    for tarball, _hash, _size, _md5 in pins.TARBALLS:
        path = download_dir / pins.prefix_name(tarball)
        prefix = path.read_bytes()
        if len(prefix) != pins.PREFIX_BYTES:
            fail(f"{path.name}: {len(prefix)} bytes")
        prefix_sha = hashlib.sha256(prefix).hexdigest()
        if pins.PREFIX_SHA256.get(tarball) and prefix_sha != pins.PREFIX_SHA256[tarball]:
            fail(f"{path.name}: sha256 {prefix_sha} != pinned")
        if ingest["tarballs"][tarball]["prefix_sha256"] != prefix_sha:
            fail(f"{path.name}: ingest_stats prefix sha256 differs")
        members = whole_tar_members(prefix)
        if len(members) != ingest["tarballs"][tarball]["whole_members"]:
            fail(f"{tarball}: {len(members)} whole members, build saw {ingest['tarballs'][tarball]['whole_members']}")
        for name, offset, png in members:
            if not re.fullmatch(pins.MEMBER_NAME_PATTERN, name):
                fail(f"{tarball}: unexpected member {name}")
            header = ihdr_of(png)
            if header != (pins.WIDTH, pins.HEIGHT, 8, 0, 0, 0, 0):
                expected_skips.append({"tarball": tarball, "member": name, "ihdr": list(header)})
                if (tarball, name) in by_key:
                    fail(f"{tarball}:{name}: non-grayscale-8 image was emitted")
                continue
            pixels = decode_grayscale_png(png, pins.WIDTH, pins.HEIGHT)
            expected_order.append((tarball, name))
            row = by_key.get((tarball, name))
            if row is None:
                fail(f"{tarball}:{name} missing from index")
            sample_path = data_root / row["sample_path"]
            if sample_path.parent != sample_dir or sample_path.name != pins.sample_name(tarball, name):
                fail(f"{tarball}:{name}: unexpected sample path {row['sample_path']}")
            if sample_path.read_bytes() != pixels:
                fail(f"{row['sample_path']}: bytes differ from the independent decode")
            digest = hashlib.sha256(pixels).hexdigest()
            if digest in digests:
                fail(f"{tarball}:{name}: duplicate pixel payload")
            digests.add(digest)
            patients.add(name.rsplit("/", 1)[-1].split("_")[0])
            stats = pixel_statistics(pixels)
            if stats["min_value"] == stats["max_value"]:
                fail(f"{name}: constant image")
            if stats["distinct_values"] < pins.MIN_DISTINCT_VALUES:
                fail(f"{name}: {stats['distinct_values']} distinct values")
            if stats["modal_fraction"] > pins.MAX_MODAL_FRACTION:
                fail(f"{name}: modal fraction {stats['modal_fraction']}")
            expected_row = {
                "dataset_id": dataset_id,
                "series_id": pins.SERIES_ID,
                "role": "primary",
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": pins.WIDTH * pins.HEIGHT,
                "value_count": pins.WIDTH * pins.HEIGHT,
                "sample_rank": 2,
                "sample_shape": [pins.HEIGHT, pins.WIDTH],
                "source_member_bytes": len(png),
                "source_member_tar_offset": offset,
                "sha256": digest,
                **stats,
            }
            for key, value in expected_row.items():
                if row.get(key) != value:
                    fail(f"{tarball}:{name}: index {key}={row.get(key)!r}, expected {value!r}")
    if [(row["source_tarball"], row["source_member"]) for row in rows] != expected_order:
        fail("index order or membership differs from the tarball/tar-order walk")
    if ingest["skipped_non_gray8"] != expected_skips:
        fail(f"skip list differs: build {ingest['skipped_non_gray8']} verify {expected_skips}")
    if ingest["distinct_patients"] != len(patients):
        fail("distinct patient count differs")
    indexed_files = {Path(row["sample_path"]).name for row in rows}
    present_files = {path.name for path in sample_dir.iterdir()}
    if present_files != indexed_files:
        fail(f"sample directory has {len(present_files - indexed_files)} unindexed / {len(indexed_files - present_files)} missing files")

    aggregate = hashlib.sha256(
        "".join(f"{Path(row['sample_path']).name}\t{row['sha256']}\n" for row in rows).encode("ascii")
    ).hexdigest()
    if pins.AGGREGATE_SHA256 and aggregate != pins.AGGREGATE_SHA256:
        fail(f"aggregate SHA-256 {aggregate} != pinned {pins.AGGREGATE_SHA256}")
    if pins.TOTAL_SAMPLES and len(rows) != pins.TOTAL_SAMPLES:
        fail(f"{len(rows)} samples, expected {pins.TOTAL_SAMPLES}")

    counts = [row["value_count"] for row in rows]
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    if sum(counts) < MIN_TOTAL_VALUES and total_bytes < MIN_PRIMARY_BYTES:
        fail("aggregate floor failed")
    if statistics.median(counts) < MIN_MEDIAN_VALUES:
        fail("median sample floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        fail("primary bytes exceed the 1 GB cap")
    series = manifest.get("series", [])
    if len(series) != 1 or series[0].get("id") != pins.SERIES_ID:
        fail("manifest must declare exactly the one primary series")
    if series[0].get("sample_count") != len(rows) or series[0].get("total_size_bytes") != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
            f"!= realized {len(rows)}/{total_bytes}"
        )
    print(
        f"verified series={pins.SERIES_ID} samples={len(rows)} skipped={len(expected_skips)} "
        f"patients={len(patients)} total_bytes={total_bytes} aggregate_sha256={aggregate}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
