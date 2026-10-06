#!/usr/bin/env python3
"""Inspect LUMO exemplary ZIPs from small range-fetched pieces (used by discover.sh).

zipdir  <tail.bin> <zip_size>          -> JSON list of central-directory entries
header  <member_head.bin>              -> JSON schema of the Dat struct, decoded from
                                          the first ~64 KiB of one ZIP member
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import lumo_mat as lm  # noqa: E402


def zipdir(tail_path: str, zip_size: int) -> list[dict]:
    tail = Path(tail_path).read_bytes()
    base = zip_size - len(tail)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit("no EOCD record in tail")
    _sig, _d, _cd, _nh, n, cdsize, cdoff, _cl = struct.unpack_from("<IHHHHIIH", tail, eocd)
    if cdoff == 0xFFFFFFFF or n == 0xFFFF:
        raise SystemExit("zip64 archives are not expected")
    if cdoff < base:
        raise SystemExit("central directory not inside fetched tail")
    pos = cdoff - base
    entries = []
    for _ in range(n):
        f = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
        if f[0] != 0x02014B50:
            raise SystemExit("bad central-directory signature")
        flags, method, crc, csize, usize, nlen, xlen, clen, lho = f[3], f[4], f[7], f[8], f[9], f[10], f[11], f[12], f[16]
        name = tail[pos + 46:pos + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
        entries.append({"name": name, "flags": flags, "method": method, "crc32": f"{crc:08x}",
                        "csize": csize, "usize": usize, "lho": lho})
        pos += 46 + nlen + xlen + clen
    entries.sort(key=lambda e: e["lho"])
    for i, e in enumerate(entries):
        e["range_end"] = (entries[i + 1]["lho"] if i + 1 < len(entries) else cdoff) - 1
    return entries


def header(head_path: str) -> dict:
    blob = Path(head_path).read_bytes()
    f = struct.unpack_from("<4s5H3I2H", blob, 0)
    if f[0] != b"PK\x03\x04":
        raise SystemExit("not a local file header")
    nlen, xlen = f[9], f[10]
    name = blob[30:30 + nlen].decode("cp437")
    mat = zlib.decompressobj(-15).decompress(blob[30 + nlen + xlen:])
    lm.check_header(mat)
    dtype, nbytes, data, _ = lm.read_tag(mat, 128, len(mat))
    if dtype != lm.MI_COMPRESSED:
        raise SystemExit("first top-level element is not miCOMPRESSED")
    inner = zlib.decompressobj().decompress(mat[data:])
    itype, inbytes, idata, _ = lm.read_tag(inner, 0, len(inner))
    node = lm.parse_matrix(inner, idata, idata + inbytes, allow_truncated_payload=True)
    meta = lm.validate_dat(node, None)
    first = struct.unpack_from("<8f", inner, meta["data_offset"])
    return {"member": name, "mat_text": mat[:116].decode("ascii").rstrip(),
            "dat_compressed_bytes": nbytes, "time": meta["time"], "fs_hz": meta["fs_hz"],
            "rows": meta["rows"], "columns": meta["columns"], "names": meta["channel_names"],
            "units": meta["channel_units"], "first_accel01x_values": first}


if __name__ == "__main__":
    if sys.argv[1] == "zipdir":
        print(json.dumps(zipdir(sys.argv[2], int(sys.argv[3])), indent=1))
    elif sys.argv[1] == "header":
        print(json.dumps(header(sys.argv[2])))
    else:
        raise SystemExit(__doc__)
