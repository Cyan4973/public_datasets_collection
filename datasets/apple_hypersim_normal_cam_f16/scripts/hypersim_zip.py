#!/usr/bin/env python3
"""Byte-range helpers for the Hypersim scene zips (used by download.sh).

The scene zips (1-16 GB each) store every member uncompressed (method 0), so a
single member can be cut out with HTTP range requests: tail -> end of central
directory (EOCD, plus the zip64 EOCD locator/record when the archive exceeds
4 GiB) -> central directory -> local file header + member bytes.  This module
never touches the network; download.sh does all I/O with curl and calls the
subcommands below on the fetched pieces.

Subcommands
  eocd    <tail.bin> <tail_start> <zip_size>
          -> prints "<cd_offset> <cd_size> <entries>"
  find    <cd.bin> <member_name>
          -> prints "<local_header_offset> <compressed_size> <crc32> <name_len>"
  slice   <in> <start> <count> <out>
          -> writes bytes [start, start+count) of <in> (CD already inside the tail)
  extract <slab.bin> <member_name> <size> <crc32> <out>
          -> validates the local header (signature, name, method 0, no
             encryption, consistent sizes/CRC) and the CRC-32 of the member
             bytes, then writes exactly the member bytes to <out>
"""
from __future__ import annotations

import struct
import sys
import zlib

EOCD_SIG = b"PK\x05\x06"
Z64_LOC_SIG = b"PK\x06\x07"
Z64_EOCD_SIG = b"PK\x06\x06"
CD_SIG = 0x02014B50
LFH_SIG = 0x04034B50
M32 = 0xFFFFFFFF
M16 = 0xFFFF


class ZipError(ValueError):
    pass


def parse_eocd(tail: bytes, tail_start: int, zip_size: int) -> tuple[int, int, int]:
    if tail_start + len(tail) != zip_size:
        raise ZipError(f"tail [{tail_start}, {tail_start + len(tail)}) does not end at zip size {zip_size}")
    pos = tail.rfind(EOCD_SIG)
    while pos >= 0:
        comment_len = struct.unpack_from("<H", tail, pos + 20)[0] if pos + 22 <= len(tail) else -1
        if pos + 22 + comment_len == len(tail):
            break
        pos = tail.rfind(EOCD_SIG, 0, pos)
    if pos < 0:
        raise ZipError("end of central directory record not found at end of file")
    (_sig, disk, cd_disk, n_disk, n_total, cd_size, cd_off, _clen) = struct.unpack_from("<IHHHHIIH", tail, pos)
    if disk not in (0, M16) or cd_disk not in (0, M16):
        raise ZipError("multi-disk zip archives are not supported")
    if M32 in (cd_size, cd_off) or M16 in (n_disk, n_total):
        lpos = pos - 20
        if lpos < 0 or tail[lpos:lpos + 4] != Z64_LOC_SIG:
            raise ZipError("zip64 sentinel values without a zip64 EOCD locator")
        _s, z_disk, z_off, z_ndisks = struct.unpack_from("<IIQI", tail, lpos)
        if z_disk != 0 or z_ndisks != 1:
            raise ZipError("multi-disk zip64 archives are not supported")
        rpos = z_off - tail_start
        if rpos < 0 or rpos + 56 > len(tail) or tail[rpos:rpos + 4] != Z64_EOCD_SIG:
            raise ZipError(f"zip64 EOCD record not at offset {z_off} inside the fetched tail")
        (_s, _rsize, _vm, _vn, d1, d2, n_disk, n_total, cd_size, cd_off) = struct.unpack_from("<IQHHIIQQQQ", tail, rpos)
        if d1 or d2:
            raise ZipError("multi-disk zip64 archives are not supported")
        cd_end_limit = z_off
    else:
        cd_end_limit = tail_start + pos
    if n_disk != n_total:
        raise ZipError("entry counts disagree (multi-disk archive?)")
    if cd_off + cd_size != cd_end_limit:
        raise ZipError(f"central directory [{cd_off}, {cd_off + cd_size}) does not end at {cd_end_limit}")
    return cd_off, cd_size, n_total


