#!/usr/bin/env python3
"""Re-derive scripts/frames.tsv from zip tail ranges fetched by discover.sh.

Each tail must contain the zip's End Of Central Directory record and the whole
central directory. Output (stdout): the pinned frame table. The duplicate
session zip (20180821_160000.zip) is parsed only to prove that every one of its
members is byte-identical (same name and CRC32) to a member of
20180821_155204.zip, which is why it is excluded.

Commands:
  sessions             print "<zip_name> <zip_size>" for every zip to fetch a tail of
  table --tails DIR    print the frame table
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from flir import DUPLICATE_ZIP, SESSIONS, STRIDE, TSV_COLUMNS  # noqa: E402


def parse_cd(tail: bytes, zip_size: int) -> list[dict[str, object]]:
    base = zip_size - len(tail)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0:
        raise SystemExit("EOCD not found in tail")
    _sig, disk, cd_disk, n_disk, n_total, cd_size, cd_off, _cl = struct.unpack_from("<IHHHHIIH", tail, pos)
    if disk or cd_disk or n_disk != n_total or cd_off == 0xFFFFFFFF:
        raise SystemExit("multi-disk or zip64 archive not supported")
    if cd_off < base or cd_off + cd_size != base + pos:
        raise SystemExit("tail does not contain the full central directory")
    p = cd_off - base
    entries = []
    for _ in range(n_total):
        (sig, _vm, _vn, flags, method, _mt, _md, crc, csize, usize, nlen, elen, clen,
         _ds, _ia, _ea, lho) = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, p)
        if sig != 0x02014B50:
            raise SystemExit("bad central directory entry")
        name = tail[p + 46:p + 46 + nlen].decode("utf-8")
        entries.append({"name": name, "flags": flags, "method": method, "crc": crc,
                        "csize": csize, "usize": usize, "lho": lho})
        p += 46 + nlen + elen + clen
    entries.sort(key=lambda e: int(e["lho"]))  # type: ignore[arg-type]
    for i, e in enumerate(entries):
        e["range_end"] = (int(entries[i + 1]["lho"]) if i + 1 < len(entries) else cd_off) - 1
    return entries


def frames_of(entries: list[dict[str, object]], session: str) -> list[dict[str, object]]:
    out = []
    for e in entries:
        name = str(e["name"])
        if name.startswith("__MACOSX/") or not name.endswith(".tiff"):
            continue
        if not name.startswith(session + "/"):
            raise SystemExit(f"unexpected member path {name}")
        out.append(e)
    out.sort(key=lambda e: str(e["name"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sessions")
    t = sub.add_parser("table")
    t.add_argument("--tails", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "sessions":
        for session, meta in SESSIONS.items():
            print(f"{session}.zip {meta['zip_size']}")
        print(f"{DUPLICATE_ZIP['name']} {DUPLICATE_ZIP['zip_size']}")
        return
    print("\t".join(TSV_COLUMNS))
    by_session = {}
    for session, meta in SESSIONS.items():
        tail = (args.tails / f"{session}.zip.tail").read_bytes()
        frames = frames_of(parse_cd(tail, int(meta["zip_size"])), session)
        by_session[session] = {Path(str(e["name"])).name: e["crc"] for e in frames}
        for idx, e in enumerate(frames):
            if e["method"] != 8:
                raise SystemExit(f"{e['name']}: not deflated")
            print("\t".join(str(v) for v in [
                session, Path(str(e["name"])).name, 1 if idx % STRIDE == 0 else 0,
                meta["zip_size"], e["lho"], e["range_end"], e["csize"], e["usize"], f"{int(e['crc']):08x}",
            ]))
    dup = DUPLICATE_ZIP
    tail = (args.tails / str(dup["name"])).with_suffix(".zip.tail").read_bytes()
    dup_frames = frames_of(parse_cd(tail, int(dup["zip_size"])), str(dup["session"]))
    parent = by_session[str(dup["duplicate_of"])]
    same = sum(1 for e in dup_frames if parent.get(Path(str(e["name"])).name) == e["crc"])
    print(f"duplicate check: {same}/{len(dup_frames)} members of {dup['name']} are identical "
          f"(name + CRC32) to members of {dup['duplicate_of']}.zip", file=sys.stderr)
    if same != len(dup_frames):
        raise SystemExit("duplicate zip is no longer a strict subset; revisit the exclusion")


if __name__ == "__main__":
    main()
