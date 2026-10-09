#!/usr/bin/env python3
"""Regenerate resources.tsv (one row per chromosome-arm .trees.tsz file).

Documentation of how the pinned resources were resolved; download.sh does not
run this. Network I/O goes through curl. Usage:

    python3 -I discover.py OUTPUT.tsv

For every modern-sample file `hgdp_tgp_sgdp_chr*_[pq].dated.trees.tsz` in
Zenodo record 5495535 (v1.0.0) it reads the Zenodo API size/md5, range-fetches
the ZIP end-of-central-directory and central directory, locates the
`nodes/time/.zarray` and `nodes/time/0` members (both stored, method 0), reads
the local header of `nodes/time/0` to get its exact extra-field length, and
pins one contiguous byte range covering both members (the .zarray member
immediately precedes the chunk member in every file).
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
import sys

RECORD = 5495535
API = f"https://zenodo.org/api/records/{RECORD}"
FILE_URL = "https://zenodo.org/api/records/5495535/files/{key}/content"
KEY_RE = re.compile(r"^hgdp_tgp_sgdp_chr(\d+)_([pq])\.dated\.trees\.tsz$")
COLUMNS = [
    "arm", "file_key", "file_size", "file_md5", "cd_offset", "cd_size", "cd_entries",
    "zarray_offset", "zarray_size", "zarray_crc32", "chunk_offset", "chunk_size",
    "chunk_crc32", "range_start", "range_end",
]


def curl(url: str, rng: str | None = None) -> bytes:
    cmd = ["curl", "-sSfL", "--max-time", "120", "--retry", "5"]
    if rng:
        cmd += ["-r", rng]
    return subprocess.run(cmd + [url], capture_output=True, check=True).stdout


def main(out_path: str) -> None:
    rec = json.loads(curl(API))
    assert rec["metadata"]["license"]["id"] == "cc-by-4.0"
    rows = []
    for f in rec["files"]:
        m = KEY_RE.match(f["key"])
        if not m:
            raise SystemExit(f"unexpected file in record: {f['key']}")
        key, size = f["key"], int(f["size"])
        url = FILE_URL.format(key=key)
        tail = curl(url, f"{size - 65536}-{size - 1}")
        i = tail.rfind(b"PK\x05\x06")
        _, _, _, _, n, cdsize, cdoff, _ = struct.unpack_from("<4s4H2IH", tail, i)
        base = size - len(tail)
        cd = tail[cdoff - base : cdoff - base + cdsize]
        p, ents = 0, {}
        for _ in range(n):
            f2 = struct.unpack_from("<4s6H3I5H2I", cd, p)
            assert f2[0] == b"PK\x01\x02"
            nl, el, cl = f2[10], f2[11], f2[12]
            name = cd[p + 46 : p + 46 + nl].decode()
            ents[name] = {"method": f2[4], "crc": f2[7], "csize": f2[8], "usize": f2[9], "lho": f2[16]}
            p += 46 + nl + el + cl
        za, ch = ents["nodes/time/.zarray"], ents["nodes/time/0"]
        assert sorted(k for k in ents if k.startswith("nodes/time/")) == ["nodes/time/.zarray", "nodes/time/0"]
        assert za["method"] == ch["method"] == 0 and za["csize"] == za["usize"] and ch["csize"] == ch["usize"]
        lh = curl(url, f"{ch['lho']}-{ch['lho'] + 63}")
        assert lh[:4] == b"PK\x03\x04"
        nl, el = struct.unpack_from("<2H", lh, 26)
        assert lh[30 : 30 + nl] == b"nodes/time/0"
        range_end = ch["lho"] + 30 + nl + el + ch["csize"] - 1
        assert ch["lho"] == za["lho"] + 30 + len("nodes/time/.zarray") + za["csize"], "members not adjacent"
        rows.append({
            "arm": f"chr{m.group(1)}_{m.group(2)}", "file_key": key, "file_size": size,
            "file_md5": f["checksum"].split(":", 1)[1], "cd_offset": cdoff, "cd_size": cdsize,
            "cd_entries": n, "zarray_offset": za["lho"], "zarray_size": za["csize"],
            "zarray_crc32": f"{za['crc']:08x}", "chunk_offset": ch["lho"], "chunk_size": ch["csize"],
            "chunk_crc32": f"{ch['crc']:08x}", "range_start": za["lho"], "range_end": range_end,
        })
        print(rows[-1]["arm"], rows[-1]["chunk_size"], file=sys.stderr, flush=True)
    rows.sort(key=lambda r: (int(r["arm"][3:].split("_")[0]), r["arm"][-1]))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in COLUMNS) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
