#!/usr/bin/env python3
"""Decode IUE NEWSIPS raw-image FITS files (swpNNNNN.rilo.gz) with the stdlib.

A RILO file is a gzip member holding a single-HDU FITS file: a 28,800-byte
ASCII primary header (10 blocks of 36 cards) declaring BITPIX = 8, NAXIS = 2,
NAXIS1 = NAXIS2 = 768, then 768 x 768 unsigned-byte detector data numbers in
FITS order (NAXIS1 varies fastest), then 576 zero bytes of FITS padding to the
2,880-byte block size: 619,200 bytes in total.

Used by download.sh (payload validation) and build.sh (sample emission).
verify.sh re-derives everything with its own independent code path.
"""
from __future__ import annotations

import csv
import gzip
import re
import struct
import zlib
from pathlib import Path

DATASET_ID = "mast_iue_swp_raw_image_u8"
SERIES_ID = "iue_swp_lowdisp_raw_dn_u8"
FITS_BLOCK = 2880
LINES = 768
SAMPLES = 768
PIXELS = LINES * SAMPLES
HEADER_BYTES = 28800
FILE_BYTES = 619200
EXPECTED_SOURCES = 256
HEADER_REQUIREMENTS = {
    "SIMPLE": "T",
    "BITPIX": "8",
    "NAXIS": "2",
    "NAXIS1": "768",
    "NAXIS2": "768",
    "BUNIT": "DN",
    "TELESCOP": "IUE",
    "CAMERA": "SWP",
    "DISPERSN": "LOW",
    "DISPTYPE": "LOW",
    "APERTURE": "LARGE",
    "READMODE": "FULL",
    "READGAIN": "LOW",
    "EXPOGAIN": "MAXIMUM",
    "UVC-VOLT": "-5.0",
    "STATION": "GSFC",
    "ABNNOSTD": "NO",
    "ABNREAD": "NO",
    "ABNUVC": "NO",
    "ABNHISTR": "NO",
    "ABNOTHER": "NO",
    "ABNMINFR": "NO",
    "LEXPTRMD": "NO-TRAIL",
    "LEXPMULT": "NO",
    "LEXPSEGM": "NO",
}
CALIBRATION_CLASSES = {98, 99}
SOURCE_FIELDS = [
    "image_no", "filename", "url", "size_bytes", "gzip_crc32", "gzip_isize", "sha256", "etag",
    "last_modified", "obs_start_time", "obs_date", "exptime_s", "catalogue_exptime_s", "iue_class",
    "catalogue_category", "readgain", "expogain", "uvc_volt", "thdaread", "target",
]


class RiloError(ValueError):
    pass


def read_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != SOURCE_FIELDS:
            raise RiloError(f"unexpected sources.tsv columns: {reader.fieldnames}")
        rows = list(reader)
    numbers = [int(row["image_no"]) for row in rows]
    if numbers != sorted(set(numbers)):
        raise RiloError("sources.tsv image numbers must be unique and ascending")
    for row in rows:
        number = int(row["image_no"])
        name = f"swp{number:05d}.rilo.gz"
        url = f"https://archive.stsci.edu/missions/iue/data/swp/{number // 1000 * 1000:05d}/{name}"
        if row["filename"] != name or row["url"] != url:
            raise RiloError(f"inconsistent filename/url for image {number}")
        if int(row["gzip_isize"]) != FILE_BYTES:
            raise RiloError(f"unexpected pinned ISIZE for image {number}")
        if not re.fullmatch(r"[0-9a-f]{8}", row["gzip_crc32"]):
            raise RiloError(f"bad pinned CRC32 for image {number}")
        if row["sha256"] and not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise RiloError(f"bad pinned SHA-256 for image {number}")
    return rows


def gunzip_checked(path: Path, expected_crc32: str, expected_isize: int) -> bytes:
    compressed = path.read_bytes()
    if compressed[:3] != b"\x1f\x8b\x08":
        raise RiloError(f"{path.name}: not a gzip deflate member")
    crc32, isize = struct.unpack("<II", compressed[-8:])
    if f"{crc32:08x}" != expected_crc32 or isize != expected_isize:
        raise RiloError(f"{path.name}: gzip trailer {crc32:08x}/{isize} != pinned {expected_crc32}/{expected_isize}")
    try:
        raw = gzip.decompress(compressed)  # verifies CRC32 and ISIZE of every member
    except (OSError, EOFError, zlib.error) as exc:
        raise RiloError(f"{path.name}: gzip decode failed: {exc}") from exc
    if len(raw) != expected_isize or zlib.crc32(raw) != crc32:
        raise RiloError(f"{path.name}: decompressed length/CRC mismatch")
    return raw


