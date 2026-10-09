#!/usr/bin/env python3
"""Validate one downloaded MARS daily HMD NetCDF4 file.

Checks: exact size, S3 multipart ETag (MD5 of 8 MiB parts), HDF5 structure
(psd located by root-group link name, contiguous IEEE f32 LE 1440 x 2787,
16,053,120 B, unfiltered, inside the file), the time axis equals the 1440
minutes of the file's UTC date, title/site text, and the embedded CC-BY 4.0
statement. Exit status nonzero on any mismatch.
"""

from __future__ import annotations

import calendar
import hashlib
import mmap
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mars_hdf5 as h5  # noqa: E402

FILE_SIZE = 16124324
PART_SIZE = 8 * 1024 * 1024
SHAPE = (1440, 2787)
PSD_BYTES = SHAPE[0] * SHAPE[1] * 4
LICENSE_TEXT = b"this derived data product carries the CC-BY 4.0 license"
TITLE_TEXT = b"Hybrid Millidecade Band Sound Pressure Levels Computed at 1 Minute Resolution"
SITE_TEXT = b"Monterey Accelerated Research System (MARS) Cabled Observatory"


def multipart_etag(path: Path) -> str:
    digests = []
    with path.open("rb") as fh:
        while block := fh.read(PART_SIZE):
            digests.append(hashlib.md5(block).digest())
    if len(digests) == 1:
        return digests[0].hex()
    return f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}"


def check_structure(raw, key: str) -> dict[str, int]:
    info = h5.root_datasets(raw)
    for name in ("psd", "time", "frequency", "effort"):
        if name not in info:
            raise ValueError(f"{key}: root group lacks {name!r}; links={sorted(info)}")
    psd = info["psd"]
    lay = psd["layout"]
    if tuple(psd["shape"]) != SHAPE:
        raise ValueError(f"{key}: psd shape {psd['shape']} != {SHAPE}")
    if not h5.is_ieee_f32le(psd["dtype"]):
        raise ValueError(f"{key}: psd dtype is not IEEE float32 little-endian: {psd['dtype']}")
    if lay["class"] != 1:
        raise ValueError(f"{key}: psd layout class {lay['class']} is not contiguous (chunked/compact rejected)")
    if psd["filters"]:
        raise ValueError(f"{key}: psd has a filter pipeline (compressed variant rejected)")
    if lay["size"] != PSD_BYTES or lay["address"] + lay["size"] > FILE_SIZE or lay["address"] < 96:
        raise ValueError(f"{key}: psd contiguous span invalid: {lay}")
    t = info["time"]
    if tuple(t["shape"]) != (SHAPE[0],) or t["layout"]["class"] != 1 or t["layout"]["size"] != SHAPE[0] * 8:
        raise ValueError(f"{key}: unexpected time variable {t['shape']} {t['layout']}")
    m = re.search(r"MARS_(\d{4})(\d{2})(\d{2})\.nc$", key)
    if not m:
        raise ValueError(f"{key}: not a MARS daily key")
    day0 = calendar.timegm((int(m[1]), int(m[2]), int(m[3]), 0, 0, 0))
    a = t["layout"]["address"]
    times = struct.unpack(f"<{SHAPE[0]}q", raw[a:a + SHAPE[0] * 8])
    if list(times) != [day0 + 60 * i for i in range(SHAPE[0])]:
        raise ValueError(f"{key}: time axis is not the 1440 minutes of its date")
    return {"psd_address": lay["address"]}


def main() -> int:
    path = Path(sys.argv[1])
    key = sys.argv[2]
    etag = sys.argv[3]
    if not path.is_file() or path.stat().st_size != FILE_SIZE:
        raise SystemExit(f"{key}: wrong size {path.stat().st_size if path.exists() else 'missing'} != {FILE_SIZE}")
    actual = multipart_etag(path)
    if actual != etag:
        raise SystemExit(f"{key}: multipart ETag mismatch expected={etag} actual={actual}")
    with path.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        head = raw[:65536]
        for text, label in ((LICENSE_TEXT, "CC-BY 4.0 license statement"), (TITLE_TEXT, "HMD title"), (SITE_TEXT, "MARS site")):
            if head.find(text) < 0:
                raise SystemExit(f"{key}: missing embedded {label}")
        try:
            info = check_structure(raw, key)
        except (ValueError, struct.error) as exc:
            raise SystemExit(f"{key}: HDF5 validation failed: {exc}") from exc
    print(f"valid key={key} etag={actual} psd_address={info['psd_address']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
