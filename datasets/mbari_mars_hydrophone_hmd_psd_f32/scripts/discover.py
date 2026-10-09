#!/usr/bin/env python3
"""Resolve the pinned day list for mbari_mars_hydrophone_hmd_psd_f32.

Documentation of how ``days.tsv`` was produced (run via ``discover.sh``; it is
not part of the download/build path). Network I/O is done with curl.

1. Page the public S3 listing of ``pacific-sound-spectra`` per year prefix
   (2017..2023) and keep keys matching ``YYYY/MARS_YYYYMMDD.nc`` with size
   16,124,324 B (excludes ``mb05/``, ``MANTA_961/``, ``MBARI/`` and the jpg
   quick-looks by construction).
2. Order the pool by date and take N=36 targets at evenly spaced positions
   ``floor((k + 0.5) * len(pool) / N)``.
3. For each target, probe candidates at offsets 0, +1, -1, +2, -2, ... (max 10)
   with two small range GETs (first 40,000 B and last 40,000 B), parse the HDF5
   headers with ``mars_hdf5`` and accept the first day whose ``psd`` dataset is
   a contiguous IEEE f32 LE 1440 x 2787 array of 16,053,120 B, whose ``time``
   axis is exactly the 1440 minutes of that UTC date, and whose ``effort``
   (seconds of input audio per minute) is 60.0 for all 1440 minutes.
4. Write key, size, ETag, LastModified, psd address, effort summary.
"""

from __future__ import annotations

import argparse
import calendar
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mars_hdf5 as h5  # noqa: E402

BUCKET = "https://pacific-sound-spectra.s3.amazonaws.com"
FILE_SIZE = 16124324
SHAPE = (1440, 2787)
PSD_BYTES = SHAPE[0] * SHAPE[1] * 4
YEARS = range(2017, 2024)
PROBE = 40000


def curl(args: list[str]) -> bytes:
    return subprocess.run(
        ["curl", "-fsS", "--retry", "5", "--retry-delay", "2", "--max-time", "120", *args],
        check=True, stdout=subprocess.PIPE,
    ).stdout


def listing() -> list[tuple[str, str, str, int]]:
    pat = re.compile(
        r"<Key>([^<]+)</Key><LastModified>([^<]+)</LastModified>"
        r"<ETag>&quot;([^&]+)&quot;</ETag><Size>(\d+)</Size>"
    )
    rows = []
    for year in YEARS:
        text = curl([f"{BUCKET}/?list-type=2&prefix={year}/&max-keys=1000"]).decode()
        if "<IsTruncated>false</IsTruncated>" not in text:
            raise SystemExit(f"listing for {year} truncated; add continuation paging")
        for key, mod, etag, size in pat.findall(text):
            if re.fullmatch(rf"{year}/MARS_{year}\d{{4}}\.nc", key) and int(size) == FILE_SIZE:
                rows.append((key, mod, etag, int(size)))
    rows.sort()
    return rows


def probe(key: str) -> dict[str, object]:
    head = curl(["-r", f"0-{PROBE - 1}", f"{BUCKET}/{key}"])
    tail = curl(["-r", f"{FILE_SIZE - PROBE}-{FILE_SIZE - 1}", f"{BUCKET}/{key}"])
    if len(head) != PROBE or len(tail) != PROBE:
        raise SystemExit(f"short range read for {key}")
    buf = head + b"\0" * (FILE_SIZE - 2 * PROBE) + tail

    def region_ok(addr: int, size: int) -> bool:
        return addr + size <= PROBE or addr >= FILE_SIZE - PROBE

    info = h5.root_datasets(buf)
    psd = info["psd"]
    lay = psd["layout"]
    ok = (
        tuple(psd["shape"]) == SHAPE
        and h5.is_ieee_f32le(psd["dtype"])
        and lay["class"] == 1
        and lay["size"] == PSD_BYTES
        and psd["filters"] == 0
    )
    t = info["time"]["layout"]
    e = info["effort"]["layout"]
    if not (region_ok(t["address"], t["size"]) and region_ok(e["address"], e["size"])):
        raise SystemExit(f"{key}: coordinate arrays outside probed ranges")
    times = struct.unpack("<1440q", buf[t["address"]:t["address"] + 11520])
    effort = struct.unpack("<1440f", buf[e["address"]:e["address"] + 5760])
    ymd = re.search(r"MARS_(\d{4})(\d{2})(\d{2})", key).groups()
    day0 = calendar.timegm((int(ymd[0]), int(ymd[1]), int(ymd[2]), 0, 0, 0))
    times_ok = list(times) == [day0 + 60 * i for i in range(1440)]
    full = sum(1 for v in effort if v == 60.0)
    return {
        "ok": ok and times_ok,
        "psd_address": lay["address"],
        "full_minutes": full,
        "effort_sum": sum(effort),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=36)
    ap.add_argument("--max-offset", type=int, default=10)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    pool = listing()
    print(f"pool={len(pool)} first={pool[0][0]} last={pool[-1][0]}", file=sys.stderr)
    chosen = []
    offsets = [0]
    for d in range(1, args.max_offset + 1):
        offsets += [d, -d]
    for k in range(args.count):
        target = (2 * k + 1) * len(pool) // (2 * args.count)
        for off in offsets:
            idx = target + off
            if not 0 <= idx < len(pool):
                continue
            key, mod, etag, size = pool[idx]
            r = probe(key)
            print(f"k={k} target={target} off={off} {key} {r}", file=sys.stderr)
            if r["ok"] and r["full_minutes"] == 1440:
                chosen.append((key, size, etag, mod, r["psd_address"], off))
                break
        else:
            raise SystemExit(f"no full-coverage day near target {k}")
    with args.out.open("w") as fh:
        fh.write("key\tsize_bytes\tetag\tlast_modified\tpsd_address_at_discovery\ttarget_offset\n")
        for row in chosen:
            fh.write("\t".join(str(x) for x in row) + "\n")
    print(f"wrote {len(chosen)} rows to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
