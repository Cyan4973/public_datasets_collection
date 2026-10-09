#!/usr/bin/env python3
"""Pin the first cam1 PNG members of each TUM VI euroc 1024_16 sequence tar.

Documentation of how `scripts/members.tsv` was resolved; not run by the
pipeline. It walks each tar's GNU/ustar headers with small HTTP range reads
(curl), never fetching image payloads: per member it reads one window that
covers the last 16 bytes of the previous member (last IDAT CRC + IEND chunk)
and the next 512-byte header.

Usage (from a scratch directory):
    python3 -I discover.py OUT.tsv [PER_TAR]
"""
from __future__ import annotations

import re
import subprocess
import sys

BASE = "https://vision.in.tum.de/tumvi/exported/euroc/1024_16/"
SEQUENCES = (
    [f"room{i}" for i in range(1, 7)]
    + [f"corridor{i}" for i in range(1, 6)]
    + [f"slides{i}" for i in range(1, 4)]
    + [f"magistrale{i}" for i in range(1, 7)]
    + [f"outdoors{i}" for i in range(1, 9)]
)
IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
MAX_MEMBERS_WALKED = 400


def fetch(url: str, start: int, end: int) -> tuple[bytes, int]:
    out = subprocess.run(
        ["curl", "-sSfL", "--max-time", "60", "--retry", "5", "-r", f"{start}-{end}",
         "-D", "-", url],
        check=True, capture_output=True,
    ).stdout
    # Split headers (possibly several responses) from body.
    total = -1
    body = out
    while body.startswith(b"HTTP/"):
        head, _, body = body.partition(b"\r\n\r\n")
        m = re.search(rb"Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)", head, re.I)
        if m:
            total = int(m.group(3))
            if (int(m.group(1)), int(m.group(2))) != (start, min(end, total - 1)):
                raise SystemExit(f"bad range {m.groups()} for {start}-{end}")
    if total < 0:
        raise SystemExit(f"server did not honour range for {url}")
    return body, total


def parse_header(h: bytes) -> tuple[str, int, bytes]:
    if len(h) != 512:
        raise SystemExit("short header")
    chk = int(h[148:156].split(b"\0")[0].strip() or b"0", 8)
    if chk != sum(h[:148]) + 256 + sum(h[156:]):
        raise SystemExit("tar header checksum mismatch")
    name = h[0:100].split(b"\0")[0].decode()
    prefix = h[345:500].split(b"\0")[0].decode() if h[257:263] == b"ustar\0" else ""
    if prefix:
        name = prefix + "/" + name
    size = int(h[124:136].split(b"\0")[0].strip() or b"0", 8)
    return name, size, h[156:157]


def walk(seq: str, per_tar: int, out) -> None:
    tar = f"dataset-{seq}_1024_16.tar"
    url = BASE + tar
    want = re.compile(rf"^dataset-{seq}_1024_16/mav0/cam1/data/(\d+)\.png$")
    hdr, total = fetch(url, 0, 511)
    off = 0
    kept = cam0 = other = 0
    pending = None  # (name, data_off, size) of a kept member awaiting its tail
    for _ in range(MAX_MEMBERS_WALKED):
        if hdr == b"\0" * 512:
            break
        name, size, typ = parse_header(hdr)
        if typ == b"L":
            raise SystemExit(f"GNU longname member in {tar}; extend discover.py")
        data_off = off + 512
        nxt = data_off + (size + 511) // 512 * 512
        if size >= 16:
            win, _ = fetch(url, data_off + size - 16, nxt + 511)
            tail, hdr = win[:16], win[nxt - (data_off + size - 16):]
        else:
            hdr, _ = fetch(url, nxt, nxt + 511)
            tail = b""
        if typ in (b"0", b"\0") and want.match(name):
            if tail[4:] != IEND:
                raise SystemExit(f"{tar}:{name} does not end with IEND")
            out.write(f"{seq}\t{tar}\t{total}\t{name}\t{data_off}\t{size}\t{tail[:4].hex()}\n")
            kept += 1
        elif "/mav0/cam0/" in name:
            cam0 += 1
        else:
            other += 1
        off = nxt
        if kept >= per_tar:
            break
    print(f"{seq}: kept={kept} cam0_skipped={cam0} other={other} prefix_end={off} tar_bytes={total}",
          file=sys.stderr, flush=True)


def main() -> None:
    path = sys.argv[1]
    per_tar = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    with open(path, "w", encoding="utf-8") as out:
        out.write("sequence\ttar\ttar_bytes\tmember\tdata_offset\tsize\tlast_idat_crc\n")
        for seq in SEQUENCES:
            walk(seq, per_tar, out)
            out.flush()


if __name__ == "__main__":
    main()