def iter_cd(cd: bytes):
    pos = 0
    while pos < len(cd):
        if pos + 46 > len(cd):
            raise ZipError("truncated central directory entry")
        (sig, _vm, _vn, flags, method, _t, _d, crc, csize, usize, nlen, elen, clen,
         disk, _ia, _ea, off) = struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, pos)
        if sig != CD_SIG:
            raise ZipError(f"bad central directory signature at {pos}")
        name = cd[pos + 46:pos + 46 + nlen].decode("utf-8")
        extra = cd[pos + 46 + nlen:pos + 46 + nlen + elen]
        if M32 in (csize, usize, off) or disk == M16:
            fields = {}
            epos = 0
            while epos + 4 <= len(extra):
                hid, hlen = struct.unpack_from("<HH", extra, epos)
                if hid == 0x0001:
                    zpos = epos + 4
                    for key, value, width in (("usize", usize, 8), ("csize", csize, 8), ("off", off, 8)):
                        if value == M32:
                            fields[key] = struct.unpack_from("<Q", extra, zpos)[0]
                            zpos += width
                    if zpos > epos + 4 + hlen:
                        raise ZipError(f"zip64 extra field too short for {name}")
                epos += 4 + hlen
            usize = fields.get("usize", usize)
            csize = fields.get("csize", csize)
            off = fields.get("off", off)
            if M32 in (usize, csize, off):
                raise ZipError(f"missing zip64 extra field for {name}")
        yield name, flags, method, crc, csize, usize, off, nlen
        pos += 46 + nlen + elen + clen


def find_member(cd: bytes, member: str) -> tuple[int, int, int, int]:
    hits = [e for e in iter_cd(cd) if e[0] == member]
    if len(hits) != 1:
        raise ZipError(f"member {member!r} found {len(hits)} times in central directory")
    name, flags, method, crc, csize, usize, off, nlen = hits[0]
    if method != 0:
        raise ZipError(f"member {name!r} uses compression method {method}, expected 0 (stored)")
    if flags & 0x0001:
        raise ZipError(f"member {name!r} is encrypted")
    if csize != usize:
        raise ZipError(f"stored member {name!r} has csize {csize} != usize {usize}")
    return off, csize, crc, nlen


def extract(slab: bytes, member: str, size: int, crc: int) -> bytes:
    if len(slab) < 30:
        raise ZipError("slab shorter than a local file header")
    (sig, _vn, flags, method, _t, _d, lcrc, lcsize, lusize, nlen, elen) = struct.unpack_from("<IHHHHHIIIHH", slab, 0)
    if sig != LFH_SIG:
        raise ZipError("local file header signature mismatch")
    name = slab[30:30 + nlen].decode("utf-8", "replace")
    if name != member:
        raise ZipError(f"local header names {name!r}, expected {member!r}")
    if method != 0 or flags & 0x0001:
        raise ZipError(f"local header method {method} flags {flags:#x} (want stored, unencrypted)")
    if not flags & 0x0008:  # sizes/CRC are in the local header unless a data descriptor is used
        if lcrc != crc:
            raise ZipError(f"local header CRC {lcrc:08x} != central directory CRC {crc:08x}")
        if lcsize != M32 and lcsize != size:
            raise ZipError(f"local header size {lcsize} != central directory size {size}")
    start = 30 + nlen + elen
    data = slab[start:start + size]
    if len(data) != size:
        raise ZipError(f"slab holds {len(data)} member bytes, need {size} (local extra length {elen})")
    actual = zlib.crc32(data) & M32
    if actual != crc:
        raise ZipError(f"member CRC-32 {actual:08x} != {crc:08x}")
    return data


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[1]
    try:
        if cmd == "eocd" and len(argv) == 5:
            with open(argv[2], "rb") as handle:
                tail = handle.read()
            print(*parse_eocd(tail, int(argv[3]), int(argv[4])))
        elif cmd == "find" and len(argv) == 4:
            with open(argv[2], "rb") as handle:
                cd = handle.read()
            print(*find_member(cd, argv[3]))
        elif cmd == "slice" and len(argv) == 6:
            with open(argv[2], "rb") as handle:
                blob = handle.read()
            start, count = int(argv[3]), int(argv[4])
            if start < 0 or start + count > len(blob):
                raise ZipError(f"slice [{start}, {start + count}) outside {len(blob)}-byte file")
            with open(argv[5], "wb") as handle:
                handle.write(blob[start:start + count])
        elif cmd == "extract" and len(argv) == 7:
            with open(argv[2], "rb") as handle:
                slab = handle.read()
            data = extract(slab, argv[3], int(argv[4]), int(argv[5]))
            with open(argv[6], "wb") as handle:
                handle.write(data)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except ZipError as exc:
        print(f"zip error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