def parse_header(raw: bytes) -> tuple[dict[str, str], int]:
    cards: dict[str, str] = {}
    offset = 0
    while offset + FITS_BLOCK <= len(raw):
        block = raw[offset:offset + FITS_BLOCK]
        offset += FITS_BLOCK
        try:
            text = block.decode("ascii")
        except UnicodeDecodeError as exc:
            raise RiloError(f"non-ASCII FITS header block at {offset - FITS_BLOCK}") from exc
        for start in range(0, FITS_BLOCK, 80):
            card = text[start:start + 80]
            key = card[:8].rstrip()
            if key == "END":
                return cards, offset
            if card[8:10] != "= ":
                continue
            if key in cards:
                raise RiloError(f"duplicate FITS keyword {key}")
            value = card[10:]
            if value.lstrip().startswith("'"):
                match = re.match(r"\s*'((?:[^']|'')*)'", value)
                if not match:
                    raise RiloError(f"unterminated string value for {key}")
                cards[key] = match.group(1).replace("''", "'").rstrip()
            else:
                cards[key] = value.split("/", 1)[0].strip()
    raise RiloError("FITS END card not found")


def check_header(cards: dict[str, str], image_no: int) -> None:
    if not list(cards)[:5] == ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2"]:
        raise RiloError(f"image {image_no}: mandatory FITS keywords out of order: {list(cards)[:5]}")
    for key, wanted in HEADER_REQUIREMENTS.items():
        if cards.get(key) != wanted:
            raise RiloError(f"image {image_no}: header {key}={cards.get(key)!r}, expected {wanted!r}")
    for key in ("BZERO", "BSCALE", "BLANK", "NAXIS3"):
        if key in cards:
            raise RiloError(f"image {image_no}: unexpected keyword {key}={cards[key]!r}")
    if int(cards.get("IMAGE", "-1")) != image_no:
        raise RiloError(f"image {image_no}: header IMAGE={cards.get('IMAGE')!r}")
    if not cards.get("FILENAME", "").upper() == f"SWP{image_no:05d}.RILO":
        raise RiloError(f"image {image_no}: header FILENAME={cards.get('FILENAME')!r}")
    if int(cards.get("LIUECLAS", "99")) in CALIBRATION_CLASSES:
        raise RiloError(f"image {image_no}: calibration object class {cards.get('LIUECLAS')}")
    if not float(cards.get("LEXPTIME", "0")) > 0:
        raise RiloError(f"image {image_no}: non-positive exposure {cards.get('LEXPTIME')!r}")


def decode(raw: bytes, image_no: int) -> tuple[bytes, dict[str, str]]:
    if len(raw) != FILE_BYTES:
        raise RiloError(f"image {image_no}: FITS length {len(raw)} != {FILE_BYTES}")
    cards, header_bytes = parse_header(raw)
    if header_bytes != HEADER_BYTES:
        raise RiloError(f"image {image_no}: header length {header_bytes} != {HEADER_BYTES}")
    check_header(cards, image_no)
    pixels = raw[header_bytes:header_bytes + PIXELS]
    padding = raw[header_bytes + PIXELS:]
    if len(pixels) != PIXELS or len(padding) != FITS_BLOCK - PIXELS % FITS_BLOCK:
        raise RiloError(f"image {image_no}: data unit has wrong size")
    if padding.count(0) != len(padding):
        raise RiloError(f"image {image_no}: nonzero FITS data padding")
    return pixels, cards


def block_mean(pixels: bytes, row0: int, col0: int, size: int) -> float:
    total = 0
    for row in range(row0, row0 + size):
        start = row * SAMPLES + col0
        total += sum(pixels[start:start + size])
    return total / (size * size)


def structure_stats(pixels: bytes) -> dict[str, float | int]:
    corners = [
        block_mean(pixels, 0, 0, 64),
        block_mean(pixels, 0, SAMPLES - 64, 64),
        block_mean(pixels, LINES - 64, 0, 64),
        block_mean(pixels, LINES - 64, SAMPLES - 64, 64),
    ]
    return {
        "minimum": min(pixels),
        "maximum": max(pixels),
        "distinct_values": len(set(pixels)),
        "mean": round(sum(pixels) / len(pixels), 4),
        "corner_mean_max": round(max(corners), 4),
        "center_mean": round(block_mean(pixels, 256, 256, 256), 4),
    }


def check_structure(stats: dict, image_no: int) -> None:
    """Reject degenerate frames and frames whose camera target is not where a raw SWP frame puts it."""
    if stats["minimum"] == stats["maximum"] or stats["distinct_values"] < 16:
        raise RiloError(f"image {image_no}: degenerate pixel distribution {stats}")
    if stats["center_mean"] < 5 or stats["corner_mean_max"] > 0.5 * stats["center_mean"]:
        raise RiloError(f"image {image_no}: raw frame structure check failed {stats}")
