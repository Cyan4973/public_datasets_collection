#!/usr/bin/env python3
"""Regenerate scripts/archives.tsv and scripts/frames.tsv from range probes.

Used by discover.sh only (documentation of how the pins were resolved); the
download, build and verify paths read the committed pin tables instead.

  archives DIR  parse listing.html, head_<archive>.txt and tail_<archive>.bin
                (last 64 KiB) -> archives.tsv, selected.tsv, header_ranges.tsv
  frames DIR    parse hdr_<archive>__<member>.bin (first 4 KiB of each
                selected member range) -> frames.tsv
"""
from __future__ import annotations

import csv
import hashlib
import re
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import microed_smv as m  # noqa: E402


def content_length(path: Path) -> int:
    text = path.read_text(encoding="iso-8859-1")
    final = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()][-1]
    match = re.search(r"^Content-Length:\s*(\d+)", final, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        raise SystemExit(f"no Content-Length in {path}")
    return int(match.group(1))


def archives(directory: Path) -> None:
    listing = (directory / "listing.html").read_text(encoding="utf-8", errors="replace")
    names = sorted({n[:-4] for n in re.findall(r'href="([^"?/]+\.zip)"', listing)})
    arch_rows, selected, probes = [], [], []
    for name in names:
        total = content_length(directory / f"head_{name}.txt")
        tail = (directory / f"tail_{name}.bin").read_bytes()
        base = total - len(tail)
        eocd = tail.rfind(b"PK\x05\x06")
        _sig, _d, _cd, _n1, n_total, cd_size, cd_off, _c = struct.unpack_from("<IHHHHIIH", tail, eocd)
        zip64 = int(base + eocd != cd_off + cd_size)
        if zip64 and tail[eocd - 76 : eocd - 72] != b"PK\x06\x06":
            raise SystemExit(f"{name}: unexplained gap before EOCD")
        cd_tail = tail[cd_off - base :]
        arch_rows.append([name, total, n_total, cd_off, len(cd_tail), zip64, hashlib.sha256(cd_tail).hexdigest()])
        pos, members = cd_off - base, []
        for _ in range(n_total):
            f = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
            member = tail[pos + 46 : pos + 46 + f[10]].decode("cp437")
            members.append((member, f[7], f[8], f[9], f[16]))
            pos += 46 + f[10] + f[11] + f[12]
        imgs = sorted((x for x in members if x[0].endswith(".img")), key=lambda x: x[0])
        n = len(imgs)
        for k in range(m.FRAMES_PER_SERIES):
            index = n * (2 * k + 1) // 6
            member, crc, csize, usize, lho = imgs[index]
            selected.append([name, member, index, n, lho, 30 + len(member) + csize, csize, usize, f"{crc:08x}"])
            probes.append([name, member, m.member_url(name), lho, lho + 30 + len(member) + 4095])
    write(directory / "archives.tsv", m.ARCHIVE_FIELDS, arch_rows)
    write(directory / "selected.tsv", m.FRAME_FIELDS[:9], selected)
    write(directory / "header_ranges.tsv", ["archive", "member", "url", "start", "end"], probes)
    print(f"archives={len(arch_rows)} selected_frames={len(selected)}")


def frames(directory: Path) -> None:
    with (directory / "selected.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    out = []
    for row in rows:
        blob = (directory / f"hdr_{row['archive']}__{row['member']}.bin").read_bytes()
        name_len, extra_len = struct.unpack_from("<HH", blob, 26)
        if blob[30 : 30 + name_len].decode("cp437") != row["member"] or extra_len != 0:
            raise SystemExit(f"{row['member']}: local header name/extra differs from the range assumption")
        header = zlib.decompressobj(-15).decompress(blob[30 + name_len :])[: m.HEADER_BYTES]
        phi = re.search(rb"\nPHI=([^;]+);", header)
        if len(header) != m.HEADER_BYTES or not phi:
            raise SystemExit(f"{row['member']}: could not inflate the SMV header")
        out.append([row[k] for k in m.FRAME_FIELDS[:9]] + [phi.group(1).decode(), hashlib.sha256(header).hexdigest()])
    write(directory / "frames.tsv", m.FRAME_FIELDS, out)
    print(f"frames={len(out)}")


def write(path: Path, fields: list[str], rows: list[list[object]]) -> None:
    path.write_text("\t".join(fields) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("archives", "frames"):
        raise SystemExit(__doc__)
    {"archives": archives, "frames": frames}[sys.argv[1]](Path(sys.argv[2]))
