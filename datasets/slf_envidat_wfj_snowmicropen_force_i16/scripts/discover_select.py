#!/usr/bin/env python3
"""Regenerate members.tsv / excluded_gain10000.tsv (used by discover.sh only).

Subcommands:
  candidates <cd_tail.bin> <raw_data.csv> <out.tsv>
      List S36M BestOfDay=1 Quality=1 rows with their central-directory
      fields (exact, case-sensitive Path match).
  select <candidates.tsv> <prefix_dir> <members_out.tsv> <excluded_out.tsv>
      Inflate the first bytes of each member from its range-fetched prefix,
      read the PNT header, and split by sensor/amplifier range.
"""
from __future__ import annotations

import csv
import struct
import sys
import zlib
from pathlib import Path

CD_OFFSET = 3132965021


def candidates(tail_path: str, csv_path: str, out_path: str) -> None:
    tail = open(tail_path, "rb").read()
    n_total = struct.unpack("<IHHHHIIH", tail[-22:])[4]
    entries, pos = {}, 0
    for _ in range(n_total):
        f = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
        name = tail[pos + 46 : pos + 46 + f[10]].decode("utf-8")
        entries[name] = (f[4], f[7], f[8], f[9], f[16])
        pos += 46 + f[10] + f[11] + f[12]
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["File"].startswith("S36M") and r["BestOfDay"] == "1" and r["Quality"] == "1"]
    with open(out_path, "w", encoding="utf-8") as out:
        for r in sorted(rows, key=lambda r: r["Path"]):
            name = "raw_data/" + r["Path"]
            method, crc, csize, usize, offset = entries[name]
            out.write(f"{name}\t{r['Date'][:10]}\t{r['Quality']}\t{offset}\t{len(name.encode())}\t{csize}\t{usize}\t{crc:08x}\n")


def select(cand_path: str, prefix_dir: str, members_out: str, excluded_out: str) -> None:
    kept, excluded = [], []
    for line in open(cand_path, encoding="utf-8"):
        name, date, quality, offset, name_len, csize, usize, crc = line.rstrip("\n").split("\t")
        blob = (Path(prefix_dir) / (name.replace("/", "__") + ".prefix")).read_bytes()
        sig, *_rest, nl, el = struct.unpack_from("<IHHHHHIIIHH", blob, 0)
        assert sig == 0x04034B50 and blob[30 : 30 + nl].decode() == name
        head = zlib.decompressobj(-15).decompress(blob[30 + nl + el :])[:512]
        conv = struct.unpack_from(">f", head, 10)[0]
        count = struct.unpack_from(">l", head, 358)[0]
        srange, arange = struct.unpack_from(">hh", head, 366)
        serial = head[392:412].split(b"\0")[0].decode("latin-1")
        if (srange, arange) == (5000, 5000):
            kept.append(f"{name}\t{date}\t{quality}\t{offset}\t{name_len}\t{el}\t{csize}\t{usize}\t{crc}\t{count}\t{conv!r}\t{arange}\t{serial}\n")
        else:
            excluded.append(f"{name}\t{date}\t{quality}\t{arange}\t{srange}\t{conv!r}\t{serial}\tamplifier range {arange} pC: force counts on a 2x coarser scale than the kept range-5000 profiles\n")
    with open(members_out, "w", encoding="utf-8") as out:
        out.write("zip_member\tprofile_date\tquality\tlocal_header_offset\tlocal_name_len\tlocal_extra_len\tcompressed_size\tuncompressed_size\tcrc32\tforce_sample_count\tforce_conv_factor\tamplifier_range_pc\tsensor_serial\n")
        out.writelines(kept)
    with open(excluded_out, "w", encoding="utf-8") as out:
        out.write("zip_member\tprofile_date\tquality\tamplifier_range_pc\tsensor_range_pc\tforce_conv_factor\tsensor_serial\treason\n")
        out.writelines(excluded)
    print(f"kept={len(kept)} excluded={len(excluded)}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["candidates"]:
        candidates(*sys.argv[2:5])
    elif sys.argv[1:2] == ["select"]:
        select(*sys.argv[2:6])
    else:
        sys.exit(__doc__)
