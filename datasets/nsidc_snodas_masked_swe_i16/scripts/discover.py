#!/usr/bin/env python3
"""Resolve SNODAS masked SWE (product 1034) tar members without fetching whole tars.

Documentation/discovery helper, not part of download/build. For each date it
walks the 512-byte ustar headers of the daily SNODAS tar with one-block curl
range GETs, locates the SWE .dat.gz and .txt.gz members, and range-fetches the
last 8 bytes of the .dat.gz member (gzip CRC32 + ISIZE trailer) so the plan
pins the decompressed raster content without downloading it.

Usage: python3 -I discover.py YYYYMMDD [YYYYMMDD ...] > plan.tsv
Network I/O goes through the curl binary (honours ~/.curlrc proxies).
"""
from __future__ import annotations

import struct
import subprocess
import sys

BASE = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked"
MONTHS = ["01_Jan", "02_Feb", "03_Mar", "04_Apr", "05_May", "06_Jun",
          "07_Jul", "08_Aug", "09_Sep", "10_Oct", "11_Nov", "12_Dec"]


def tar_url(date: str) -> str:
    return f"{BASE}/{date[:4]}/{MONTHS[int(date[4:6]) - 1]}/SNODAS_{date}.tar"


def rng(url: str, start: int, length: int) -> bytes:
    out = subprocess.run(
        ["curl", "-sSfL", "--max-time", "60", "--retry", "3", "-r", f"{start}-{start + length - 1}", url],
        check=True, capture_output=True).stdout
    if len(out) != length:
        raise SystemExit(f"short range read {url} {start}+{length}: got {len(out)}")
    return out


def parse_header(block: bytes):
    if block == b"\0" * 512:
        return None
    name = block[0:100].split(b"\0", 1)[0].decode("ascii")
    size = int(block[124:136].split(b"\0", 1)[0].strip() or b"0", 8)
    chk = int(block[148:156].split(b"\0", 1)[0].strip(), 8)
    calc = sum(block[:148]) + 32 * 8 + sum(block[156:])
    if chk != calc:
        raise SystemExit(f"bad ustar header checksum for {name!r}")
    prefix = block[345:500].split(b"\0", 1)[0].decode("ascii") if block[257:262] == b"ustar" else ""
    return (prefix + "/" + name) if prefix else name, size


def main() -> None:
    print("date\ttar_url\tdat_member\tdat_offset\tdat_size\tdat_crc32\tdat_isize\ttxt_member\ttxt_offset\ttxt_size")
    for date in sys.argv[1:]:
        url = tar_url(date)
        off = 0
        found = {}
        while True:
            h = parse_header(rng(url, off, 512))
            if h is None:
                break
            name, size = h
            data_off = off + 512
            want = f"us_ssmv11034tS__T0001TTNATS{date}05HP001"
            if name == want + ".dat.gz":
                found["dat"] = (name, data_off, size)
            elif name == want + ".txt.gz":
                found["txt"] = (name, data_off, size)
            off = data_off + (size + 511) // 512 * 512
            if "dat" in found and "txt" in found:
                break
        if set(found) != {"dat", "txt"}:
            print(f"# {date}: SWE members not found", file=sys.stderr)
            continue
        dn, do, ds = found["dat"]
        crc, isize = struct.unpack("<II", rng(url, do + ds - 8, 8))
        tn, to, ts = found["txt"]
        print(f"{date}\t{url}\t{dn}\t{do}\t{ds}\t{crc:08x}\t{isize}\t{tn}\t{to}\t{ts}", flush=True)


if __name__ == "__main__":
    main()
