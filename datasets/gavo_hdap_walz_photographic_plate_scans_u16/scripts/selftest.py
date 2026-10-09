#!/usr/bin/env python3
"""Self-test both header parsers and both decode paths on a synthetic FITS plate."""
from __future__ import annotations

import hashlib
import random
import struct
import sys
import tempfile
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import fitsplate  # noqa: E402
import verify  # noqa: E402


def card(key: str, value: str = "", comment: str = "") -> bytes:
    if key in ("END", "COMMENT", "HISTORY"):
        text = f"{key:<8}{value}"
    else:
        text = f"{key:<8}= {value:>20}"
        if comment:
            text += f" / {comment}"
    return text.ljust(80)[:80].encode("ascii")


def synthetic(nx: int, ny: int, values: list[int], extra_hdu: bool = False) -> bytes:
    cards = [
        card("SIMPLE", "T"), card("BITPIX", "16"), card("NAXIS", "2"),
        card("NAXIS1", str(nx)), card("NAXIS2", str(ny)), card("EXTEND", "T"),
        card("BZERO", "32768"), card("BSCALE", "1"),
        card("OBJECT", "'Moon    '", "Special object on plate"),
        card("DATE-OBS", "'1909-04-03'"),
        card("TELESCOP", "'72cm Walz Reflektor'"),
        card("PLATE-ID", "'DTEST   '"),
        card("REMARKS", "'it''s a test / slash'"),
        card("COMMENT", "synthetic = not real"),
    ] + [card("HISTORY", f"filler {i}") for i in range(30)] + [card("END")]
    header = b"".join(cards)
    header += b" " * (-len(header) % 2880)  # END lands in block 2: 5,760 bytes like the real files
    data = struct.pack(f">{nx * ny}h", *(v - 32768 for v in values))
    data += b"\0" * (-len(data) % 2880)
    blob = header + data
    if extra_hdu:
        blob += b" " * 2880
    return blob


def main() -> int:
    nx, ny = 1003, 1001
    rng = random.Random(20261009)
    values = [rng.randrange(65536) for _ in range(nx * ny)]
    values[:6] = [0, 1, 32767, 32768, 32769, 65535]
    blob = synthetic(nx, ny, values)

    cards, hdr = fitsplate.parse_primary_header(blob)
    assert hdr == 5760, hdr
    assert cards["REMARKS"] == "it's a test / slash", cards["REMARKS"]
    facts = fitsplate.check_regime(cards, hdr, len(blob))
    assert (facts["naxis1"], facts["naxis2"]) == (nx, ny)
    vcards, vhdr = verify.header_cards(blob)
    assert vhdr == hdr and vcards["BZERO"] == "32768" and vcards["TELESCOP"] == "72cm Walz Reflektor"

    expected = struct.pack(f"<{nx * ny}H", *values)
    raw = blob[hdr : hdr + nx * ny * 2]
    got = build.be_int16_bzero_to_le_uint16(raw)
    assert got == expected, "build decode mismatch"
    words = array("H")
    words.frombytes(raw)
    words.byteswap()
    alt = bytearray(words.tobytes())
    alt[1::2] = alt[1::2].translate(verify.XOR)
    assert alt == expected, "verify decode mismatch"
    stats = build.value_stats(got)
    assert stats["min"] == 0 and stats["max"] == 65535 and stats["count_0"] >= 1 and stats["count_65535"] >= 1

    # negative cases: extension HDU, BLANK, wrong BZERO, non-lunar object
    for mutate, label in [
        (lambda b: b + b" " * 2880, "extension"),
        (lambda b: b.replace(card("COMMENT", "synthetic = not real"), card("BLANK", "-32768")), "blank"),
        (lambda b: b.replace(card("BZERO", "32768"), card("BZERO", "0")), "bzero"),
        (lambda b: b.replace(card("OBJECT", "'Moon    '", "Special object on plate"), card("OBJECT", "'M45'")), "object"),
    ]:
        bad = mutate(blob)
        try:
            c, h = fitsplate.parse_primary_header(bad)
            fitsplate.check_regime(c, h, len(bad))
        except fitsplate.RegimeError:
            continue
        raise AssertionError(f"regime check accepted the {label} mutation")

    # check_file round trip against a pin
    with tempfile.TemporaryDirectory(prefix="hdap_selftest_") as tmp:
        path = Path(tmp) / "DTEST.fits"
        path.write_bytes(blob)
        pin = {
            "plate_id": "DTEST", "size_bytes": str(len(blob)), "naxis1": str(nx), "naxis2": str(ny),
            "header_bytes": "5760", "fits_date_obs": "1909-04-03",
            "header_sha256": hashlib.sha256(blob[:5760]).hexdigest(),
        }
        out = fitsplate.check_file(path, pin)
        assert out["sha256"] == hashlib.sha256(blob).hexdigest()
        pin["header_sha256"] = "0" * 64
        try:
            fitsplate.check_file(path, pin)
        except fitsplate.RegimeError:
            pass
        else:
            raise AssertionError("check_file accepted a wrong header hash")
    print("selftest ok: parsers, decoders and regime rejections agree on synthetic 1003x1001 plate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
