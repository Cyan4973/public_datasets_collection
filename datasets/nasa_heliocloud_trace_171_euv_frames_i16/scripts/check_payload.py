#!/usr/bin/env python3
"""Semantic validation of one downloaded TRACE FITS file against its sources.tsv pin.

usage: check_payload.py <file> <sources.tsv> <filename>
Checks exact size, MD5 == pinned single-part S3 ETag, FITS header regime, key/DATE_OBS
agreement, pinned header facts and the zero data padding. Prints the file SHA-256.
"""

from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_fits as T  # noqa: E402


def main() -> None:
    path, sources, filename = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    pins = {r["filename"]: r for r in csv.DictReader(open(sources, newline=""), delimiter="\t")}
    pin = pins.get(filename)
    if pin is None:
        raise SystemExit(f"{filename}: not pinned")
    blob = path.read_bytes()
    if len(blob) != int(pin["size_bytes"]):
        raise SystemExit(f"{filename}: size {len(blob)} != {pin['size_bytes']}")
    md5 = hashlib.md5(blob).hexdigest()
    if md5 != pin["md5_etag"]:
        raise SystemExit(f"{filename}: md5 {md5} != pinned ETag {pin['md5_etag']}")
    h, hist, off = T.parse_header(blob)
    problems = T.regime_problems(h, hist)
    if not T.key_matches_header(pin["key"], h):
        problems.append("key timestamp != DATE_OBS")
    for field, key in (("date_obs", "DATE_OBS"), ("frm_nam", "FRM_NAM"), ("sht_mdur", "SHT_MDUR"),
                       ("img_max", "IMG_MAX")):
        if str(h.get(key)) != pin[field]:
            problems.append(f"{key}={h.get(key)!r} != pinned {pin[field]!r}")
    if problems:
        raise SystemExit(f"{filename}: header regime/pin problems: {problems}")
    T.decode_pixels(blob, off)  # layout + zero padding check
    print(hashlib.sha256(blob).hexdigest())


if __name__ == "__main__":
    main()
