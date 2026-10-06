#!/usr/bin/env python3
"""Self-test of the FITS walkers, SCI decoders and CRC64-NVME implementations on synthetic input.

Builds a small uncal-shaped FITS image in memory (multi-block primary header, SCI int16 cube with
BZERO = 32768 and data padding, ZEROFRAME, three BINTABLE stubs) and checks that the build-side
module (jwst_uncal.py) and the independent verify-side functions (verify.py) agree with the
known values and with each other, and that malformed inputs are rejected. Run by build.sh.
"""
from __future__ import annotations

import os
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jwst_uncal as ju  # noqa: E402
import verify as vf  # noqa: E402


def card(key: str, value, comment: str = "") -> bytes:
    if isinstance(value, bool):
        text = f"{'T' if value else 'F':>20}"
    elif isinstance(value, int):
        text = f"{value:>20}"
    else:
        text = "'" + f"{str(value).replace(chr(39), chr(39) * 2):<8}" + "'"
    line = f"{key:<8}= {text}"
    if comment:
        line += f" / {comment}"
    return f"{line:<80}"[:80].encode("ascii")


def block(cards: list[bytes]) -> bytes:
    raw = b"".join(cards) + f"{'END':<80}".encode("ascii")
    return raw + b" " * (-len(raw) % 2880)


def pad(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 2880)


def synthetic(nx: int, ny: int, ng: int, filename: str, values: list[int], bzero: int = 32768) -> bytes:
    primary = [card("SIMPLE", True), card("BITPIX", 8), card("NAXIS", 0), card("EXTEND", True)]
    for key, want in ju.PRIMARY_REQUIRED.items():
        if key in ("SIMPLE", "NAXIS"):
            continue
        if want in ("T", "F"):
            primary.append(card(key, want == "T"))
        elif want.isdigit() and key not in ("PROGRAM", "OBSERVTN", "VISIT"):
            primary.append(card(key, int(want)))
        else:
            primary.append(card(key, want))
    primary += [card("FILENAME", filename), card("DETECTOR", "NRCB3"), card("FILTER", "F200W"),
                card("SDP_VER", "2026_1b"), card("ACT_ID", "05"), card("EXPOSURE", "7"),
                card("DATE-OBS", "2022-06-07"), card("TIME-OBS", "06:51:12.968"),
                card("TITLE", "It's a test", "quote escaping")]
    primary += [f"COMMENT filler card {i:<64}".encode("ascii")[:80] for i in range(20)]  # 58 cards + END -> 2 blocks
    sci_hdr = [card("XTENSION", "IMAGE"), card("BITPIX", 16), card("NAXIS", 4), card("NAXIS1", nx),
               card("NAXIS2", ny), card("NAXIS3", ng), card("NAXIS4", 1), card("PCOUNT", 0), card("GCOUNT", 1),
               card("BZERO", bzero), card("BSCALE", 1), card("EXTNAME", "SCI"), card("BUNIT", "DN")]
    sci_data = struct.pack(f">{len(values)}h", *[v - 32768 for v in values])
    zero_hdr = [card("XTENSION", "IMAGE"), card("BITPIX", 16), card("NAXIS", 3), card("NAXIS1", nx),
                card("NAXIS2", ny), card("NAXIS3", 1), card("PCOUNT", 0), card("GCOUNT", 1),
                card("BZERO", 32768), card("EXTNAME", "ZEROFRAME")]
    zero_data = sci_data[: nx * ny * 2]
    out = block(primary) + block(sci_hdr) + pad(sci_data) + block(zero_hdr) + pad(zero_data)
    for extname, width, rows in (("GROUP", 9, 3), ("INT_TIMES", 52, 1), ("ASDF", 777, 1)):
        hdr = [card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2), card("NAXIS1", width),
               card("NAXIS2", rows), card("PCOUNT", 0), card("GCOUNT", 1), card("TFIELDS", 1),
               card("EXTNAME", extname)]
        out += block(hdr) + pad(os.urandom(width * rows))
    return out


def expect_reject(label: str, func) -> None:
    try:
        func()
    except (ju.UncalError, ValueError, KeyError):
        return
    raise SystemExit(f"selftest FAIL: {label} was not rejected")


