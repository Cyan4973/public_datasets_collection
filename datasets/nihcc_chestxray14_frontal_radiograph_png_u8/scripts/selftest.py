#!/usr/bin/env python3
"""Synthetic self-test for both ChestX-ray14 decoders (build and verify paths).

A reference PNG encoder written here applies each scanline filter (0-4, fixed
per image and mixed per row) to random and structured grayscale images, splits
the zlib stream over several IDAT chunks and adds ancillary chunks. Both
decoders must reproduce the original pixels exactly (including one full
1024x1024 image using all five filter types) and must reject RGB, palette,
tRNS, 16-bit, interlaced, wrong-size, bad-CRC, bad-filter, trailing-data and
non-consecutive-IDAT inputs. Both tar-prefix walkers are run on synthetic
ustar .tar.gz archives cut at many byte offsets and must agree on exactly the
whole members, and the build-side classifier must flag RGBA / grey+alpha /
16-bit members for skipping. Runs in memory only.
"""
from __future__ import annotations

import gzip
import io
import random
import struct
import sys
import tarfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nih_decode as build_side  # noqa: E402
import nih_verify as verify_side  # noqa: E402


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
    a, _info = build_side.decode_png(png, width, height)
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
    rng = random.Random(14)
    random.seed(2017)
    cases = 0
    for width, height in [(1, 1), (1, 7), (7, 1), (37, 23), (64, 40)]:
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
    # Full ChestX-ray14 geometry with every filter type in one image.
    width, height = build_side.pins.WIDTH, build_side.pins.HEIGHT
    pixels = bytes(
        (rng.randrange(256) if (x // 64 + y // 48) % 3 == 0 else (x * 3 + y) & 255) if x > 20 else min(255, y // 4)
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
    if info["ancillary"] != {"pHYs": 1, "tEXt": 1} or info["idat_chunks"] != 9:
        raise SystemExit(f"selftest: chunk accounting mismatch {info}")
    cases += 1

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


def test_tar_prefix() -> int:
    rng = random.Random(1024)
    random.seed(8)
    members = []
    for i in range(12):
        w, h = 16 + i, 9 + (i % 4)
        if i == 4:
            ct, depth, payload = 6, 8, bytes(rng.randrange(256) for _ in range(w * h * 4))  # RGBA
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ct, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(payload)) + chunk(b"IEND", b"")
        elif i == 7:
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 4, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(bytes(w * h * 2 + h))) + chunk(b"IEND", b"")
        else:
            pixels = bytes(rng.randrange(256) for _ in range(w * h))
            png = encode_png(pixels, w, h, [rng.randrange(5) for _ in range(h)])
        members.append((f"images/{10000000 + i * 37:08d}_{i:03d}.png", png))
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 1500000000
            tf.addfile(info, io.BytesIO(data))
        # padding so the archive is longer than any tested prefix
        info = tarfile.TarInfo("images/99999999_999.png")
        info.size = 300000
        tf.addfile(info, io.BytesIO(bytes(rng.randrange(256) for _ in range(300000))))
    gz_bytes = gzip.compress(tar_buf.getvalue(), compresslevel=6, mtime=0)
    checked = 0
    for cut in sorted({20, 400, 1500, 3000, len(gz_bytes) // 3, len(gz_bytes) // 2, len(gz_bytes) - 50000} | {rng.randrange(30, len(gz_bytes) - 40000) for _ in range(25)}):
        prefix = gz_bytes[:cut]
        inflated, ended = build_side.inflate_prefix(prefix)
        if ended:
            raise SystemExit("selftest: prefix unexpectedly ended")
        got_build, _summary = build_side.walk_tar(inflated)
        got_verify = verify_side.whole_tar_members(prefix)
        a = [(m["name"], m["data_offset"], m["data"]) for m in got_build]
        if a != got_verify:
            raise SystemExit(f"selftest: tar walkers disagree at cut {cut}: {len(a)} vs {len(got_verify)}")
        expected = []
        offset = 0
        for name, data in members + [("images/99999999_999.png", None)]:
            size = len(data) if data is not None else 300000
            if offset + 512 + size > len(inflated):
                break
            expected.append(name)
            offset += 512 + ((size + 511) // 512) * 512
        if [m[0] for m in a] != expected:
            raise SystemExit(f"selftest: whole-member set wrong at cut {cut}")
        for name, _off, data in a:
            ref = dict(members).get(name)
            if ref is not None and data != ref:
                raise SystemExit(f"selftest: member {name} data mismatch")
        checked += 1
    # classification of skip-worthy members
    full = dict(members)
    for idx, expect in ((4, False), (7, False), (0, False)):
        ihdr = build_side.png_ihdr(full[members[idx][0]])
        if build_side.qualifies(ihdr) != expect or verify_side.ihdr_of(full[members[idx][0]]) != tuple(ihdr):
            raise SystemExit(f"selftest: classification wrong for member {idx}")
    if not build_side.qualifies((1024, 1024, 8, 0, 0, 0, 0)) or build_side.qualifies((1024, 1024, 8, 6, 0, 0, 0)):
        raise SystemExit("selftest: qualifies() wrong")
    # bad magic and corrupted tar header checksum must be rejected
    for bad in (b"PK\x03\x04" + gz_bytes[4:3000],):
        try:
            build_side.inflate_prefix(bad)
        except build_side.DecodeError:
            pass
        else:
            raise SystemExit("selftest: bad gzip magic accepted")
    corrupted = bytearray(tar_buf.getvalue()[:4096])
    corrupted[10] ^= 0x20
    try:
        build_side.walk_tar(bytes(corrupted))
    except build_side.DecodeError:
        pass
    else:
        raise SystemExit("selftest: tar header checksum corruption accepted")
    return checked


def main() -> int:
    png_cases = test_png()
    tar_cases = test_tar_prefix()
    print(f"selftest ok png_roundtrip_cases={png_cases} negative_png_cases=15 tar_prefix_cuts={tar_cases}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
