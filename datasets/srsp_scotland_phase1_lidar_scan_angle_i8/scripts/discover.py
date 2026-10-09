#!/usr/bin/env python3
"""Maintainer-only tile discovery for srsp_scotland_phase1_lidar_scan_angle_i8.

Not run by download.sh or build.sh. Documents how scripts/tiles.tsv was made.

1. Lists s3://srsp-open-data/lidar/phase-1/laz/ (public ListObjectsV2, curl,
   continuation tokens) and sorts the 12,464 .laz keys.
2. Takes CANDIDATES keys evenly spaced over the sorted list (index
   floor((i + 0.5) * N / CANDIDATES)).
3. For each candidate, uses curl byte-range reads (header, chunk table at the
   file tail, chunk 0 only) and decodes chunk 0 with tools/laz/laszip.py.
   Several Phase I collection areas were delivered with the scan-angle-rank
   byte zeroed in every point (range probes of first/middle/last chunks
   showed such tiles are all-zero throughout); a candidate is kept only when
   its chunk 0 scan angle is not constant (at least 2 distinct values;
   zeroed tiles have exactly one value, 0).
4. Writes key, size, ETag and the chunk-0 probe stats to a TSV. sha256 is
   filled in from the first verified download (download_inventory.json).

usage: python3 -I discover.py OUT_DIR [CANDIDATES]
"""
from __future__ import annotations

import collections
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "laz"))
import laszip  # noqa: E402

BASE = "https://srsp-open-data.s3.eu-west-2.amazonaws.com/"
PREFIX = "lidar/phase-1/laz/"


def curl(url: str, rng: str | None = None) -> bytes:
    cmd = ["curl", "-sfL", "--retry", "3", "--max-time", "120"]
    if rng:
        cmd += ["-r", rng]
    return subprocess.run(cmd + [url], check=True, capture_output=True).stdout


def list_keys() -> list[tuple[str, int, str]]:
    rows = []
    token = None
    while True:
        url = f"{BASE}?list-type=2&prefix={PREFIX}"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token, safe="")
        xml = curl(url).decode()
        for m in re.finditer(r"<Contents>(.*?)</Contents>", xml):
            c = m.group(1)
            key = re.search(r"<Key>(.*?)</Key>", c).group(1)
            etag = re.search(r"<ETag>(.*?)</ETag>", c).group(1).replace("&quot;", "").strip('"')
            size = int(re.search(r"<Size>(\d+)</Size>", c).group(1))
            if key.endswith(".laz"):
                rows.append((key, size, etag))
        t = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", xml)
        if not t:
            break
        token = t.group(1)
    rows.sort()
    return rows


def probe(key: str, size: int, scratch: Path) -> dict:
    head = curl(BASE + key, "0-4095")
    tail = curl(BASE + key, f"{size - 65536}-{size - 1}")
    with scratch.open("wb") as o:
        o.write(head)
        o.seek(size - len(tail))
        o.write(tail)
    hdr = laszip.read_header(str(scratch))
    lz = hdr["laszip"] or {}
    with scratch.open("rb") as fh:
        _, items, table = laszip._chunk_plan(fh, hdr)
    count, nbytes = table["entries"][0]
    n = count if count is not None else min(lz["chunk_size"], hdr["point_count"])
    start = table["chunks_start"]
    buf = curl(BASE + key, f"{start}-{start + nbytes - 1}") + bytes(16)
    rec, _ = laszip.decode_pointwise_chunk(buf, items, hdr["point_record_length"], n)
    sa = [b - 256 if b > 127 else b for b in rec[16::hdr["point_record_length"]]]
    c = collections.Counter(sa)
    return {
        "version": hdr["version"], "pdrf": hdr["point_format"],
        "rlen": hdr["point_record_length"], "points": hdr["point_count"],
        "compressor": lz.get("compressor"), "software": hdr["generating_software"],
        "c0_min": min(sa), "c0_max": max(sa), "c0_distinct": len(c),
    }


def main() -> None:
    out = Path(sys.argv[1])
    cands = int(sys.argv[2]) if len(sys.argv) > 2 else 128
    out.mkdir(parents=True, exist_ok=True)
    rows = list_keys()
    print(f"listed {len(rows)} keys, {sum(r[1] for r in rows)} bytes", flush=True)
    picks = sorted({int((i + 0.5) * len(rows) / cands) for i in range(cands)})
    kept, log = [], []
    for idx in picks:
        key, size, etag = rows[idx]
        p = probe(key, size, out / "sparse.laz")
        ok = (p["version"] == "1.2" and p["pdrf"] == 1 and p["rlen"] == 28
              and p["compressor"] == 2 and p["c0_distinct"] >= 2)
        log.append((idx, key, size, etag, p, ok))
        print(idx, key.rsplit("/", 1)[1], size, p, "KEEP" if ok else "skip", flush=True)
        if ok:
            kept.append((key, size, etag, p))
    with (out / "tiles.tsv").open("w") as fh:
        fh.write("key\tsize_bytes\tetag\tsha256\tpoint_count\tchunk0_scan_angle_min\tchunk0_scan_angle_max\n")
        for key, size, etag, p in kept:
            fh.write(f"{key}\t{size}\t{etag}\t\t{p['points']}\t{p['c0_min']}\t{p['c0_max']}\n")
    with (out / "discovery_log.tsv").open("w") as fh:
        fh.write("list_index\tkey\tsize_bytes\tetag\tpoints\tchunk0_min\tchunk0_max\tchunk0_distinct\tsoftware\tkept\n")
        for idx, key, size, etag, p, ok in log:
            fh.write(f"{idx}\t{key}\t{size}\t{etag}\t{p['points']}\t{p['c0_min']}\t{p['c0_max']}\t"
                     f"{p['c0_distinct']}\t{p['software']}\t{int(ok)}\n")
    print(f"candidates={len(picks)} kept={len(kept)} bytes={sum(k[1] for k in kept)}")


if __name__ == "__main__":
    main()
