#!/usr/bin/env python3
"""Self-test the pure-Python TIFF LZW + predictor-2 decoder on synthetic TIFFs.

Builds a full 2048 x 2048 8-bit LZW/predictor-2 TIFF (4-row strips like the
source files) whose strips mix content regimes that exercise every decoder
path: pseudo-random bytes (fills the 12-bit table and forces clear codes),
constant rows (long KwKwK runs, code == next_code), off-axis-like fringe
patterns, and gradients with wrap-around. Also checks that layout deviations
are rejected.
"""

from __future__ import annotations

import math
from pathlib import Path
import random
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dhm_tiff  # noqa: E402

W = H = 2048
RPS = 4


def synthetic_pixels(seed: int = 12345) -> bytes:
    rng = random.Random(seed)
    buf = bytearray(W * H)
    for r in range(H):
        regime = (r // RPS) % 4
        base = r * W
        if regime == 0:
            buf[base : base + W] = rng.randbytes(W)
        elif regime == 1:
            buf[base : base + W] = bytes([(r * 7) & 255]) * W
        elif regime == 2:
            for c in range(W):
                v = 128 + 100 * math.cos(2 * math.pi * (c / 3.6 + r / 3.9)) + rng.gauss(0, 6)
                buf[base + c] = max(0, min(255, int(v)))
        else:
            for c in range(W):
                buf[base + c] = (c * 3 + r) & 255
    return bytes(buf)


def main() -> int:
    pixels = synthetic_pixels()
    for legacy_mode in (True, False):
        tiff = dhm_tiff.build_synthetic_tiff(pixels, W, H, RPS, legacy_eoi=legacy_mode)
        decoded, meta = dhm_tiff.decode_frame(tiff)
        if decoded != pixels:
            bad = next(i for i, (a, b) in enumerate(zip(decoded, pixels)) if a != b)
            print(f"FAIL: round-trip mismatch at pixel {bad} legacy={legacy_mode}", file=sys.stderr)
            return 1
        if meta["strips"] != H // RPS:
            print("FAIL: strip count", file=sys.stderr)
            return 1
        if not legacy_mode and meta["legacy_eoi_strips"]:
            print("FAIL: modern encoder reported legacy EOI", file=sys.stderr)
            return 1

    # Find payloads whose final code lands exactly on a width boundary, so the
    # legacy (no final widen) and modern encoders differ; both must decode and
    # be classified correctly.
    rng = random.Random(99)
    boundary_cases = 0
    for length in range(300, 6000):
        sample = rng.randbytes(length)
        modern = dhm_tiff.lzw_encode(sample)
        legacy = dhm_tiff.lzw_encode(sample, legacy_eoi=True)
        if modern == legacy:
            continue
        out_m, flag_m = dhm_tiff.lzw_decode(modern, length)
        out_l, flag_l = dhm_tiff.lzw_decode(legacy, length)
        if out_m != sample or out_l != sample or flag_m or not flag_l:
            print(f"FAIL: boundary EOI case len={length}", file=sys.stderr)
            return 1
        boundary_cases += 1
        if boundary_cases >= 3:
            break
    if boundary_cases < 3:
        print("FAIL: no width-boundary EOI cases exercised", file=sys.stderr)
        return 1
    # Wrong expected length must fail (EOI too early / stream overrun).
    sample = rng.randbytes(5000)
    enc = dhm_tiff.lzw_encode(sample)
    for wrong in (4999, 5001):
        try:
            dhm_tiff.lzw_decode(enc, wrong)
        except dhm_tiff.TiffFormatError:
            continue
        print(f"FAIL: wrong expected length {wrong} accepted", file=sys.stderr)
        return 1

    # Direct LZW edge cases: empty-ish, KwKwK, table overflow.
    for sample in (b"\x00", b"ab" * 5000, bytes(range(256)) * 40, random.Random(7).randbytes(30000)):
        enc = dhm_tiff.lzw_encode(sample)
        if dhm_tiff.lzw_decode(enc, len(sample))[0] != sample:
            print(f"FAIL: lzw round trip len={len(sample)}", file=sys.stderr)
            return 1

    # Layout rejections: patch tags in a small valid header.
    def patched(tag: int, value: int) -> bytes:
        data = bytearray(tiff)
        (count,) = struct.unpack_from("<H", data, 8)
        for i in range(count):
            off = 10 + 12 * i
            t, typ = struct.unpack_from("<HH", data, off)
            if t == tag:
                if typ == 3:
                    struct.pack_into("<H", data, off + 8, value)
                else:
                    struct.pack_into("<I", data, off + 8, value)
                return bytes(data)
        raise AssertionError(tag)

    for tag, value in ((256, 1024), (258, 16), (259, 1), (317, 1), (262, 2), (277, 3)):
        try:
            dhm_tiff.decode_frame(patched(tag, value))
        except dhm_tiff.TiffFormatError:
            continue
        print(f"FAIL: layout deviation tag={tag} value={value} not rejected", file=sys.stderr)
        return 1

    # Corrupted LZW stream must fail, not silently produce pixels.
    corrupt = bytearray(tiff)
    tags = dhm_tiff.parse_ifd(tiff)
    first = tags[273][0]
    corrupt[first + 5] ^= 0xFF
    corrupt[first + 6] ^= 0x5A
    try:
        out, _ = dhm_tiff.decode_frame(bytes(corrupt))
        if out == pixels:
            print("FAIL: corruption had no effect", file=sys.stderr)
            return 1
    except dhm_tiff.TiffFormatError:
        pass
    print(
        f"selftest_tiff=ok synthetic={W}x{H} strips={meta['strips']} tiff_bytes={len(tiff)} "
        f"boundary_eoi_cases={boundary_cases}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
