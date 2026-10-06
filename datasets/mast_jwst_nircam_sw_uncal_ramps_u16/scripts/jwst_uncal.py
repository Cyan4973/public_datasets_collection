#!/usr/bin/env python3
"""Shared helpers for the JWST NIRCam SW uncal ramp recipe (download check + build).

Pure standard library. verify.py deliberately does NOT import this module.

- FITS header/HDU walking over an in-memory file image
- homogeneity assertions on the primary and SCI headers
- SCI decode: big-endian int16 with BZERO = 32768 -> little-endian uint16
- CRC64-NVME (the S3 full-object checksum algorithm)
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

DATASET_ID = "mast_jwst_nircam_sw_uncal_ramps_u16"
SERIES_ID = "nircam_sw_full_medium8_uncal_ramp_dn_u16"
BLOCK = 2880
CARD = 80

SW_DETECTORS = {"NRCA1", "NRCA2", "NRCA3", "NRCA4", "NRCB1", "NRCB2", "NRCB3", "NRCB4"}
FILTERS = {"F090W", "F200W"}
EXPECTED_HDUS = ["PRIMARY", "SCI", "ZEROFRAME", "GROUP", "INT_TIMES", "ASDF"]

# Fixed geometry of the pinned regime (FULL / MEDIUM8 / NGROUPS=8 / NINTS=1).
GEOMETRY = {"NAXIS1": 2048, "NAXIS2": 2048, "NAXIS3": 8, "NAXIS4": 1}

# Primary-header requirements (string compare on the parsed card value).
PRIMARY_REQUIRED = {
    "SIMPLE": "T",
    "NAXIS": "0",
    "TELESCOP": "JWST",
    "INSTRUME": "NIRCAM",
    "DATAMODL": "Level1bModel",
    "PROGRAM": "02736",
    "OBSERVTN": "001",
    "VISIT": "001",
    "EXP_TYPE": "NRC_IMAGE",
    "CHANNEL": "SHORT",
    "PUPIL": "CLEAR",
    "SUBARRAY": "FULL",
    "SUBSTRT1": "1",
    "SUBSTRT2": "1",
    "SUBSIZE1": "2048",
    "SUBSIZE2": "2048",
    "READPATT": "MEDIUM8",
    "NGROUPS": "8",
    "NINTS": "1",
    "NFRAMES": "8",
    "FRMDIVSR": "8",
    "GROUPGAP": "2",
    "NSAMPLES": "1",
    "COMPRESS": "F",
    "DATAPROB": "F",
    "ENG_QUAL": "OK",
    "ZEROFRAM": "T",
}
SCI_REQUIRED = {
    "XTENSION": "IMAGE",
    "EXTNAME": "SCI",
    "BITPIX": "16",
    "NAXIS": "4",
    "PCOUNT": "0",
    "GCOUNT": "1",
    "BZERO": "32768",
    "BSCALE": "1",
    "BUNIT": "DN",
}

_CARD_RE = re.compile(r"^([A-Z0-9_-]{1,8}) *$")
# XOR 0x80 on the high (first, big-endian) byte of every 16-bit word adds 32768 mod 65536.
_XOR80 = bytes(b ^ 0x80 for b in range(256))


class UncalError(Exception):
    pass


def _card_value(text: str) -> str:
    raw = text[10:]
    stripped = raw.lstrip()
    if stripped.startswith("'"):
        out = []
        i = 1
        while i < len(stripped):
            ch = stripped[i]
            if ch == "'":
                if i + 1 < len(stripped) and stripped[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(ch)
            i += 1
        return "".join(out).rstrip()
    return raw.split("/", 1)[0].strip()


def parse_header(buf, offset: int) -> tuple[dict[str, str], int]:
    """Parse one FITS header starting at `offset`; return (cards, header length in bytes)."""
    cards: dict[str, str] = {}
    pos = offset
    limit = len(buf)
    while pos + CARD <= limit:
        card = bytes(buf[pos:pos + CARD])
        pos += CARD
        if any(b < 32 or b > 126 for b in card):
            raise UncalError(f"non-printable byte in header card at offset {pos - CARD}")
        text = card.decode("ascii")
        if text.rstrip() == "END":
            length = pos - offset
            length = (length + BLOCK - 1) // BLOCK * BLOCK
            if offset + length > limit:
                raise UncalError("header padding runs past end of file")
            pad = bytes(buf[pos:offset + length])
            if pad.strip(b" "):
                raise UncalError("non-blank bytes after END card")
            return cards, length
        if text[8:10] != "= ":
            continue
        key = text[:8].rstrip()
        if not _CARD_RE.match(text[:8]):
            continue
        cards.setdefault(key, _card_value(text))
    raise UncalError(f"no END card for header at offset {offset}")


def data_length(cards: dict[str, str]) -> int:
    bitpix = abs(int(cards["BITPIX"]))
    naxis = int(cards["NAXIS"])
    if naxis == 0:
        return 0
    count = 1
    for axis in range(1, naxis + 1):
        count *= int(cards[f"NAXIS{axis}"])
    return bitpix // 8 * int(cards.get("GCOUNT", "1")) * (int(cards.get("PCOUNT", "0")) + count)


def walk_hdus(buf) -> list[dict]:
    """Walk every HDU; require the chain to end exactly at the end of the file."""
    hdus = []
    offset = 0
    total = len(buf)
    while offset < total:
        cards, hlen = parse_header(buf, offset)
        dlen = data_length(cards)
        padded = (dlen + BLOCK - 1) // BLOCK * BLOCK
        name = "PRIMARY" if not hdus else cards.get("EXTNAME", "?")
        hdus.append({"name": name, "offset": offset, "header_len": hlen, "data_offset": offset + hlen,
                     "data_len": dlen, "padded_len": padded, "cards": cards})
        offset += hlen + padded
    if offset != total:
        raise UncalError(f"HDU chain ends at {offset}, file size {total}")
    return hdus


PINNED_PRIMARY_KEYS = ("SDP_VER", "ACT_ID", "EXPOSURE", "DATE-OBS", "TIME-OBS")


def check_headers(primary: dict, sci: dict, source: dict, geometry: dict | None = None,
                  primary_required: dict | None = None) -> None:
    """Homogeneity assertions on the primary and SCI header cards."""
    geometry = GEOMETRY if geometry is None else geometry
    primary_required = PRIMARY_REQUIRED if primary_required is None else primary_required
    for key, want in primary_required.items():
        if primary.get(key) != want:
            raise UncalError(f"primary {key}={primary.get(key)!r}, required {want!r}")
    if primary.get("FILENAME") != source["filename"]:
        raise UncalError(f"FILENAME {primary.get('FILENAME')!r} != pinned {source['filename']!r}")
    detector = primary.get("DETECTOR")
    if detector not in SW_DETECTORS or detector != source.get("detector", detector):
        raise UncalError(f"DETECTOR {detector!r} is not the pinned SW detector {source.get('detector')!r}")
    filt = primary.get("FILTER")
    if filt not in FILTERS or filt != source.get("filter", filt):
        raise UncalError(f"FILTER {filt!r} != pinned {source.get('filter')!r}")
    for key in PINNED_PRIMARY_KEYS:
        pinned = source.get(key.lower().replace("-", "_"))
        if pinned is not None and primary.get(key) != pinned:
            raise UncalError(f"primary {key}={primary.get(key)!r} != pinned {pinned!r}")
    if sci.get("XTENSION") != "IMAGE" or sci.get("EXTNAME") != "SCI":
        raise UncalError("second HDU is not the SCI image extension")
    for key, want in SCI_REQUIRED.items():
        if sci.get(key) != want:
            raise UncalError(f"SCI {key}={sci.get(key)!r}, required {want!r}")
    for key, want in geometry.items():
        if sci.get(key) != str(want):
            raise UncalError(f"SCI {key}={sci.get(key)!r}, required {want}")
    if "BLANK" in sci:
        raise UncalError("SCI declares BLANK; no missing-value sentinel is expected")


def validate(buf, source: dict, geometry: dict | None = None,
             primary_required: dict | None = None, expected_hdus: list | None = None) -> dict:
    """Assert the pinned regime; return the SCI HDU record."""
    geometry = GEOMETRY if geometry is None else geometry
    primary_required = PRIMARY_REQUIRED if primary_required is None else primary_required
    expected_hdus = EXPECTED_HDUS if expected_hdus is None else expected_hdus
    hdus = walk_hdus(buf)
    names = [h["name"] for h in hdus]
    if names != expected_hdus:
        raise UncalError(f"HDU sequence {names} != {expected_hdus}")
    sci = hdus[1]
    check_headers(hdus[0]["cards"], sci["cards"], source, geometry, primary_required)
    pad = bytes(buf[sci["data_offset"] + sci["data_len"]:sci["data_offset"] + sci["padded_len"]])
    if pad.strip(b"\x00"):
        raise UncalError("non-zero padding after SCI data")
    return sci


def decode_sci_le(buf, sci: dict) -> bytes:
    """Big-endian int16 + BZERO 32768 -> little-endian uint16 (whole SCI cube, FITS order)."""
    start = sci["data_offset"]
    raw = bytes(buf[start:start + sci["data_len"]])
    if len(raw) % 2:
        raise UncalError("odd SCI data length")
    out = bytearray(len(raw))
    out[0::2] = raw[1::2]                      # low byte first
    out[1::2] = raw[0::2].translate(_XOR80)    # high byte with sign bit flipped (= +32768)
    return bytes(out)


_POLY_REFLECTED = 0x9A6C9329AC4BC9B5  # CRC-64/NVME, reflected form of 0xAD93D23594C93659
_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ _POLY_REFLECTED if _c & 1 else _c >> 1
    _TABLE.append(_c)


def crc64nvme(data, crc: int = 0) -> int:
    table = _TABLE
    crc ^= 0xFFFFFFFFFFFFFFFF
    for byte in data:
        crc = table[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFFFFFFFFFF


def crc64nvme_b64(data) -> str:
    import base64
    return base64.b64encode(crc64nvme(data).to_bytes(8, "big")).decode("ascii")


def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))
