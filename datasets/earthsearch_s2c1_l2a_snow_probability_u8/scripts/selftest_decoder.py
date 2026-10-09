#!/usr/bin/env python3
"""Self-test snw_cog.decode on a synthetic 5490x5490 tiled TIFF.

Builds a TIFF with the exact SNW_20m layout (Deflate + predictor 2, 512x512
tiles, padded edge tiles filled with junk) from a known pseudo-random grid,
then checks the decoder reproduces the grid byte-exactly and rejects a
truncated file and a wrong predictor.
"""
from __future__ import annotations

import random
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snw_cog  # noqa: E402

W = H = snw_cog.WIDTH
T = snw_cog.TILE


def make_grid(seed: int) -> bytearray:
    rnd = random.Random(seed)
    g = bytearray(W * H)
    for y in range(0, H, 7):
        v = rnd.choice([0, 0, 100, 100, rnd.randrange(101)])
        n = min(7, H - y)
        for dy in range(n):
            row = bytearray(rnd.choice([v, rnd.randrange(101)]) for _ in range(0, W, 61))
            full = bytes(b for b in row for _ in range(61))[:W]
            g[(y + dy) * W:(y + dy + 1) * W] = full
    for _ in range(20000):
        g[rnd.randrange(W * H)] = rnd.randrange(256)
    return g


def make_tiff(grid: bytes, predictor: int = 2) -> bytes:
    across = (W + T - 1) // T
    tiles = []
    rnd = random.Random(7)
    for ty in range(across):
        for tx in range(across):
            buf = bytearray(rnd.randrange(256) for _ in range(T)) * T  # junk padding
            for r in range(T):
                y = ty * T + r
                if y >= H:
                    break
                x0 = tx * T
                cw = min(T, W - x0)
                buf[r * T:r * T + cw] = grid[y * W + x0:y * W + x0 + cw]
            # forward predictor 2
            enc = bytearray(buf)
            for r in range(T):
                for x in range(T - 1, 0, -1):
                    enc[r * T + x] = (buf[r * T + x] - buf[r * T + x - 1]) & 255
            tiles.append(zlib.compress(bytes(enc), 6))
    entries = [(256, 3, 1, W), (257, 3, 1, H), (258, 3, 1, 8), (259, 3, 1, 8), (262, 3, 1, 1),
               (277, 3, 1, 1), (284, 3, 1, 1), (317, 3, 1, predictor), (322, 3, 1, T), (323, 3, 1, T),
               (324, 4, len(tiles), None), (325, 4, len(tiles), None), (339, 3, 1, 1), (42113, 2, 2, b"0\x00")]
    n = len(entries)
    ifd_off = 8
    extra_off = ifd_off + 2 + n * 12 + 4
    offs_off = extra_off
    cnts_off = offs_off + 4 * len(tiles)
    data_off = cnts_off + 4 * len(tiles)
    offsets, pos = [], data_off
    for t in tiles:
        offsets.append(pos)
        pos += len(t)
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_off) + struct.pack("<H", n))
    for tag, ft, cnt, val in entries:
        if tag == 324:
            out += struct.pack("<HHII", tag, ft, cnt, offs_off)
        elif tag == 325:
            out += struct.pack("<HHII", tag, ft, cnt, cnts_off)
        elif ft == 2:
            out += struct.pack("<HHI", tag, ft, cnt) + val.ljust(4, b"\x00")
        else:
            out += struct.pack("<HHIHH", tag, ft, cnt, val, 0)
    out += struct.pack("<I", 0)
    out += struct.pack(f"<{len(tiles)}I", *offsets)
    out += struct.pack(f"<{len(tiles)}I", *[len(t) for t in tiles])
    for t in tiles:
        out += t
    return bytes(out)


def main() -> None:
    grid = make_grid(1)
    tif = make_tiff(grid)
    got = snw_cog.decode(tif)
    assert got == bytes(grid), "decoded grid differs from synthetic source"
    for bad, label in ((tif[:-1000], "truncated"), (make_tiff(grid, predictor=1), "predictor 1")):
        try:
            snw_cog.decode(bad)
        except snw_cog.SnwFormatError as exc:
            print(f"rejected {label}: {exc}")
        else:
            raise SystemExit(f"decoder accepted {label} TIFF")
    print("selftest_ok synthetic 5490x5490 Deflate+predictor2 grid decoded byte-exact")


if __name__ == "__main__":
    main()
