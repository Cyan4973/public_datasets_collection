#!/usr/bin/env python3
"""Regenerate scripts/pinned_files.tsv from a local copy of the GSE290585
series filelist.txt (documents how the 150 pinned IDATs were resolved).

Selection rule: the first 75 GSM accessions of GSE290585 in ascending
numeric order, each contributing exactly its Grn and Red *.idat.gz.

GEO publishes no checksums for supplementary files. With an optional third
argument (a directory holding already-downloaded IDAT.gz files), a sha256
column is filled from those local files so later runs detect any upstream
replacement; download.sh/build.sh/verify.sh enforce it when present.

Usage: make_pins.py <filelist.txt> <pinned_files.tsv> [<idat_dir>]
"""
from __future__ import annotations

import collections
import hashlib
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^(GSM\d+)_(\d{12})_(R\d\dC\d\d)_(Grn|Red)\.idat\.gz$")
GSM_COUNT = 75


def main() -> int:
    filelist = Path(sys.argv[1])
    output = Path(sys.argv[2])
    by_gsm: dict[str, list[tuple[str, int, str, str, str]]] = collections.defaultdict(list)
    for line in filelist.read_text(encoding="ascii").splitlines():
        parts = line.split("\t")
        if len(parts) != 5 or parts[0] != "File" or parts[4] != "IDAT":
            continue
        match = NAME_RE.match(parts[1])
        if not match:
            raise SystemExit(f"unexpected IDAT name {parts[1]!r}")
        gsm, barcode, position, channel = match.groups()
        by_gsm[gsm].append((parts[1], int(parts[3]), barcode, position, channel))
    bad = {gsm: rows for gsm, rows in by_gsm.items() if sorted(r[4] for r in rows) != ["Grn", "Red"]}
    if bad:
        raise SystemExit(f"GSMs without exactly one Grn and one Red IDAT: {sorted(bad)[:5]}")
    selected = sorted(by_gsm, key=lambda gsm: int(gsm[3:]))[:GSM_COUNT]
    idat_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    header = "gsm\tfile_name\tsize_bytes\tchip_barcode\tarray_position\tchannel"
    lines = [header + ("\tsha256" if idat_dir else "")]
    for gsm in selected:
        for name, size, barcode, position, channel in sorted(by_gsm[gsm], key=lambda r: r[4]):
            line = f"{gsm}\t{name}\t{size}\t{barcode}\t{position}\t{channel}"
            if idat_dir:
                data = (idat_dir / name).read_bytes()
                if len(data) != size:
                    raise SystemExit(f"{name}: local size {len(data)} != listed {size}")
                line += "\t" + hashlib.sha256(data).hexdigest()
            lines.append(line)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
    total = sum(int(line.split("\t")[2]) for line in lines[1:])
    print(f"gsms={len(selected)} files={len(lines) - 1} bytes={total} first={selected[0]} last={selected[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
