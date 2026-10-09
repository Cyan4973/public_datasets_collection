#!/usr/bin/env python3
"""Self-test for scripts/tumvi_lib.py on synthetic inputs.

Builds 16-bit grayscale PNGs whose rows cycle through all five PNG filter
types (with a reference encoder written independently here), decodes them,
and checks byte-exact recovery; also checks the tar prefix walk and the
rejection paths (bad CRC, wrong IHDR, truncation, interlace).

Usage: python3 -I scripts/selftest.py
"""
from __future__ import annotations

import io
import random
import struct
import sys
import tarfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tumvi_lib as L  # noqa: E402


def chunk(t: bytes, p: bytes) -> bytes:
    return struct.pack(">I", len(p)) + t + p + struct.pack(">I", zlib.crc32(t + p) & 0xFFFFFFFF)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def encode(vals, w, h, filters, depth=16, ctype=0, interlace=0, split_idat=3):
    bpp = 2
    stride = w * bpp
    rows = []
    for y in range(h):
        rows.append(b"".join(struct.pack(">H", v) for v in vals[y * w:(y + 1) * w]))
    raw = bytearray()
    prev = bytes(stride)
    for y, line in enumerate(rows):
        ft = filters[y % len(filters)]
        raw.append(ft)
        for i in range(stride):
            x = line[i]
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = [0, a, b, (a + b) // 2, paeth(a, b, c)][ft]
            raw.append((x - pred) & 0xFF)
        prev = line
    z = zlib.compress(bytes(raw), 6)
    step = max(1, len(z) // split_idat)
    idats = b"".join(chunk(b"IDAT", z[i:i + step]) for i in range(0, len(z), step))
    hdr = struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, interlace)
    return L.PNG_SIG + chunk(b"IHDR", hdr) + chunk(b"tEXt", b"k\0v") + idats + chunk(b"IEND", b"")


def expect_fail(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise SystemExit(f"selftest: expected failure not raised: {label}")


def main() -> None:
    rng = random.Random(1234)
    w, h = 37, 23
    for pattern in ([0, 1, 2, 3, 4], [4, 3, 2, 1, 0], [1], [3], [4]):
        vals = [rng.randrange(0, 4096) << 4 for _ in range(w * h)]
        # include extremes and a smooth ramp region
        vals[0], vals[1], vals[-1] = 0, 65535, 65520
        for i in range(w):
            vals[w + i] = (i * 1771) & 0xFFFF
        png = encode(vals, w, h, pattern)
        chunks, out = L.decode_png_gray16(png, w, h)
        if list(out) != vals:
            raise SystemExit(f"selftest: decode mismatch for filters {pattern}")
        le = L.le_bytes(out)
        if le != b"".join(struct.pack("<H", v) for v in vals):
            raise SystemExit("selftest: little-endian serialisation mismatch")
        st = L.frame_stats(out)
        if st["max"] != 65535 or st["min"] != 0 or st["low_nibble_nonzero"] != sum(1 for v in vals if v & 15):
            raise SystemExit(f"selftest: stats mismatch {st}")
        if L.last_idat_crc(chunks) != f"{[c for c in chunks if c[0] == b'IDAT'][-1][2]:08x}":
            raise SystemExit("selftest: last idat crc")
    vals = [rng.randrange(65536) for _ in range(w * h)]
    good = encode(vals, w, h, [0, 1, 2, 3, 4])
    bad = bytearray(good)
    bad[60] ^= 0x01
    expect_fail(lambda: L.decode_png_gray16(bytes(bad), w, h), "bad CRC")
    expect_fail(lambda: L.decode_png_gray16(good[:-5], w, h), "truncated")
    expect_fail(lambda: L.decode_png_gray16(good + b"x", w, h), "trailing bytes")
    expect_fail(lambda: L.decode_png_gray16(good, w + 1, h), "wrong size")
    expect_fail(lambda: L.decode_png_gray16(encode(vals, w, h, [0], interlace=1), w, h), "interlace")
    expect_fail(lambda: L.decode_png_gray16(encode(vals, w, h, [0], ctype=4), w, h), "colour type")
    # filter-type byte 7 inside a valid stream
    z = zlib.compress(bytes([7]) + bytes(2 * w) + bytes((2 * w + 1) * (h - 1)))
    bad_ft = L.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)) + chunk(b"IDAT", z) + chunk(b"IEND", b"")
    expect_fail(lambda: L.decode_png_gray16(bad_ft, w, h), "filter type")

    # tar prefix walk: directories + two PNG members, prefix cut inside the 3rd
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for d in ["dataset-room1_1024_16/", "dataset-room1_1024_16/mav0/"]:
            ti = tarfile.TarInfo(d)
            ti.type = tarfile.DIRTYPE
            tf.addfile(ti)
        for k in range(3):
            data = encode([rng.randrange(65536) for _ in range(w * h)], w, h, [k % 5])
            ti = tarfile.TarInfo(f"dataset-room1_1024_16/mav0/cam1/data/15205303909033359{k:02d}.png")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    full = bio.getvalue()
    members = list(L.walk_tar_prefix(full))
    if [m[0] for m in members][2:] != [f"dataset-room1_1024_16/mav0/cam1/data/15205303909033359{k:02d}.png" for k in range(3)]:
        raise SystemExit(f"selftest: tar walk names {members}")
    end2 = members[3][2] + members[3][3]
    cut = list(L.walk_tar_prefix(full[:end2]))
    if len(cut) != 4 or cut[-1][2] + cut[-1][3] != end2:
        raise SystemExit("selftest: exact-end prefix should keep member 2")
    cut = list(L.walk_tar_prefix(full[:end2 + 700]))
    if len(cut) != 4:
        raise SystemExit("selftest: partial third member must be dropped")
    for name, typ, off, size in members[2:]:
        L.decode_png_gray16(full[off:off + size], w, h)
    if not L.member_regex("room1").match(members[2][0]) or L.member_regex("room1").match(
            "dataset-room1_1024_16/mav0/cam0/data/1520530390903335995.png"):
        raise SystemExit("selftest: member regex")
    print("selftest ok: png filters 0-4, rejection paths, tar prefix walk")


if __name__ == "__main__":
    main()
