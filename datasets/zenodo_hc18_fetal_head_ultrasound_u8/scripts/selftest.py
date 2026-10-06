#!/usr/bin/env python3
"""Synthetic self-test for both HC18 decoders (build and verify paths).

A reference PNG encoder written here applies each scanline filter (0-4,
fixed per image and mixed per row) to random and structured grayscale
images, splits the zlib stream over several IDAT chunks and interleaves
ancillary chunks. Both decoders must reproduce the original pixels exactly
and must reject RGB, palette, tRNS, 16-bit, interlaced, wrong-size, bad-CRC,
bad-filter, trailing-data and non-consecutive-IDAT inputs. The build-side ZIP
central-directory reader is checked against stored, deflated and directory
members written by zipfile. Runs in memory plus one temporary directory.
"""
from __future__ import annotations

import random
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hc18_decode as build_side  # noqa: E402
import hc18_verify as verify_side  # noqa: E402


def chunk(kind: bytes, body: bytes, corrupt: bool = False) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    if corrupt:
        crc ^= 1
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_rows(pixels: bytes, width: int, height: int, filters: list[int]) -> bytes:
    out = bytearray()
    prev = [0] * width
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        ftype = filters[y]
        out.append(ftype)
        for x in range(width):
            a = row[x - 1] if x else 0
            b = prev[x]
            c = prev[x - 1] if x else 0
            predictor = [0, a, b, (a + b) >> 1, paeth(a, b, c)][ftype]
            out.append((row[x] - predictor) & 255)
        prev = list(row)
    return bytes(out)


def encode_png(
    pixels: bytes,
    width: int,
    height: int,
    filters: list[int],
    *,
    color_type: int = 0,
    bit_depth: int = 8,
    interlace: int = 0,
    idat_parts: int = 3,
    extra_before: list[bytes] | None = None,
    split_idat_with: bytes | None = None,
    corrupt_idat_crc: bool = False,
    trailing: bytes = b"",
    raw_override: bytes | None = None,
) -> bytes:
    raw = raw_override if raw_override is not None else filter_rows(pixels, width, height, filters)
    stream = zlib.compress(raw, 9)
    cut = sorted({0, len(stream), *random.sample(range(1, len(stream)), max(0, min(idat_parts - 1, len(stream) - 1)))})
    parts = [stream[cut[i] : cut[i + 1]] for i in range(len(cut) - 1)]
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace))
    png += chunk(b"pHYs", struct.pack(">IIB", 3780, 3780, 1))
    png += chunk(b"tIME", struct.pack(">HBBBBB", 2018, 7, 27, 12, 0, 0))
    for extra in extra_before or []:
        png += extra
    for i, part in enumerate(parts):
        png += chunk(b"IDAT", part, corrupt=corrupt_idat_crc and i == 0)
        if split_idat_with is not None and i == 0 and len(parts) > 1:
            png += split_idat_with
    png += chunk(b"tEXt", b"Comment\x00synthetic")
    png += chunk(b"IEND", b"")
    return png + trailing


def both_decode(png: bytes, width: int, height: int) -> tuple[bytes, bytes]:
    a, info = build_side.decode_png(png, width, height)
    b = verify_side.decode_grayscale_png(png, width, height)
    return a, b


def expect_failure(label: str, png: bytes, width: int, height: int) -> None:
    for name, func in (
        ("build", lambda: build_side.decode_png(png, width, height)),
        ("verify", lambda: verify_side.decode_grayscale_png(png, width, height)),
    ):
        try:
            func()
        except (ValueError, struct.error):
            continue
        raise SystemExit(f"selftest: {name} decoder accepted invalid input ({label})")


