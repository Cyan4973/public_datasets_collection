#!/usr/bin/env python3
"""Independently re-derive and check every IUE SWP raw-frame sample.

Deliberately does not import iue_rilo.py: the gzip member is inflated with a
hand-parsed RFC 1952 header and raw zlib, the FITS header is scanned with its
own card parser, and every emitted sample is byte-compared to the re-derived
data unit. Index rows, manifest scope, duplicates and degeneracy are checked.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "mast_iue_swp_raw_image_u8"
SERIES_ID = "iue_swp_lowdisp_raw_dn_u8"
SIDE = 768
FRAME = SIDE * SIDE
FITS_TOTAL = 619200
REQUIRED = {
    "SIMPLE": "T", "BITPIX": "8", "NAXIS": "2", "NAXIS1": "768", "NAXIS2": "768", "BUNIT": "DN",
    "TELESCOP": "IUE", "CAMERA": "SWP", "DISPERSN": "LOW", "DISPTYPE": "LOW", "APERTURE": "LARGE",
    "READMODE": "FULL", "READGAIN": "LOW", "EXPOGAIN": "MAXIMUM", "UVC-VOLT": "-5.0", "STATION": "GSFC",
    "ABNNOSTD": "NO", "ABNREAD": "NO", "ABNUVC": "NO", "ABNHISTR": "NO", "ABNOTHER": "NO", "ABNMINFR": "NO",
    "LEXPTRMD": "NO-TRAIL", "LEXPMULT": "NO", "LEXPSEGM": "NO",
}
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def inflate_gzip(blob: bytes, name: str) -> tuple[bytes, int, int]:
    if len(blob) < 18 or blob[0:2] != b"\x1f\x8b" or blob[2] != 8:
        fail(f"{name}: not a deflate gzip member")
    flags = blob[3]
    if flags & 0xE0:
        fail(f"{name}: reserved gzip flags set")
    pos = 10
    if flags & 0x04:  # FEXTRA
        (xlen,) = struct.unpack_from("<H", blob, pos)
        pos += 2 + xlen
    if flags & 0x08:  # FNAME
        end = blob.index(b"\x00", pos)
        stored = blob[pos:end].decode("latin-1")
        if not stored.lower().startswith(name.split(".")[0].lower()):
            fail(f"{name}: gzip FNAME {stored!r} does not name the image")
        pos = end + 1
    if flags & 0x10:  # FCOMMENT
        pos = blob.index(b"\x00", pos) + 1
    if flags & 0x02:  # FHCRC
        pos += 2
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    data = inflater.decompress(blob[pos:]) + inflater.flush()
    if not inflater.eof:
        fail(f"{name}: truncated deflate stream")
    trailer = inflater.unused_data
    if len(trailer) != 8:
        fail(f"{name}: expected exactly one gzip member with an 8-byte trailer, got {len(trailer)} trailing bytes")
    crc, isize = struct.unpack("<II", trailer)
    if zlib.crc32(data) & 0xFFFFFFFF != crc or len(data) & 0xFFFFFFFF != isize:
        fail(f"{name}: gzip CRC32/ISIZE mismatch")
    return data, crc, isize


CARD = re.compile(r"^([A-Z0-9_-]{1,8}) *= *('(?:[^']|'')*'|[^/]*)")


def fits_header(data: bytes, name: str) -> tuple[dict[str, str], int]:
    values: dict[str, str] = {}
    for index in range(0, len(data) // 80):
        card = data[index * 80:(index + 1) * 80]
        if any(byte < 32 or byte > 126 for byte in card):
            fail(f"{name}: non-printable byte in FITS header card {index}")
        text = card.decode("ascii")
        if text.rstrip() == "END":
            end_block = (index * 80) // 2880 + 1
            return values, end_block * 2880
        if text[8:10] != "= ":
            continue
        match = CARD.match(text)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw.startswith("'"):
            raw = raw[1:-1].replace("''", "'").rstrip()
        values.setdefault(key, raw)
    fail(f"{name}: no END card")
    raise AssertionError


def corner_center(frame: bytes) -> tuple[float, float]:
    def mean(r0: int, c0: int, size: int) -> float:
        return sum(sum(frame[r * SIDE + c0:r * SIDE + c0 + size]) for r in range(r0, r0 + size)) / (size * size)
    corners = max(mean(0, 0, 64), mean(0, SIDE - 64, 64), mean(SIDE - 64, 0, 64), mean(SIDE - 64, SIDE - 64, 64))
    return corners, mean(256, 256, 256)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    data_dir = args.data_dir
    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series with the expected id")
    series = series[0]
    if (series.get("numeric_kind"), series.get("bit_width")) != ("uint", 8):
        fail("manifest series must be uint8")

    with (args.recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    if len(sources) != series["sample_count"]:
        fail(f"sources.tsv rows {len(sources)} != manifest sample_count {series['sample_count']}")

    index_path = data_dir / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(sources):
        fail(f"index rows {len(rows)} != sources {len(sources)}")
    output_dir = data_dir / series["output_path"]
    on_disk = sorted(p.name for p in output_dir.iterdir())
    expected_names = sorted(f"swp{int(s['image_no']):05d}.u8" for s in sources)
    if on_disk != expected_names:
        fail("sample directory contents do not match the pinned selection (stale or missing files)")

    hashes: set[str] = set()
    total_bytes = 0
    histogram = [0] * 256
    exposures = []
    for source, row in zip(sources, rows):
        image_no = int(source["image_no"])
        name = source["filename"]
        for key in INDEX_KEYS:
            if key not in row:
                fail(f"index row for {name} lacks {key}")
        expected_row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": f"{series['output_path']}swp{image_no:05d}.u8", "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": FRAME, "value_count": FRAME,
        }
        for key, value in expected_row.items():
            if row[key] != value:
                fail(f"index row for {name}: {key}={row[key]!r}, expected {value!r}")
        download = data_dir / "downloads" / DATASET_ID / "rilo" / name
        blob = download.read_bytes()
        if len(blob) != int(source["size_bytes"]):
            fail(f"{name}: download size differs from pin")
        if source["sha256"] and hashlib.sha256(blob).hexdigest() != source["sha256"]:
            fail(f"{name}: download SHA-256 differs from pin")
        data, crc, isize = inflate_gzip(blob, name)
        if f"{crc:08x}" != source["gzip_crc32"] or isize != int(source["gzip_isize"]) or isize != FITS_TOTAL:
            fail(f"{name}: gzip trailer differs from pin")
        header, data_start = fits_header(data, name)
        for key, value in REQUIRED.items():
            if header.get(key) != value:
                fail(f"{name}: FITS {key}={header.get(key)!r}, expected {value!r}")
        if any(key in header for key in ("BZERO", "BSCALE", "BLANK")):
            fail(f"{name}: scaled or blanked pixel values")
        if header.get("IMAGE") != str(image_no) or int(header.get("LIUECLAS", "99")) in (98, 99):
            fail(f"{name}: IMAGE/object-class check failed")
        if data_start + FRAME + 576 != len(data) or any(data[data_start + FRAME:]):
            fail(f"{name}: unexpected data-unit length or nonzero padding")
        frame = data[data_start:data_start + FRAME]
        sample = (data_dir / row["sample_path"]).read_bytes()
        if sample != frame:
            fail(f"{name}: emitted sample differs from the re-derived FITS data unit")
        digest = hashlib.sha256(sample).hexdigest()
        if row.get("sha256") != digest or digest in hashes:
            fail(f"{name}: index sha256 mismatch or duplicate frame")
        hashes.add(digest)
        distinct = len(set(sample))
        if row.get("minimum") != min(sample) or row.get("maximum") != max(sample) or row.get("distinct_values") != distinct:
            fail(f"{name}: index min/max/distinct mismatch")
        if distinct < 16 or min(sample) == max(sample):
            fail(f"{name}: degenerate frame")
        corners, center = corner_center(sample)
        if center < 5 or corners > 0.5 * center:
            fail(f"{name}: raw-frame structure check failed corners={corners:.3f} center={center:.3f}")
        for value in sample:
            histogram[value] += 1
        exposures.append(float(header["LEXPTIME"]))
        total_bytes += len(sample)
    if total_bytes != series["total_size_bytes"]:
        fail(f"total bytes {total_bytes} != manifest total_size_bytes {series['total_size_bytes']}")
    used_levels = sum(1 for count in histogram if count)
    if used_levels < 200:
        fail(f"aggregate DN histogram uses only {used_levels} levels")
    print(
        f"verify ok samples={len(rows)} bytes={total_bytes} dn_levels={used_levels} "
        f"exposure_s_min={min(exposures):.3f} exposure_s_max={max(exposures):.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
