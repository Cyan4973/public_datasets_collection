#!/usr/bin/env python3
"""Synthetic self-test of both FITS header walkers and both big-endian float32 decoders.

Builds an in-memory PRIMARY + IMAGE prefix shaped like a SPHEREx L2 file (multi-block header,
HIERARCH cards, quoted strings with escaped quotes, COMMENT/HISTORY cards) whose 2040 x 2040
data unit holds edge values (signed zeros, +/-Inf, quiet and payload NaNs, subnormals,
float32 extremes) and checks that build-side and verify-side paths agree bit-for-bit with a
struct reference.
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import spherex_fits as sf  # noqa: E402
import verify as vf  # noqa: E402

NAME = "level2_2026W30_1B_0001_1D1_spx_l2b-v27-2026-222.fits"


def card(key: str, value: str, comment: str = "") -> bytes:
    s = f"{key:<8}= {value:>20}" + (f" / {comment}" if comment else "")
    return s.ljust(80)[:80].encode("ascii")


def header(cards: list[bytes]) -> bytes:
    raw = b"".join(cards) + b"END".ljust(80)
    pad = (-len(raw)) % 2880
    return raw + b" " * pad


def main() -> None:
    primary = header([card("SIMPLE", "T"), card("BITPIX", "8"), card("NAXIS", "0"), card("EXTEND", "T"),
                      card("VERSION", "'7.0.5   '", "SSDC Pipelines software version")])
    img_cards = [card("XTENSION", "'IMAGE   '"), card("BITPIX", "-32"), card("NAXIS", "2"),
                 card("NAXIS1", "2040"), card("NAXIS2", "2040"), card("PCOUNT", "0"), card("GCOUNT", "1"),
                 card("EXTNAME", "'IMAGE   '"), card("BUNIT", "'MJy / sr'", "Unit of pixel value"),
                 card("DETECTOR", "1", "1-3: SWIR, 4-6: MWIR"), card("OBSID", "'2026W30_1B_0001_1'"),
                 card("EXPIDN", "202630102000111"), card("DETCOORD", "'sky     '"),
                 card("L1DQAFLG", "'Pass    '"), card("L2DQAFLG", "'Pass    '"), card("JACTIVE", "2040"),
                 card("KACTIVE", "2040"), card("XPOSURE", "113.5826"), card("TESTQ", "'it''s / ok'"),
                 b"HIERARCH NON_SURVEY = 'False   ' / Observation is not part of a science survey".ljust(80),
                 b"HIERARCH L2 N_HOT = 0 / number of pixels flagged hot".ljust(80),
                 b"KEN_A   = 20000 / [adu2] free-format value".ljust(80)]
    img_cards += [b"HISTORY filler card number %d with = sign inside" % i + b" " * 0 for i in range(120)]
    img_cards = [c.ljust(80)[:80] for c in img_cards]
    img_hdr = header(img_cards)
    assert len(img_hdr) > 2 * 2880, "synthetic header should span several blocks"

    rng = random.Random(20261008)
    edge = [0x00000000, 0x80000000, 0x7F800000, 0xFF800000, 0x7FC00000, 0x7FC12345, 0xFFC00001, 0x7F800001,
            0x00000001, 0x807FFFFF, 0x7F7FFFFF, 0xFF7FFFFF, 0x3EA0E3B5, 0xC2622F00]
    bits = edge + [rng.getrandbits(32) for _ in range(sf.IMAGE_VALUES - len(edge))]
    be = struct.pack(f">{len(bits)}I", *bits)
    ref_le = struct.pack(f"<{len(bits)}I", *bits)
    buf = primary + img_hdr + be

    info = sf.walk_prefix(buf)
    assert info["data_offset"] == len(primary) + len(img_hdr), info["data_offset"]
    assert info["prefix_bytes"] == len(buf)
    assert sf.check_regime(info, NAME) == [], sf.check_regime(info, NAME)
    assert info["image"]["TESTQ"] == "it's / ok", info["image"]["TESTQ"]
    assert info["image"]["HIERARCH NON_SURVEY"] == "False"
    assert info["image"]["KEN_A"] == 20000
    bad = dict(info, image=dict(info["image"], DETECTOR=2))
    assert sf.check_regime(bad, NAME), "detector 2 must be rejected"
    assert sf.check_regime(info, NAME.replace("1D1", "1D2")), "D2 file name must be rejected"

    a_bytes = sf.decode_be_f32(buf[info["data_offset"]:]).tobytes()
    b_bytes = vf.swap_be32(buf[info["data_offset"]:])
    assert a_bytes == ref_le, "build decoder not bit-exact"
    assert b_bytes == ref_le, "verify decoder not bit-exact"

    prim2, p_end = vf.hdu_header(buf, 0)
    img2, d_off = vf.hdu_header(buf, p_end)
    assert p_end == len(primary) and d_off == info["data_offset"], (p_end, d_off)
    assert img2["BUNIT"] == "MJy / sr" and img2["BITPIX"] == "-32" and img2["OBSID"] == "2026W30_1B_0001_1"

    st1 = sf.image_stats(sf.decode_be_f32(be))
    st2 = vf.stats(ref_le)
    for k in ("nan_count", "inf_count", "finite_min", "finite_max", "distinct_bit_patterns"):
        assert st1[k] == st2[k], (k, st1[k], st2[k])
    assert st1["inf_count"] >= 2 and st1["nan_count"] >= 4

    try:
        sf.walk_prefix(buf[:len(primary) + 2880])
    except sf.FitsError:
        pass
    else:
        raise AssertionError("truncated header must fail")
    print("selftest_ok decoders and header walkers agree on synthetic SPHEREx-shaped FITS")


if __name__ == "__main__":
    main()
