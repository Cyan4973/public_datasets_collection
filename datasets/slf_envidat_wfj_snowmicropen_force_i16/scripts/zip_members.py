#!/usr/bin/env python3
"""Download-side helpers for range-fetched members of WFJ_DailySMP raw_data.zip.

Pure standard library. Network I/O stays in download.sh (curl); this script
only parses bytes curl already fetched.

Subcommands:
  cd-check <cd_tail.bin> <members.tsv> <raw_data.csv>
      Parse the end-of-central-directory record and the full central
      directory of raw_data.zip (the tail file holds bytes
      [cd_offset, zip_size) of the archive) and require every pinned member
      to match its central-directory entry exactly (name, method, CRC32,
      sizes, local-header offset). Also re-check the raw_data.csv selection
      flags for every pinned member.
  inflate <range.bin> <out.PNT> <zip_member> <compressed_size> <uncompressed_size> <crc32hex>
      Validate the local file header of one range-fetched member (signature,
      method, name; the data offset is taken from the LOCAL name/extra
      lengths), raw-inflate the deflate stream, and require the exact
      uncompressed size and CRC32 before writing the member file.
"""
from __future__ import annotations

import csv
import os
import struct
import sys
import zlib

ZIP_SIZE = 3134603173
CD_OFFSET = 3132965021
CD_SIZE = 1638130
CD_ENTRIES = 16535


def read_members(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def cd_check(tail_path: str, members_path: str, csv_path: str) -> None:
    tail = open(tail_path, "rb").read()
    if len(tail) != ZIP_SIZE - CD_OFFSET:
        sys.exit(f"cd tail size {len(tail)} != {ZIP_SIZE - CD_OFFSET}")
    eocd = tail[-22:]
    sig, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = struct.unpack("<IHHHHIIH", eocd)
    if sig != 0x06054B50 or comment_len != 0:
        sys.exit("end-of-central-directory record not found at archive end")
    if (disk, cd_disk, n_disk, n_total, cd_size, cd_offset) != (0, 0, CD_ENTRIES, CD_ENTRIES, CD_SIZE, CD_OFFSET):
        sys.exit(f"unexpected EOCD fields {(disk, cd_disk, n_disk, n_total, cd_size, cd_offset)}")
    entries: dict[str, tuple] = {}
    pos = 0
    for _ in range(n_total):
        fixed = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
        if fixed[0] != 0x02014B50:
            sys.exit(f"bad central directory signature at cd+{pos}")
        flags, method, crc, csize, usize = fixed[3], fixed[4], fixed[7], fixed[8], fixed[9]
        name_len, extra_len, comment_len, local_offset = fixed[10], fixed[11], fixed[12], fixed[16]
        name = tail[pos + 46 : pos + 46 + name_len].decode("utf-8")
        entries[name] = (flags, method, crc, csize, usize, local_offset)
        pos += 46 + name_len + extra_len + comment_len
    if pos != CD_SIZE:
        sys.exit(f"central directory parse ended at {pos}, expected {CD_SIZE}")

    selection = {}
    with open(csv_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            selection[row["Path"]] = row
    members = read_members(members_path)
    seen = set()
    for member in members:
        name = member["zip_member"]
        if name in seen:
            sys.exit(f"duplicate pinned member {name}")
        seen.add(name)
        entry = entries.get(name)  # exact, case-sensitive match (.PNT vs .pnt)
        if entry is None:
            sys.exit(f"pinned member missing from central directory: {name}")
        flags, method, crc, csize, usize, local_offset = entry
        expected = (8, int(member["crc32"], 16), int(member["compressed_size"]), int(member["uncompressed_size"]), int(member["local_header_offset"]))
        if (method, crc, csize, usize, local_offset) != expected:
            sys.exit(f"central directory entry changed for {name}: {(method, crc, csize, usize, local_offset)} != {expected}")
        if flags & 0x1:
            sys.exit(f"encrypted member {name}")
        rel = name[len("raw_data/") :]
        row = selection.get(rel)
        if row is None:
            sys.exit(f"pinned member not listed in raw_data.csv Path column: {rel}")
        if not (row["File"].startswith("S36M") and row["BestOfDay"] == "1" and row["Quality"] == "1"):
            sys.exit(f"raw_data.csv flags no longer select {rel}: {row}")
        if row["Date"][:10] != member["profile_date"]:
            sys.exit(f"raw_data.csv date changed for {rel}")
    print(f"cd-check ok entries={n_total} pinned_members={len(members)}")


def inflate(range_path: str, out_path: str, name: str, csize: str, usize: str, crc_hex: str) -> None:
    csize_i, usize_i, crc_i = int(csize), int(usize), int(crc_hex, 16)
    blob = open(range_path, "rb").read()
    if len(blob) < 30:
        sys.exit(f"{name}: truncated range")
    sig, _ver, flags, method, _t, _d, _crc, _cs, _us, name_len, extra_len = struct.unpack_from("<IHHHHHIIIHH", blob, 0)
    if sig != 0x04034B50:
        sys.exit(f"{name}: local file header signature missing")
    if method != 8 or flags & 0x1:
        sys.exit(f"{name}: unexpected local method {method} flags {flags:#x}")
    local_name = blob[30 : 30 + name_len].decode("utf-8")
    if local_name != name:
        sys.exit(f"{name}: local header names {local_name!r}")
    start = 30 + name_len + extra_len
    if len(blob) != start + csize_i:
        sys.exit(f"{name}: range holds {len(blob) - start} compressed bytes, expected {csize_i}")
    inflater = zlib.decompressobj(-15)
    raw = inflater.decompress(blob[start:]) + inflater.flush()
    if not inflater.eof:
        sys.exit(f"{name}: deflate stream incomplete")
    if len(raw) != usize_i:
        sys.exit(f"{name}: inflated {len(raw)} bytes, expected {usize_i}")
    if zlib.crc32(raw) & 0xFFFFFFFF != crc_i:
        sys.exit(f"{name}: CRC32 mismatch")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(raw)
    os.replace(tmp, out_path)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "cd-check" and len(sys.argv) == 5:
        cd_check(*sys.argv[2:])
    elif len(sys.argv) >= 2 and sys.argv[1] == "inflate" and len(sys.argv) == 8:
        inflate(*sys.argv[2:])
    elif len(sys.argv) >= 2 and sys.argv[1] == "crc-ok" and len(sys.argv) == 5:
        data = open(sys.argv[2], "rb").read()
        ok = len(data) == int(sys.argv[3]) and (zlib.crc32(data) & 0xFFFFFFFF) == int(sys.argv[4], 16)
        sys.exit(0 if ok else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
