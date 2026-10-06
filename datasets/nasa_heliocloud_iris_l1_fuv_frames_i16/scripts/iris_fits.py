"""Shared FITS / tile-compressed RICE_1 helpers for the IRIS level-1 FUV recipe.

Pure standard library. Used by discover.py, check_payload.py and build.py.
verify.py deliberately does NOT import this module: it carries its own header
walker and a second, byte-wise Rice decoder so that the emitted samples are
re-derived independently.

Rice decoding follows CFITSIO fits_rdecomp_short (ricecomp.c) exactly:
  * each compressed tile (here: one image row of ZTILE1 = 4144 pixels) starts
    with the first pixel value as a 2-byte big-endian integer (the seed);
  * then, per block of BLOCKSIZE (32) pixels, a 4-bit code fs+1 (fsbits = 4):
      fs < 0      -> every pixel of the block equals the previous pixel;
      fs == 14    -> each difference is coded verbatim in 16 bits (fsmax = 14,
                     bbits = 16), still zigzag-mapped;
      otherwise   -> each difference is a unary quotient (zeros terminated by
                     a one bit) followed by fs low bits;
  * mapped difference m is un-zigzagged (even -> m >> 1, odd -> ~(m >> 1))
    and accumulated onto the previous pixel modulo 2**16;
  * the encoder flushes to a byte boundary, so the bit stream of a valid tile
    is consumed to within its final byte.
"""

from __future__ import annotations

import sys
from array import array

BLOCK = 2880
CARD = 80

FSBITS = 4
FSMAX = 14
BBITS = 16


class FitsError(Exception):
    pass


# ---------------------------------------------------------------- headers
def parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("'"):
        # FITS string: '' is an escaped quote; value ends at the closing quote.
        out = []
        i = 1
        while i < len(raw):
            ch = raw[i]
            if ch == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(ch)
            i += 1
        return "".join(out).rstrip()
    value = raw.split("/", 1)[0].strip()
    if value == "T":
        return True
    if value == "F":
        return False
    if value == "":
        return None
    try:
        if any(c in value for c in ".EeDd") and not value.lstrip("+-").isdigit():
            return float(value.replace("D", "E").replace("d", "e"))
        return int(value)
    except ValueError:
        return value


def read_header(data: bytes, offset: int):
    """Parse one FITS header starting at offset; return (cards, data_offset)."""
    cards = {}
    order = []
    pos = offset
    while True:
        if pos + BLOCK > len(data):
            raise FitsError(f"truncated header at byte {pos}")
        block = data[pos:pos + BLOCK]
        pos += BLOCK
        for i in range(0, BLOCK, CARD):
            card = block[i:i + CARD]
            try:
                text = card.decode("ascii")
            except UnicodeDecodeError as exc:
                raise FitsError("non-ASCII header card") from exc
            key = text[:8].rstrip()
            if key == "END":
                return cards, order, pos
            if text[8:10] == "= " and key not in ("COMMENT", "HISTORY", ""):
                if key in cards:
                    raise FitsError(f"duplicate header keyword {key}")
                cards[key] = parse_value(text[10:])
                order.append(key)


def hdu_layout(data: bytes):
    """Return (primary_cards, table_cards, table_header_offset, table_data_offset,
    table_data_bytes)."""
    primary, _, pos = read_header(data, 0)
    if primary.get("SIMPLE") is not True or primary.get("NAXIS") != 0:
        raise FitsError("primary HDU is not an empty SIMPLE header")
    if primary.get("EXTEND") is not True:
        raise FitsError("primary HDU does not declare EXTEND")
    table, _, data_off = read_header(data, pos)
    if table.get("XTENSION") != "BINTABLE":
        raise FitsError("first extension is not a BINTABLE")
    nbytes = int(table["NAXIS1"]) * int(table["NAXIS2"]) + int(table["PCOUNT"])
    return primary, table, pos, data_off, nbytes


def padded(n: int) -> int:
    return (n + BLOCK - 1) // BLOCK * BLOCK


# ---------------------------------------------------------------- checksums
def ones_complement_sum(buf: bytes, start: int = 0) -> int:
    """FITS 32-bit ones-complement sum of big-endian words (len multiple of 4)."""
    if len(buf) % 4:
        raise FitsError("checksum buffer is not word aligned")
    words = array("I")
    if words.itemsize != 4:
        raise FitsError("platform array('I') is not 32-bit")
    words.frombytes(buf)
    if sys.byteorder == "little":
        words.byteswap()
    total = start + sum(words)
    while total >> 32:
        total = (total & 0xFFFFFFFF) + (total >> 32)
    return total


# ---------------------------------------------------------------- regime
def expected_datavals(table: dict) -> int:
    n = 0
    for r in range(1, int(table["CRS_NREG"]) + 1):
        n += (int(table[f"TER{r}"]) - int(table[f"TSR{r}"]) + 1) * (
            int(table[f"TEC{r}"]) - int(table[f"TSC{r}"]) + 1)
    return n


