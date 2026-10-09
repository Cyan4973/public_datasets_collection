"""Self-test for hdrplus_dng: round-trips synthetic lossless-JPEG streams
through the reference encoder and the decoder, then decodes a synthetic tiled
CFA DNG (edge tiles cropped). Exits non-zero on any mismatch."""
from __future__ import annotations

import random
import struct
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdrplus_dng as hd  # noqa: E402


def synth(width, height, nc, precision, rng, mode):
    top = (1 << precision) - 1
    vals = []
    for y in range(height):
        for x in range(width):
            for c in range(nc):
                if mode == "smooth":
                    v = int((x * 7 + y * 3 + c * 50) % (top + 1))
                    v = min(top, max(0, v + rng.randint(-3, 3)))
                elif mode == "noise":
                    v = rng.randint(0, top)
                else:  # extremes: force +/- full-range differences
                    v = top if (x + y + c) % 2 else 0
                vals.append(v)
    return vals


def check_stream(width, height, nc, precision, predictor, pt, ri, mode, rng, tables=None):
    vals = synth(width, height, nc, precision, rng, mode)
    if pt:
        vals = [(v >> pt) << pt for v in vals]
    enc = hd.encode_lj92(vals, width, height, nc, precision, predictor, pt, ri, tables)
    hdr, dec = hd.decode_lj92(enc)
    if list(dec) != vals:
        bad = next(k for k, (a, b) in enumerate(zip(dec, vals)) if a != b)
        raise SystemExit(f"FAIL stream w={width} h={height} nc={nc} P={precision} pred={predictor} "
                         f"pt={pt} ri={ri} mode={mode}: first mismatch at {bad}: {dec[bad]} != {vals[bad]}")
    return len(vals)