def main() -> int:
    rng = random.Random(20261005)
    nx, ny, ng = 7, 5, 3
    edge = [0, 1, 2, 255, 256, 32767, 32768, 32769, 65534, 65535]
    values = edge + [rng.randrange(65536) for _ in range(nx * ny * ng - len(edge))]
    name = "jw02736001001_02105_00007_nrcb3_uncal.fits"
    buf = synthetic(nx, ny, ng, name, values)
    geometry = {"NAXIS1": nx, "NAXIS2": ny, "NAXIS3": ng, "NAXIS4": 1}
    source = {"filename": name, "detector": "NRCB3", "filter": "F200W", "sdp_ver": "2026_1b",
              "act_id": "05", "exposure": "7", "date_obs": "2022-06-07", "time_obs": "06:51:12.968"}

    expected_le = struct.pack(f"<{len(values)}H", *values)
    sci = ju.validate(buf, source, geometry=geometry)
    got_build = ju.decode_sci_le(buf, sci)
    if got_build != expected_le:
        raise SystemExit("selftest FAIL: jwst_uncal.decode_sci_le mismatch")
    chain = vf.hdu_chain(buf, "synthetic")
    if [c[0] for c in chain] != vf.HDU_NAMES:
        raise SystemExit(f"selftest FAIL: verify HDU chain {[c[0] for c in chain]}")
    hdus = ju.walk_hdus(buf)
    if [(h["data_offset"], h["data_len"]) for h in hdus] != [(c[2], c[3]) for c in chain]:
        raise SystemExit("selftest FAIL: build and verify HDU walkers disagree")
    if chain[0][1].get("TITLE") != "It's a test" or hdus[0]["cards"].get("TITLE") != "It's a test":
        raise SystemExit("selftest FAIL: quoted-string card parsing")
    if hdus[0]["header_len"] != 5760:
        raise SystemExit(f"selftest FAIL: multi-block primary header length {hdus[0]['header_len']}")
    start, nbytes = chain[1][2], chain[1][3]
    got_verify = vf.decode_cube(buf[start:start + nbytes])
    if got_verify != expected_le:
        raise SystemExit("selftest FAIL: verify.decode_cube mismatch")

    # CRC64-NVME: published check value plus agreement on random data.
    if ju.crc64nvme(b"123456789") != 0xAE8B14860A799888:
        raise SystemExit("selftest FAIL: jwst_uncal CRC64-NVME check value")
    if vf.crc64_nvme(b"123456789") != "rosUhgp5mIg=":
        raise SystemExit("selftest FAIL: verify CRC64-NVME check value")
    blob = os.urandom(100_003)
    if ju.crc64nvme_b64(blob) != vf.crc64_nvme(blob):
        raise SystemExit("selftest FAIL: CRC64-NVME implementations disagree")

    # Rejections.
    expect_reject("BZERO != 32768", lambda: ju.validate(synthetic(nx, ny, ng, name, values, bzero=0), source, geometry=geometry))
    expect_reject("truncated file", lambda: ju.validate(buf[:-2880], source, geometry=geometry))
    expect_reject("wrong FILENAME pin", lambda: ju.validate(buf, {**source, "filename": "x_uncal.fits"}, geometry=geometry))
    expect_reject("wrong DETECTOR pin", lambda: ju.validate(buf, {**source, "detector": "NRCA1"}, geometry=geometry))
    expect_reject("wrong geometry", lambda: ju.validate(buf, source, geometry={**geometry, "NAXIS3": ng + 1}))
    expect_reject("full-frame default geometry", lambda: ju.validate(buf, source))
    bad_pad = bytearray(buf)
    bad_pad[hdus[1]["data_offset"] + hdus[1]["data_len"]] = 1
    expect_reject("non-zero SCI padding", lambda: ju.validate(bytes(bad_pad), source, geometry=geometry))
    print(f"selftest ok: {len(values)} synthetic values (edges {edge[0]}..{edge[-1]}), "
          f"header_len={hdus[0]['header_len']}, both decoders and both CRC64-NVME implementations agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