def test_png() -> int:
    rng = random.Random(1327317)
    random.seed(1322000)
    cases = 0
    shapes = [(1, 1), (1, 7), (7, 1), (37, 23), (64, 40)]
    for width, height in shapes:
        images = [
            bytes(rng.randrange(256) for _ in range(width * height)),
            bytes(((x * 7 + y * 13) ^ (x * y)) & 255 for y in range(height) for x in range(width)),
            bytes([0] * (width * height)),
            bytes([255] * (width * height)),
        ]
        filter_sets = [[f] * height for f in range(5)]
        filter_sets.append([y % 5 for y in range(height)])
        filter_sets.append([rng.randrange(5) for _ in range(height)])
        for pixels in images:
            for filters in filter_sets:
                png = encode_png(pixels, width, height, filters, idat_parts=rng.randrange(1, 6))
                a, b = both_decode(png, width, height)
                if a != pixels or b != pixels:
                    raise SystemExit(f"selftest: decode mismatch {width}x{height} filters={filters[:6]}")
                cases += 1
    # Full HC18 geometry with every filter type in one image.
    width, height = build_side.pins.WIDTH, build_side.pins.HEIGHT
    pixels = bytes(
        (rng.randrange(256) if (x // 50 + y // 30) % 3 == 0 else (x * 3 + y) & 255) if x > 20 else min(255, y // 2)
        for y in range(height)
        for x in range(width)
    )
    filters = [(y * 7) % 5 for y in range(height)]
    png = encode_png(pixels, width, height, filters, idat_parts=9)
    a, b = both_decode(png, width, height)
    if a != pixels or b != pixels:
        raise SystemExit("selftest: full-size decode mismatch")
    _, info = build_side.decode_png(png, width, height)
    if info["filter_rows"] != [sum(1 for f in filters if f == k) for k in range(5)]:
        raise SystemExit("selftest: filter row accounting mismatch")
    if info["ancillary"] != {"pHYs": 1, "tIME": 1, "tEXt": 1} or info["idat_chunks"] != 9:
        raise SystemExit(f"selftest: chunk accounting mismatch {info}")
    cases += 1

    # Negative cases on a small image.
    width, height = 9, 5
    pixels = bytes(rng.randrange(256) for _ in range(width * height))
    filters = [4] * height
    good = encode_png(pixels, width, height, filters)
    a, b = both_decode(good, width, height)
    assert a == pixels and b == pixels
    expect_failure("wrong size", good, width + 1, height)
    expect_failure("wrong height", good, width, height + 1)
    expect_failure("rgb", encode_png(pixels, width, height, filters, color_type=2), width, height)
    expect_failure(
        "palette",
        encode_png(pixels, width, height, filters, color_type=3, extra_before=[chunk(b"PLTE", bytes(range(48)))]),
        width,
        height,
    )
    expect_failure("tRNS", encode_png(pixels, width, height, filters, extra_before=[chunk(b"tRNS", b"\x00\x00")]), width, height)
    expect_failure("unknown critical chunk", encode_png(pixels, width, height, filters, extra_before=[chunk(b"ABCD", b"")]), width, height)
    expect_failure("16-bit", encode_png(pixels, width, height, filters, bit_depth=16), width, height)
    expect_failure("interlaced", encode_png(pixels, width, height, filters, interlace=1), width, height)
    expect_failure("bad CRC", encode_png(pixels, width, height, filters, corrupt_idat_crc=True), width, height)
    expect_failure("trailing data", encode_png(pixels, width, height, filters, trailing=b"\x00"), width, height)
    expect_failure(
        "split IDAT",
        encode_png(pixels, width, height, filters, idat_parts=3, split_idat_with=chunk(b"tEXt", b"a\x00b")),
        width,
        height,
    )
    bad_filter = bytearray(filter_rows(pixels, width, height, filters))
    bad_filter[(width + 1) * 2] = 5
    expect_failure("filter type 5", encode_png(pixels, width, height, filters, raw_override=bytes(bad_filter)), width, height)
    short_raw = filter_rows(pixels, width, height, filters)[:-1]
    expect_failure("short scanlines", encode_png(pixels, width, height, filters, raw_override=short_raw), width, height)
    expect_failure("not png", b"GIF89a" + good[6:], width, height)
    expect_failure("no IEND", good[: good.rfind(b"IEND") - 4], width, height)
    return cases


def test_zip() -> int:
    rng = random.Random(43518463)
    with tempfile.TemporaryDirectory(prefix="hc18_selftest_") as tmp:
        path = Path(tmp) / "synthetic.zip"
        members = {
            "set/000_HC.png": bytes(rng.randrange(256) for _ in range(5000)),
            "set/000_HC_Annotation.png": bytes(1000),
            "set/001_2HC.png": b"x" * 20000,
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(zipfile.ZipInfo("set/"), b"")
            archive.writestr("set/000_HC.png", members["set/000_HC.png"], compress_type=zipfile.ZIP_STORED)
            archive.writestr("set/000_HC_Annotation.png", members["set/000_HC_Annotation.png"], compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("set/001_2HC.png", members["set/001_2HC.png"], compress_type=zipfile.ZIP_DEFLATED)
        entries = build_side.read_central_directory(path)
        names = [entry["name"] for entry in entries]
        if names != ["set/", "set/000_HC.png", "set/000_HC_Annotation.png", "set/001_2HC.png"]:
            raise SystemExit(f"selftest: central directory names {names}")
        methods = {entry["name"]: entry["method"] for entry in entries}
        if methods["set/000_HC.png"] != 0 or methods["set/001_2HC.png"] != 8:
            raise SystemExit(f"selftest: central directory methods {methods}")
        with path.open("rb") as fh:
            for entry in entries[1:]:
                if build_side.read_member(fh, entry) != members[entry["name"]]:
                    raise SystemExit(f"selftest: member {entry['name']} mismatch")
            corrupt = dict(entries[3])
            corrupt["crc32"] ^= 1
            try:
                build_side.read_member(fh, corrupt)
            except build_side.DecodeError:
                pass
            else:
                raise SystemExit("selftest: CRC mismatch not detected")
        # Truncated archive (EOCD missing) must be rejected.
        broken = Path(tmp) / "broken.zip"
        broken.write_bytes(path.read_bytes()[:-30])
        try:
            build_side.read_central_directory(broken)
        except build_side.DecodeError:
            pass
        else:
            raise SystemExit("selftest: truncated archive accepted")
    for name, expected in [("000_HC.png", (0, 1)), ("010_2HC.png", (10, 2)), ("805_4HC.png", (805, 4))]:
        if build_side.pins.natural_key(name) != expected:
            raise SystemExit(f"selftest: natural_key({name})")
    return 3


def main() -> int:
    png_cases = test_png()
    zip_cases = test_zip()
    print(f"selftest ok png_roundtrip_cases={png_cases} zip_cases={zip_cases} negative_png_cases=15")
    return 0


if __name__ == "__main__":
    sys.exit(main())