def build_dng(width, height, tw, tl, nc_per_tile, precision, rng):
    """Minimal little-endian tiled CFA DNG with LJ92 tiles (2 comps x tw/2)."""
    full = [[0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            base = 64 + ((x % 2) * 100) + ((y % 2) * 200)
            full[y][x] = min(1023, max(0, base + (x * y) % 37 + rng.randint(0, 5)))
    ta, td = -(-width // tw), -(-height // tl)
    tiles = []
    for ty in range(td):
        for tx in range(ta):
            vals = []
            for r in range(tl):
                for cidx in range(tw):
                    y, x = ty * tl + r, tx * tw + cidx
                    vals.append(full[y][x] if (y < height and x < width) else 0)
            tiles.append(hd.encode_lj92(vals, tw // nc_per_tile, tl, nc_per_tile, precision, 1))
    entries = []

    def ent(tag, typ, cnt, payload):
        entries.append((tag, typ, cnt, payload))

    n_tiles = len(tiles)
    ent(254, 4, 1, struct.pack("<I", 0))
    ent(256, 4, 1, struct.pack("<I", width))
    ent(257, 4, 1, struct.pack("<I", height))
    ent(258, 3, 1, struct.pack("<H", 16))
    ent(259, 3, 1, struct.pack("<H", 7))
    ent(262, 3, 1, struct.pack("<H", 32803))
    ent(271, 2, 7, b"google\0")
    ent(272, 2, 9, b"sailfish\0")
    ent(277, 3, 1, struct.pack("<H", 1))
    ent(322, 4, 1, struct.pack("<I", tw))
    ent(323, 4, 1, struct.pack("<I", tl))
    ent(324, 4, n_tiles, None)  # offsets filled later
    ent(325, 4, n_tiles, struct.pack(f"<{n_tiles}I", *[len(t) for t in tiles]))
    ent(33421, 3, 2, struct.pack("<HH", 2, 2))
    ent(33422, 1, 4, bytes([2, 1, 1, 0]))
    ent(50714, 5, 4, struct.pack("<8I", 16320, 256, 16256, 256, 16256, 256, 16320, 256))
    ent(50717, 3, 1, struct.pack("<H", 1023))
    entries.sort()
    ifd_off = 8
    ifd_size = 2 + 12 * len(entries) + 4
    extra_off = ifd_off + ifd_size
    blobs = bytearray()
    tile_data_off = None
    fixed = []
    for tag, typ, cnt, payload in entries:
        if tag == 324:
            payload = b"\0" * (4 * cnt)
        fixed.append((tag, typ, cnt, payload))
    # layout: header, IFD, out-of-line values, tile data
    value_offsets = {}
    for tag, typ, cnt, payload in fixed:
        if len(payload) > 4:
            value_offsets[tag] = extra_off + len(blobs)
            blobs += payload
            if len(blobs) % 2:
                blobs += b"\0"
    tile_data_off = extra_off + len(blobs)
    offsets = []
    pos = tile_data_off
    for t in tiles:
        offsets.append(pos)
        pos += len(t)
    off324 = value_offsets[324] - extra_off
    blobs[off324:off324 + 4 * n_tiles] = struct.pack(f"<{n_tiles}I", *offsets)
    out = bytearray(b"II" + struct.pack("<HI", 42, ifd_off))
    out += struct.pack("<H", len(fixed))
    for tag, typ, cnt, payload in fixed:
        if len(payload) > 4:
            out += struct.pack("<HHII", tag, typ, cnt, value_offsets[tag])
        else:
            out += struct.pack("<HHI", tag, typ, cnt) + payload.ljust(4, b"\0")
    out += struct.pack("<I", 0)
    out += blobs
    for t in tiles:
        out += t
    expect = array("H", [full[y][x] for y in range(height) for x in range(width)])
    return bytes(out), expect


def main() -> int:
    rng = random.Random(20261008)
    n = 0
    # every predictor, several component counts / precisions / point transforms
    for predictor in range(1, 8):
        for nc in (1, 2, 4):
            for precision, pt in ((10, 0), (12, 2), (16, 0)):
                for mode in ("smooth", "noise"):
                    n += check_stream(9, 7, nc, precision, predictor, pt, 0, mode, rng)
    # restart intervals (multiples of the row width)
    for predictor in (1, 4, 7):
        n += check_stream(8, 9, 2, 12, predictor, 0, 16, "noise", rng)
        n += check_stream(5, 6, 1, 16, predictor, 0, 5, "smooth", rng)
    # extreme differences incl. SSSS=16 (diff -32768) at 16-bit precision
    for predictor in (1, 2, 7):
        n += check_stream(6, 5, 2, 16, predictor, 0, 0, "extreme", rng)
    # Huffman table shaped like the HDR+ tiles (short codes, max SSSS 15)
    bits = bytes([0, 0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2])
    order = bytes([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    assert sum(bits) == len(order)
    n += check_stream(16, 12, 2, 16, 1, 0, 0, "smooth", rng, tables=[(bits, order)] * 2)
    print(f"lj92 stream round-trips ok ({n} samples)")

    # synthetic tiled DNG: 2 comps per LJ92 row, edge tiles cropped
    width, height, tw, tl = 52, 37, 16, 16
    dng, expect = build_dng(width, height, tw, tl, 2, 16, rng)
    tags = hd.parse_tiff_ifd0(dng)
    info = hd.dng_raw_info(tags)
    assert info["cfa_pattern"] == "BGGR", info["cfa_pattern"]
    assert info["black_level"] == [63.75, 63.5, 63.5, 63.75], info["black_level"]
    info2, frame = hd.decode_dng_cfa(dng, info)
    if list(frame) != list(expect):
        bad = next(k for k, (a, b) in enumerate(zip(frame, expect)) if a != b)
        raise SystemExit(f"FAIL synthetic DNG mismatch at {bad}: {frame[bad]} != {expect[bad]}")
    le = hd.frame_le_bytes(frame)
    assert le[:2] == struct.pack("<H", expect[0])
    print(f"synthetic DNG tile reassembly ok ({width}x{height}, {info['tile_count']} tiles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
