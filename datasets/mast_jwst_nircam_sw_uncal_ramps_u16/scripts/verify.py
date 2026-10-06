#!/usr/bin/env python3
"""Independently re-derive and check every NIRCam SW uncal ramp sample.

Deliberately does not import jwst_uncal.py: the FITS headers are scanned with
their own card parser, the HDU chain is re-walked, the SCI cube is decoded by a
different method (whole-cube big-integer XOR with 0x8000 words, then array
byteswap), the S3 CRC64-NVME content pin is recomputed with a separate
implementation, and each emitted sample is byte-compared with the re-derived
cube. Index rows, manifest scope, duplicates and degeneracy are checked with
the same policy as build.py (no values masked, filled or dropped).
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import re
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "mast_jwst_nircam_sw_uncal_ramps_u16"
SERIES_ID = "nircam_sw_full_medium8_uncal_ramp_dn_u16"
NX = NY = 2048
NG = 8
PLANE = NX * NY
CUBE_VALUES = NG * PLANE
REF = 4
MIN_DISTINCT = 1024
EXPECTED_SAMPLES = 12
HDU_NAMES = ["PRIMARY", "SCI", "ZEROFRAME", "GROUP", "INT_TIMES", "ASDF"]
PRIMARY_REQ = {
    "SIMPLE": "T", "NAXIS": "0", "TELESCOP": "JWST", "INSTRUME": "NIRCAM", "PROGRAM": "02736",
    "OBSERVTN": "001", "VISIT": "001", "EXP_TYPE": "NRC_IMAGE", "CHANNEL": "SHORT", "PUPIL": "CLEAR",
    "SUBARRAY": "FULL", "READPATT": "MEDIUM8", "NGROUPS": "8", "NINTS": "1", "NFRAMES": "8",
    "GROUPGAP": "2", "COMPRESS": "F", "DATAPROB": "F", "DATAMODL": "Level1bModel",
}
SCI_REQ = {
    "XTENSION": "IMAGE", "EXTNAME": "SCI", "BITPIX": "16", "NAXIS": "4", "NAXIS1": "2048", "NAXIS2": "2048",
    "NAXIS3": "8", "NAXIS4": "1", "BZERO": "32768", "BSCALE": "1", "BUNIT": "DN",
}
DETECTORS = {f"NRC{m}{n}" for m in "AB" for n in "1234"}
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]
CARD = re.compile(r"^([A-Z0-9_-]{1,8}) *= *('(?:[^']|'')*'|[^/]*)")


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def header(data: bytes, start: int, name: str) -> tuple[dict[str, str], int]:
    values: dict[str, str] = {}
    index = 0
    while start + (index + 1) * 80 <= len(data):
        text = data[start + index * 80:start + (index + 1) * 80].decode("ascii", errors="strict")
        index += 1
        if text.rstrip() == "END":
            blocks = (index * 80 + 2879) // 2880
            return values, blocks * 2880
        if text[8:10] != "= ":
            continue
        match = CARD.match(text)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw.startswith("'"):
            raw = raw[1:-1].replace("''", "'").rstrip()
        values.setdefault(key, raw)
    fail(f"{name}: header at {start} has no END card")
    raise AssertionError


def hdu_chain(data: bytes, name: str) -> list[tuple[str, dict[str, str], int, int]]:
    chain = []
    pos = 0
    while pos < len(data):
        cards, hlen = header(data, pos, name)
        naxis = int(cards["NAXIS"])
        n = 0
        if naxis:
            n = 1
            for k in range(naxis):
                n *= int(cards[f"NAXIS{k + 1}"])
        nbytes = abs(int(cards["BITPIX"])) // 8 * int(cards.get("GCOUNT", "1")) * (int(cards.get("PCOUNT", "0")) + n)
        label = "PRIMARY" if not chain else cards.get("EXTNAME", "?")
        chain.append((label, cards, pos + hlen, nbytes))
        pos += hlen + -(-nbytes // 2880) * 2880
    if pos != len(data):
        fail(f"{name}: HDU chain ends at {pos}, file has {len(data)} bytes")
    return chain


CRC_POLY = 0xAD93D23594C93659


def _reflect64(value: int) -> int:
    return int(f"{value:064b}"[::-1], 2)


_RPOLY = _reflect64(CRC_POLY)
_CRC_TABLE = [0] * 256
for _n in range(256):
    _r = _n
    for _k in range(8):
        _r = (_r >> 1) ^ (_RPOLY if _r & 1 else 0)
    _CRC_TABLE[_n] = _r


def crc64_nvme(data: bytes) -> str:
    table = _CRC_TABLE
    reg = 0xFFFFFFFFFFFFFFFF
    for b in data:
        reg = (reg >> 8) ^ table[(reg ^ b) & 0xFF]
    reg ^= 0xFFFFFFFFFFFFFFFF
    return base64.b64encode(reg.to_bytes(8, "big")).decode("ascii")


_MASK = None


def decode_cube(raw_be: bytes) -> bytes:
    """Big-endian int16 words + 32768 -> little-endian uint16 bytes, via big-int XOR."""
    global _MASK
    if _MASK is None or _MASK[0] != len(raw_be):
        _MASK = (len(raw_be), int.from_bytes(b"\x80\x00" * (len(raw_be) // 2), "big"))
    flipped = (int.from_bytes(raw_be, "big") ^ _MASK[1]).to_bytes(len(raw_be), "big")
    words = array("H")
    words.frombytes(flipped)
    if sys.byteorder == "little":
        words.byteswap()          # now native values
        return words.tobytes()    # native == little-endian
    swapped = array("H", words)
    swapped.byteswap()
    return swapped.tobytes()


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
    if (series.get("numeric_kind"), series.get("bit_width"), series.get("endianness")) != ("uint", 16, "little"):
        fail("manifest series must be little-endian uint16")

    with (args.recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    if len(sources) != EXPECTED_SAMPLES or series.get("sample_count") != EXPECTED_SAMPLES:
        fail(f"expected {EXPECTED_SAMPLES} sources and manifest sample_count, got {len(sources)} / {series.get('sample_count')}")
    if len({s["filename"] for s in sources}) != len(sources):
        fail("duplicate filenames in sources.tsv")

    index_path = data_dir / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(sources):
        fail(f"index rows {len(rows)} != sources {len(sources)}")
    out_dir = data_dir / series["output_path"]
    expected_names = sorted(s["filename"][: -len("_uncal.fits")] + ".u16" for s in sources)
    if sorted(p.name for p in out_dir.iterdir()) != expected_names:
        fail("sample directory contents do not match the pinned selection (stale, partial or missing files)")

    total = 0
    sample_hashes: set[str] = set()
    detectors = set()
    filters = set()
    for source, row in zip(sources, rows):
        name = source["filename"]
        stem = name[: -len("_uncal.fits")]
        for key in INDEX_KEYS:
            if key not in row:
                fail(f"index row for {name} lacks {key}")
        expected_row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": f"{series['output_path'].rstrip('/')}/{stem}.u16",
            "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
            "sample_size_bytes": CUBE_VALUES * 2, "value_count": CUBE_VALUES, "source_file": name,
        }
        for key, want in expected_row.items():
            if row.get(key) != want:
                fail(f"{name}: index {key}={row.get(key)!r}, expected {want!r}")

        data = (data_dir / "downloads" / DATASET_ID / "uncal" / name).read_bytes()
        if len(data) != int(source["size_bytes"]):
            fail(f"{name}: size {len(data)} != pinned {source['size_bytes']}")
        if crc64_nvme(data) != source["crc64nvme"]:
            fail(f"{name}: CRC64-NVME mismatch with pinned S3 checksum")
        if source.get("sha256") and hashlib.sha256(data).hexdigest() != source["sha256"]:
            fail(f"{name}: SHA-256 mismatch with pinned value")
        chain = hdu_chain(data, name)
        if [c[0] for c in chain] != HDU_NAMES:
            fail(f"{name}: HDU sequence {[c[0] for c in chain]}")
        primary, sci = chain[0][1], chain[1][1]
        for key, want in PRIMARY_REQ.items():
            if primary.get(key) != want:
                fail(f"{name}: primary {key}={primary.get(key)!r}")
        if primary.get("FILENAME") != name or primary.get("DETECTOR") not in DETECTORS \
                or primary.get("DETECTOR") != source["detector"] or primary.get("FILTER") != source["filter"]:
            fail(f"{name}: FILENAME/DETECTOR/FILTER disagree with the pin")
        for key, want in SCI_REQ.items():
            if sci.get(key) != want:
                fail(f"{name}: SCI {key}={sci.get(key)!r}")
        if "BLANK" in sci:
            fail(f"{name}: SCI declares BLANK")
        start, nbytes = chain[1][2], chain[1][3]
        if nbytes != CUBE_VALUES * 2:
            fail(f"{name}: SCI data length {nbytes}")
        derived = decode_cube(data[start:start + nbytes])
        del data

        sample_path = data_dir / row["sample_path"]
        stored = sample_path.read_bytes()
        if stored != derived:
            fail(f"{name}: emitted sample differs from the independently re-derived SCI cube")
        del derived
        digest = hashlib.sha256(stored).hexdigest()
        if digest != row.get("sha256"):
            fail(f"{name}: index sha256 mismatch")
        if digest in sample_hashes:
            fail(f"{name}: duplicate sample")
        sample_hashes.add(digest)

        values = array("H")
        values.frombytes(stored)
        if sys.byteorder == "big":
            values.byteswap()
        lo, hi = min(values), max(values)
        distinct = len(set(values))
        if (lo, hi) != (row.get("minimum"), row.get("maximum")) or distinct != row.get("distinct_values"):
            fail(f"{name}: index min/max/distinct disagree with stored values ({lo}, {hi}, {distinct})")
        if distinct < MIN_DISTINCT:
            fail(f"{name}: degenerate cube ({distinct} distinct values)")
        means = []
        planes = set()
        for g in range(NG):
            plane = values[g * PLANE:(g + 1) * PLANE]
            if min(plane) == max(plane):
                fail(f"{name}: group {g + 1} is constant")
            planes.add(hashlib.sha256(plane.tobytes()).hexdigest())
            interior = plane[REF * NX:(NY - REF) * NX]
            means.append(sum(interior) / len(interior))
        if len(planes) != NG:
            fail(f"{name}: identical groups within the ramp")
        if not means[-1] > means[0]:
            fail(f"{name}: no accumulated signal up the ramp ({means[0]:.2f} -> {means[-1]:.2f})")
        del values, stored
        total += CUBE_VALUES * 2
        detectors.add(source["detector"])
        filters.add(source["filter"])
        print(f"verified {stem} min={lo} max={hi} distinct={distinct} interior_mean g1={means[0]:.2f} g{NG}={means[-1]:.2f}")

    if total != series.get("total_size_bytes"):
        fail(f"total bytes {total} != manifest total_size_bytes {series.get('total_size_bytes')}")
    if total > 1_000_000_000:
        fail("primary output exceeds the 1 GB cap")
    if detectors != DETECTORS or filters != {"F090W", "F200W"}:
        fail(f"claimed scope not realized: detectors={sorted(detectors)} filters={sorted(filters)}")
    print(f"verify ok samples={len(rows)} bytes={total} detectors={len(detectors)} filters={sorted(filters)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
