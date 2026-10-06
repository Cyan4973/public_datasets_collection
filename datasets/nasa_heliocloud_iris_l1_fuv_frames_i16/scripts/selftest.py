#!/usr/bin/env python3
"""Self-test of both RICE_1 decoders, the FITS header walkers and checksums.

A literal Python port of CFITSIO fits_rcomp_short (ricecomp.c: fsbits 4,
fsmax 14, bbits 16, zigzag mapping, zero-block code, byte-boundary flush)
encodes synthetic int16 rows that exercise every block type (all-zero
difference blocks, fs = 0 unary-only, fs = 1..13 split, fs = 14 verbatim),
the -32768 BLANK edges, full-range wrap-around differences and a short last
block (4144 = 129 * 32 + 16). Both decoders (iris_fits.rice_decode_tile and
verify.py's byte-wise port) must reproduce every row exactly and must reject
truncated or over-long tiles. A synthetic tile-compressed FITS file is then
written and decoded end to end by build.decode_frame and verify's walker,
including the DATASUM / CHECKSUM arithmetic.
"""

from __future__ import annotations

import random
import struct
import sys
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import iris_fits  # noqa: E402
import verify as vfy  # noqa: E402


# ------------------------------------------------- CFITSIO encoder port
def rcomp_short(values: list[int], nblock: int = 32) -> tuple[bytes, list[int]]:
    """Encode signed int16 values like fits_rcomp_short; return (bytes, fs codes)."""
    fsbits, fsmax, bbits = 4, 14, 16
    bits: list[str] = []
    first = values[0] & 0xFFFF
    seed = bytes([first >> 8, first & 0xFF])
    codes = []
    lastpix = values[0]
    for i in range(0, len(values), nblock):
        block = values[i:i + nblock]
        diffs = []
        pixelsum = 0.0
        for nextpix in block:
            pdiff = (nextpix - lastpix + 0x8000) & 0xFFFF
            pdiff -= 0x8000                       # C short wrap-around
            mapped = ~(pdiff << 1) if pdiff < 0 else (pdiff << 1)
            diffs.append(mapped)
            pixelsum += mapped
            lastpix = nextpix
        n = len(block)
        dpsum = (pixelsum - (n // 2) - 1) / n
        if dpsum < 0:
            dpsum = 0.0
        psum = int(dpsum) >> 1
        fs = 0
        while psum > 0:
            psum >>= 1
            fs += 1
        if fs >= fsmax:
            codes.append(fsmax)
            bits.append(format(fsmax + 1, "04b"))
            bits.extend(format(d, "016b") for d in diffs)
        elif fs == 0 and pixelsum == 0:
            codes.append(-1)
            bits.append("0000")
        else:
            codes.append(fs)
            bits.append(format(fs + 1, "04b"))
            for d in diffs:
                top = d >> fs
                bits.append("0" * top + "1")
                if fs:
                    bits.append(format(d & ((1 << fs) - 1), f"0{fs}b"))
    stream = "".join(bits)
    stream += "0" * (-len(stream) % 8)
    body = int(stream, 2).to_bytes(len(stream) // 8, "big") if stream else b""
    del bbits, fsbits
    return seed + body, codes


def synthetic_rows(rng: random.Random, nx: int) -> list[list[int]]:
    rows = []
    rows.append([110] * nx)                                         # zero blocks only
    rows.append([110 + (rng.random() < 0.3) for _ in range(nx)])    # fs 0
    rows.append([rng.randint(95, 140) for _ in range(nx)])          # small fs
    rows.append([rng.randint(0, 16383) for _ in range(nx)])         # fs ~ 12-13
    rows.append([rng.randint(-32768, 32767) for _ in range(nx)])    # fs 14 verbatim
    mixed = []
    for i in range(nx):                                             # BLANK edges + lines
        if i < 24 or 2048 <= i < 2096 or i >= nx - 32:
            mixed.append(-32768)
        elif i % 997 < 6:
            mixed.append(rng.randint(5000, 16383))
        else:
            mixed.append(rng.randint(100, 125))
    rows.append(mixed)
    rows.append([(-32768 if (i // 32) % 2 else 32767) for i in range(nx)])  # max wrap
    graded = []
    for i in range(nx):                                             # every fs level
        spread = 1 << ((i // 32) % 15)
        graded.append(max(-32768, min(32767, rng.randint(-spread, spread))))
    rows.append(graded)
    return rows


def check_decoders() -> None:
    rng = random.Random(20261005)
    seen_codes = set()
    for nx in (4144, 32, 33, 1, 4145):
        for row in synthetic_rows(rng, nx):
            tile, codes = rcomp_short(row)
            seen_codes.update(codes)
            want = array("h", row)
            a = array("h", iris_fits.rice_decode_tile(tile, nx).tobytes())
            b = array("h", vfy.rice_decode_bytewise(tile, nx).tobytes())
            if a != want or b != want:
                raise SystemExit(f"selftest: decoder mismatch (nx={nx})")
            for label, bad in (("truncated", tile[:-1]), ("over-long", tile + b"\x00")):
                for fn in (iris_fits.rice_decode_tile, vfy.rice_decode_bytewise):
                    try:
                        fn(bad, nx)
                    except Exception:
                        continue
                    raise SystemExit(f"selftest: {fn.__name__} accepted a {label} tile (nx={nx})")
    missing = set(range(-1, 15)) - seen_codes
    if missing:
        raise SystemExit(f"selftest: block codes never exercised: {sorted(missing)}")
    print(f"selftest decoders ok block_codes={sorted(seen_codes)}")


# ------------------------------------------------- synthetic FITS
def card(key: str, value) -> bytes:
    if isinstance(value, bool):
        v = f"{'T' if value else 'F':>20}"
    elif isinstance(value, int):
        v = f"{value:>20d}"
    elif isinstance(value, float):
        v = f"{value:>20.6f}"
    else:
        v = f"'{value:<8}'"
    return f"{key:<8}= {v}".ljust(80).encode("ascii")


def header_bytes(cards: list[bytes]) -> bytes:
    raw = b"".join(cards) + b"END".ljust(80)
    return raw + b" " * (-len(raw) % 2880)


def encode_checksum(total: int) -> str:
    """FITS ASCII-encoded complement checksum (Seaman et al.)."""
    value = (~total) & 0xFFFFFFFF
    exclude = set(range(0x3A, 0x41)) | set(range(0x5B, 0x61))
    asc = [0] * 16
    for i in range(4):
        byte = (value >> (24 - 8 * i)) & 0xFF
        quotient, remainder = byte // 4 + 0x30, byte % 4
        ch = [quotient] * 4
        ch[0] += remainder
        changed = True
        while changed:
            changed = False
            for j in range(0, 4, 2):
                if ch[j] in exclude or ch[j + 1] in exclude:
                    ch[j] += 1
                    ch[j + 1] -= 1
                    changed = True
        for j in range(4):
            asc[4 * j + i] = ch[j]
    text = bytes(asc)
    return (text[-1:] + text[:-1]).decode("ascii")


def compand(value: int) -> int:
    """Snap a DN value to a square-root companding lattice (step 2 DN at ~110 DN)."""
    # levels v_i = (i / sqrt(110))**2 have spacing 2 * sqrt(v / 110): 2 DN at 110 DN,
    # ~12 DN at 4,000 DN.
    scale = 110 ** 0.5
    return min(16383, int(round((round(value ** 0.5 * scale) / scale) ** 2)))


def synthetic_fits(rng: random.Random, companded: bool = False) -> tuple[bytes, array]:
    nx, ny = 4144, 1096
    tsr, ter = 25, 1072
    image = array("h")
    for r in range(ny):
        for c in range(nx):
            inside = (tsr - 1 <= r <= ter - 1) and (c < 2048 or 2096 <= c < 4112)
            if not inside:
                image.append(-32768)
                continue
            if rng.random() < 0.002:
                v = rng.randint(2000, 16383)
            else:
                v = rng.randint(96, 130)
            image.append(compand(v) if companded else v)
    tiles = []
    for r in range(ny):
        tiles.append(rcomp_short(list(image[r * nx:(r + 1) * nx]))[0])
    table = b"".join(struct.pack(">ii", len(t), sum(len(x) for x in tiles[:i]))
                     for i, t in enumerate(tiles))
    heap = b"".join(tiles)
    data = table + heap
    data_padded = data + b"\x00" * (-len(data) % 2880)
    valid = sorted(v for v in image if v != -32768)
    n = len(valid)
    cards = [
        card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2), card("NAXIS1", 8),
        card("NAXIS2", ny), card("PCOUNT", len(heap)), card("GCOUNT", 1), card("TFIELDS", 1),
        card("TTYPE1", "COMPRESSED_DATA"), card("TFORM1", f"1PB({max(len(t) for t in tiles)})"),
        card("ZIMAGE", True), card("ZBITPIX", 16), card("ZNAXIS", 2), card("ZNAXIS1", nx),
        card("ZNAXIS2", ny), card("ZTILE1", nx), card("ZTILE2", 1), card("ZCMPTYPE", "RICE_1"),
        card("ZNAME1", "BLOCKSIZE"), card("ZVAL1", 32), card("ZNAME2", "BYTEPIX"), card("ZVAL2", 2),
        card("TELESCOP", "IRIS"), card("LVL_NUM", 1.0), card("T_OBS", "2026-10-05T00:00:00.00Z"),
        card("FSN", 1), card("INSTRUME", "FUV"), card("IMG_PATH", "FUV"), card("IMG_TYPE", "LIGHT"),
        card("CAMERA", 1), card("SUMSPTRL", 1), card("SUMSPAT", 1), card("EXPTIME", 30.0),
        card("TOTVALS", n), card("DATAVALS", n), card("MISSVALS", 0),
        card("DATAMIN", valid[0]), card("DATAMAX", valid[-1]), card("DATAMEDN", valid[n // 2]),
        card("DATAMEAN", sum(valid) / n),
        card("CRS_TYPE", "FUV"), card("CRS_NREG", 2),
        card("TSR1", tsr), card("TER1", ter), card("TSC1", 1), card("TEC1", 2048),
        card("TSR2", tsr), card("TER2", ter), card("TSC2", 2097), card("TEC2", 4112),
    ]
    for r in range(3, 9):
        cards += [card(f"TSR{r}", 0), card(f"TER{r}", 0), card(f"TSC{r}", 0), card(f"TEC{r}", 0)]
    cards += [card("ISQOLTID", 3893012099), card("LUTID", 0), card("BLANK", -32768)]
    datasum = iris_fits.ones_complement_sum(data_padded)
    cards += [card("CHECKSUM", "0000000000000000"), card("DATASUM", str(datasum))]
    hdr = header_bytes(cards)
    total = iris_fits.ones_complement_sum(hdr, datasum)
    cards[-2] = card("CHECKSUM", encode_checksum(total))
    hdr = header_bytes(cards)
    primary = header_bytes([card("SIMPLE", True), card("BITPIX", 16), card("NAXIS", 0),
                            card("EXTEND", True)])
    return primary + hdr + data_padded, image


def check_fits() -> None:
    import build
    rng = random.Random(7)
    blob, image = synthetic_fits(rng)
    raw, facts = build.decode_frame(blob)
    if array("h", raw) != image:
        raise SystemExit("selftest: build.decode_frame mismatch")
    vraw, vfacts = vfy.decode_frame(blob)
    if vraw != raw:
        raise SystemExit("selftest: verify.decode_frame mismatch")
    corrupt = bytearray(blob)
    corrupt[-100] ^= 0x01  # inside zero padding of the data unit -> DATASUM fails
    for fn in (build.decode_frame, vfy.decode_frame):
        try:
            fn(bytes(corrupt))
        except Exception:
            continue
        raise SystemExit(f"selftest: {fn.__module__}.decode_frame accepted a corrupt data unit")
    # A frame on a square-root companded lattice (even values only near 110 DN), even with
    # an honest-looking LUTID 0 header, must be rejected by both lattice checks.
    cblob, cimage = synthetic_fits(random.Random(11), companded=True)
    near = sorted({v for v in cimage if 100 <= v <= 130})
    if near == list(range(near[0], near[-1] + 1)):
        raise SystemExit("selftest: companded synthetic image is not on a coarse lattice")
    for fn in (build.decode_frame, vfy.decode_frame):
        try:
            fn(cblob)
        except Exception as exc:
            if "lattice" not in str(exc):
                raise SystemExit(f"selftest: {fn.__module__} rejected the companded frame for "
                                 f"the wrong reason: {exc}")
            continue
        raise SystemExit(f"selftest: {fn.__module__}.decode_frame accepted a companded frame")
    print(f"selftest fits ok valid={facts['valid_count']} blank={facts['blank_count']} "
          f"companded_rejected=2 companded_levels_100_130={near}")


if __name__ == "__main__":
    check_decoders()
    check_fits()
    print("selftest ok")