REGIME_EXACT = {
    "XTENSION": "BINTABLE", "BITPIX": 8, "NAXIS": 2, "NAXIS1": 8, "NAXIS2": 1096,
    "GCOUNT": 1, "TFIELDS": 1, "TTYPE1": "COMPRESSED_DATA",
    "ZIMAGE": True, "ZBITPIX": 16, "ZNAXIS": 2, "ZNAXIS1": 4144, "ZNAXIS2": 1096,
    "ZTILE1": 4144, "ZTILE2": 1, "ZCMPTYPE": "RICE_1",
    "ZNAME1": "BLOCKSIZE", "ZVAL1": 32, "ZNAME2": "BYTEPIX", "ZVAL2": 2,
    "TELESCOP": "IRIS", "INSTRUME": "FUV", "IMG_PATH": "FUV", "IMG_TYPE": "LIGHT",
    "CAMERA": 1, "SUMSPTRL": 1, "SUMSPAT": 1, "CRS_NREG": 2, "CRS_TYPE": "FUV",
    "TSC1": 1, "TEC1": 2048, "TSC2": 2097, "TEC2": 4112,
    "BLANK": -32768, "MISSVALS": 0,
    # Onboard compression look-up table: 0 = none (unit-DN lattice). LUTID 4 frames are
    # square-root companded on board (steps of 2 DN near 110 DN, ~40 DN above 4000 DN),
    # a different value lattice, and are excluded.
    "LUTID": 0,
}
# Keywords that must NOT appear: they would change the pixel semantics.
REGIME_ABSENT = ("ZSCALE", "ZZERO", "ZBLANK", "ZQUANTIZ", "ZDITHER0", "BSCALE",
                 "BZERO", "THEAP", "TFORM2", "ZNAME3")


def regime_problems(table: dict) -> list[str]:
    """Return a list of header-regime violations (empty list = accepted)."""
    bad = []
    for key, want in REGIME_EXACT.items():
        got = table.get(key)
        if isinstance(want, str):
            ok = isinstance(got, str) and got.strip() == want
        elif isinstance(want, bool):
            ok = got is want
        else:
            ok = got is not None and not isinstance(got, bool) and got == want
        if not ok:
            bad.append(f"{key}={got!r} (want {want!r})")
    for key in REGIME_ABSENT:
        if key in table:
            bad.append(f"unexpected keyword {key}")
    tform = str(table.get("TFORM1", ""))
    if not (tform.startswith("1PB(") and tform.endswith(")")):
        bad.append(f"TFORM1={tform!r} (want 1PB(n))")
    lvl = table.get("LVL_NUM")
    if not isinstance(lvl, (int, float)) or float(lvl) != 1.0:
        bad.append(f"LVL_NUM={lvl!r}")
    try:
        for r in (1, 2):
            tsr, ter = int(table[f"TSR{r}"]), int(table[f"TER{r}"])
            if not (1 <= tsr <= ter <= 1096):
                bad.append(f"readout rows region {r} = {tsr}..{ter}")
        for r in range(3, 9):
            if any(int(table.get(f"{p}{r}", 0)) != 0 for p in ("TSR", "TER", "TSC", "TEC")):
                bad.append(f"unexpected readout region {r}")
        if table.get("DATAVALS") != expected_datavals(table):
            bad.append(f"DATAVALS={table.get('DATAVALS')} != readout area {expected_datavals(table)}")
        if table.get("TOTVALS") != table.get("DATAVALS"):
            bad.append("TOTVALS != DATAVALS")
    except (KeyError, TypeError, ValueError) as exc:
        bad.append(f"readout geometry unreadable: {exc}")
    for key in ("DATAMIN", "DATAMAX", "DATAMEDN", "EXPTIME", "ISQOLTID", "T_OBS", "FSN"):
        if key not in table:
            bad.append(f"missing keyword {key}")
    return bad


# ---------------------------------------------------------------- Rice
def rice_decode_tile(buf: bytes, nx: int, nblock: int = 32) -> array:
    """Decode one RICE_1 tile of BYTEPIX=2 into array('H') of nx raw uint16 words."""
    if len(buf) < 2:
        raise FitsError("Rice tile shorter than its 2-byte seed")
    lastpix = (buf[0] << 8) | buf[1]
    nbytes = len(buf) - 2
    nbits_total = nbytes * 8
    if nbytes:
        bits = bin(int.from_bytes(buf[2:], "big"))[2:].zfill(nbits_total)
    else:
        bits = ""
    out = array("H")
    append = out.append
    find = bits.find
    p = 0
    i = 0
    while i < nx:
        if p + FSBITS > nbits_total:
            raise FitsError("Rice stream ended inside a block header")
        fs = int(bits[p:p + FSBITS], 2) - 1
        p += FSBITS
        imax = i + nblock
        if imax > nx:
            imax = nx
        n = imax - i
        if fs < 0:
            out.extend([lastpix] * n)
        elif fs == FSMAX:
            end = p + BBITS * n
            if end > nbits_total:
                raise FitsError("Rice stream ended inside a verbatim block")
            for q in range(p, end, BBITS):
                m = int(bits[q:q + BBITS], 2)
                if m & 1:
                    lastpix = (lastpix - (m >> 1) - 1) & 0xFFFF
                else:
                    lastpix = (lastpix + (m >> 1)) & 0xFFFF
                append(lastpix)
            p = end
        elif fs == 0:
            for _ in range(n):
                one = find("1", p)
                if one < 0:
                    raise FitsError("Rice stream ended inside a unary code")
                m = one - p
                p = one + 1
                if m & 1:
                    lastpix = (lastpix - (m >> 1) - 1) & 0xFFFF
                else:
                    lastpix = (lastpix + (m >> 1)) & 0xFFFF
                append(lastpix)
        else:
            for _ in range(n):
                one = find("1", p)
                if one < 0:
                    raise FitsError("Rice stream ended inside a unary code")
                zeros = one - p
                p = one + 1 + fs
                if p > nbits_total:
                    raise FitsError("Rice stream ended inside fs bits")
                m = (zeros << fs) | int(bits[one + 1:p], 2)
                if m & 1:
                    lastpix = (lastpix - (m >> 1) - 1) & 0xFFFF
                else:
                    lastpix = (lastpix + (m >> 1)) & 0xFFFF
                append(lastpix)
        i = imax
    if (p + 7) // 8 != nbytes:
        raise FitsError(f"Rice tile length mismatch: used {p} bits of {nbytes} bytes")
    return out
