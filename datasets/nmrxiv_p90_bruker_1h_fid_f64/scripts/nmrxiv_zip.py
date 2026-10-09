#!/usr/bin/env python3
"""Range-access helpers for the nmrXiv P90 project ZIP and Bruker acqus files.

Pure standard library. Network I/O is done by curl in download.sh; this module
only parses bytes that curl already fetched:

  eocd     parse the archive tail, print central-directory offset/size/count
  plan     parse the central directory, write a TSV of every member with its
           exact local byte range [start, end] (start = local header offset,
           end = next local header offset - 1, or CD offset - 1 for the last)
  extract  validate one fetched member range (local header, name, DEFLATE
           stream, optional data descriptor, CRC32, sizes) and write the
           inflated member
  select   parse every fetched acqus and write the selected 1H zg30 FIDs
  selftest build synthetic ZIPs with stdlib zipfile and round-trip them
"""
from __future__ import annotations

import argparse
import io
import json
import re
import struct
import sys
import zlib
from pathlib import Path

EOCD_SIG = b"PK\x05\x06"
CD_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"
DD_SIG = b"PK\x07\x08"
ZIP64_LOCATOR_SIG = b"PK\x06\x07"

FID_BYTES = 524288
FID_VALUES = 65536

# Selection rule for the primary series (all must hold, values from acqus).
SELECT_RULE = {
    "DTYPA": "2",
    "NUC1": "<1H>",
    "PULPROG": "<zg30>",
    "TD": "65536",
    "PARMODE": "0",
    "TOPSPIN": "4.0.5",
    "SOLVENT": "<DMSO>",
    "INSTRUM": "<Avance Neo 600>",
}


def parse_eocd(tail: bytes, tail_offset: int, archive_size: int) -> dict:
    pos = tail.rfind(EOCD_SIG)
    if pos < 0 or pos + 22 > len(tail):
        raise ValueError("no end-of-central-directory record in archive tail")
    _, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = struct.unpack_from(
        "<4s4H2IH", tail, pos
    )
    if tail_offset + pos + 22 + comment_len != archive_size:
        raise ValueError("EOCD comment length does not reach the end of the archive")
    if tail.rfind(ZIP64_LOCATOR_SIG, 0, pos) >= 0 or 0xFFFFFFFF in (cd_size, cd_offset) or n_total == 0xFFFF:
        raise ValueError("ZIP64 archive; this parser handles classic ZIP only")
    if disk != 0 or cd_disk != 0 or n_disk != n_total:
        raise ValueError("multi-disk archive")
    if cd_offset + cd_size != tail_offset + pos:
        raise ValueError("central directory does not end at the EOCD record")
    return {"cd_offset": cd_offset, "cd_size": cd_size, "entries": n_total}


def parse_cd(cd: bytes) -> list[dict]:
    entries = []
    pos = 0
    while pos < len(cd):
        if cd[pos : pos + 4] != CD_SIG:
            raise ValueError(f"bad central-directory signature at {pos}")
        f = struct.unpack_from("<4s6H3I5H2I", cd, pos)
        flags, method, crc, csize, usize = f[3], f[4], f[7], f[8], f[9]
        name_len, extra_len, comment_len, local_offset = f[10], f[11], f[12], f[16]
        raw_name = cd[pos + 46 : pos + 46 + name_len]
        name = raw_name.decode("utf-8" if flags & 0x800 else "cp437")
        if 0xFFFFFFFF in (csize, usize, local_offset):
            raise ValueError(f"ZIP64 member {name!r}")
        entries.append(
            {
                "name": name,
                "flags": flags,
                "method": method,
                "crc32": crc,
                "csize": csize,
                "usize": usize,
                "offset": local_offset,
            }
        )
        pos += 46 + name_len + extra_len + comment_len
    if pos != len(cd):
        raise ValueError("central directory overruns its declared size")
    return entries


def assign_ranges(entries: list[dict], cd_offset: int) -> None:
    ordered = sorted(entries, key=lambda e: e["offset"])
    for i, entry in enumerate(ordered):
        nxt = ordered[i + 1]["offset"] if i + 1 < len(ordered) else cd_offset
        if nxt <= entry["offset"]:
            raise ValueError(f"overlapping local headers at {entry['offset']}")
        entry["start"] = entry["offset"]
        entry["end"] = nxt - 1
        if entry["end"] - entry["start"] + 1 < 30 + entry["csize"]:
            raise ValueError(f"member {entry['name']!r} range shorter than its compressed size")


def extract_member(payload: bytes, entry: dict) -> bytes:
    """Validate a local record (header + data [+ descriptor]) against the CD entry."""
    if payload[:4] != LOCAL_SIG:
        raise ValueError("range does not start with a local file header")
    f = struct.unpack_from("<4s5H3I2H", payload, 0)
    flags, method, crc, csize, usize, name_len, extra_len = f[2], f[3], f[6], f[7], f[8], f[9], f[10]
    name = payload[30 : 30 + name_len].decode("utf-8" if flags & 0x800 else "cp437")
    if name != entry["name"]:
        raise ValueError(f"local name {name!r} != CD name {entry['name']!r}")
    if method != entry["method"] or flags != entry["flags"]:
        raise ValueError("local method/flags differ from the central directory")
    if not flags & 0x08 and (crc, csize, usize) != (entry["crc32"], entry["csize"], entry["usize"]):
        raise ValueError("local header sizes/CRC differ from the central directory")
    data_start = 30 + name_len + extra_len  # local extra length may differ from the CD one
    data_end = data_start + entry["csize"]
    if data_end > len(payload):
        raise ValueError("member range truncated")
    data = payload[data_start:data_end]
    if method == 8:
        dec = zlib.decompressobj(-zlib.MAX_WBITS)
        out = dec.decompress(data) + dec.flush()
        if not dec.eof or dec.unused_data:
            raise ValueError("DEFLATE stream does not end exactly at the compressed size")
    elif method == 0:
        out = data
    else:
        raise ValueError(f"unsupported compression method {method}")
    if len(out) != entry["usize"]:
        raise ValueError(f"inflated size {len(out)} != {entry['usize']}")
    actual_crc = zlib.crc32(out) & 0xFFFFFFFF
    if actual_crc != entry["crc32"]:
        raise ValueError(f"CRC32 {actual_crc:08x} != CD {entry['crc32']:08x}")
    trailer = payload[data_end:]
    if flags & 0x08:
        body = trailer[4:] if trailer[:4] == DD_SIG else trailer
        if len(body) not in (12, 20):
            raise ValueError(f"unexpected data-descriptor length {len(trailer)}")
        dd_crc = struct.unpack_from("<I", body, 0)[0]
        if len(body) == 12:
            dd_c, dd_u = struct.unpack_from("<2I", body, 4)
        else:
            dd_c, dd_u = struct.unpack_from("<2Q", body, 4)
        if (dd_crc, dd_c, dd_u) != (entry["crc32"], entry["csize"], entry["usize"]):
            raise ValueError("data descriptor disagrees with the central directory")
    elif trailer:
        raise ValueError(f"{len(trailer)} unexpected bytes after member data")
    return out


# ---------------------------------------------------------------- acqus

ACQUS_PARAM = re.compile(r"^##\$([A-Za-z0-9_]+)=\s*(.*)$")


def parse_acqus(text: str) -> dict:
    params: dict[str, str] = {}
    lines = text.splitlines()
    for line in lines:
        m = ACQUS_PARAM.match(line)
        if m:
            params[m.group(1)] = m.group(2).strip()
    title = next((l for l in lines if l.startswith("##TITLE=")), "")
    m = re.search(r"TopSpin\s+([0-9]+(?:\.[0-9]+)*)", title)
    params["TOPSPIN"] = m.group(1) if m else ""
    origin = next((l for l in lines if l.startswith("##ORIGIN=")), "")
    params["ORIGIN"] = origin[len("##ORIGIN=") :].strip()
    return params


def acqus_matches(params: dict) -> bool:
    return all(params.get(key) == value for key, value in SELECT_RULE.items())


def member_dir(name: str) -> str:
    return name.rsplit("/", 1)[0]


def local_relpath(name: str) -> str:
    """Archive member name -> path below downloads/<id>/members/ (drop the UUID root)."""
    parts = [p for p in name.split("/") if p]
    if len(parts) < 3:
        raise ValueError(f"unexpected member path {name!r}")
    for p in parts:
        if p in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._+-]+", p):
            raise ValueError(f"unsafe member path component {p!r}")
    return "/".join(parts[1:])


# ---------------------------------------------------------------- commands


def read_tsv(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        row = dict(zip(head, line.split("\t")))
        for key in ("flags", "method", "crc32", "csize", "usize", "offset", "start", "end"):
            if key in row:
                row[key] = int(row[key], 16) if key == "crc32" else int(row[key])
        rows.append(row)
    return rows


PLAN_COLUMNS = ["name", "flags", "method", "crc32", "csize", "usize", "offset", "start", "end"]


def write_plan(entries: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(PLAN_COLUMNS) + "\n")
        for e in entries:
            vals = [e["name"], e["flags"], e["method"], f"{e['crc32']:08x}", e["csize"], e["usize"], e["offset"], e["start"], e["end"]]
            fh.write("\t".join(str(v) for v in vals) + "\n")


def cmd_eocd(args: argparse.Namespace) -> None:
    tail = Path(args.tail).read_bytes()
    info = parse_eocd(tail, args.archive_size - len(tail), args.archive_size)
    print(f"{info['cd_offset']} {info['cd_size']} {info['entries']}")


def cmd_plan(args: argparse.Namespace) -> None:
    cd = Path(args.cd).read_bytes()
    entries = parse_cd(cd)
    if len(entries) != args.entries:
        raise SystemExit(f"CD entry count {len(entries)} != EOCD {args.entries}")
    assign_ranges(entries, args.cd_offset)
    names = {e["name"] for e in entries}
    if len(names) != len(entries):
        raise SystemExit("duplicate member names")
    write_plan(entries, Path(args.all_out))
    # Candidate experiment directories: a 1D 'fid' with a sibling 'acqus' and no 'acqu2s'/'ser'.
    fid_dirs = sorted(member_dir(n) for n in names if n.endswith("/fid"))
    acqus_rows = []
    excluded = 0
    for d in fid_dirs:
        if f"{d}/acqus" not in names or f"{d}/acqu2s" in names or f"{d}/ser" in names:
            excluded += 1
            continue
        acqus_rows.append(next(e for e in entries if e["name"] == f"{d}/acqus"))
    write_plan(acqus_rows, Path(args.acqus_out))
    print(f"plan entries={len(entries)} fid_dirs={len(fid_dirs)} acqus_candidates={len(acqus_rows)} excluded_non1d={excluded}")


def cmd_extract(args: argparse.Namespace) -> None:
    rows = [r for r in read_tsv(Path(args.plan)) if r["name"] == args.name]
    if len(rows) != 1:
        raise SystemExit(f"member {args.name!r} not in plan")
    entry = rows[0]
    payload = Path(args.range_file).read_bytes()
    if len(payload) != entry["end"] - entry["start"] + 1:
        raise SystemExit(f"range length {len(payload)} != planned {entry['end'] - entry['start'] + 1}")
    out = extract_member(payload, entry)
    dest = Path(args.out)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(out)
    tmp.replace(dest)


def cmd_select(args: argparse.Namespace) -> None:
    members = Path(args.members_dir)
    acqus_rows = read_tsv(Path(args.acqus_plan))
    all_rows = {r["name"]: r for r in read_tsv(Path(args.all_plan))}
    tally: dict[str, int] = {}
    selected = []
    for row in acqus_rows:
        path = members / local_relpath(row["name"])
        params = parse_acqus(path.read_text(encoding="latin-1"))
        key = f"TopSpin={params['TOPSPIN']} SOLVENT={params.get('SOLVENT')} PULPROG={params.get('PULPROG')} NUC1={params.get('NUC1')} DTYPA={params.get('DTYPA')} TD={params.get('TD')}"
        tally[key] = tally.get(key, 0) + 1
        if not acqus_matches(params):
            continue
        if params.get("BYTORDA") not in ("0", "1"):
            raise SystemExit(f"{row['name']}: unexpected BYTORDA {params.get('BYTORDA')!r}")
        bf1 = float(params["BF1"])
        if not 600.0 <= bf1 < 601.0:
            raise SystemExit(f"{row['name']}: BF1 {bf1} outside the 600 MHz instrument")
        fid_name = member_dir(row["name"]) + "/fid"
        fid = all_rows[fid_name]
        if fid["usize"] != FID_BYTES:
            raise SystemExit(f"{fid_name}: size {fid['usize']} != {FID_BYTES}")
        selected.append(fid)
    for key in sorted(tally):
        print(f"acqus_tally {tally[key]:4d}  {key}")
    write_plan(sorted(selected, key=lambda e: e["name"]), Path(args.out))
    print(f"selected_fids={len(selected)}")
    if args.expect is not None and len(selected) != args.expect:
        raise SystemExit(f"selected {len(selected)} FIDs, expected {args.expect}")


def cmd_selftest(_: argparse.Namespace) -> None:
    import random
    import zipfile

    class Unseekable(io.RawIOBase):
        def __init__(self) -> None:
            self.buf = bytearray()

        def writable(self) -> bool:
            return True

        def write(self, b) -> int:
            self.buf += b
            return len(b)

    rng = random.Random(7)
    members = {
        "uuid//S1/10/acqus": b"##TITLE= Parameter file, TopSpin 4.0.5\n##$DTYPA= 2\n",
        "uuid//S1/10/fid": struct.pack("<512d", *[rng.uniform(-1e9, 1e9) for _ in range(512)]),
        "uuid//S1/10/pdata/1/1r": bytes(rng.getrandbits(8) for _ in range(3000)),
        "uuid//S1/11/stored.txt": b"stored member\n" * 10,
    }
    for mode in ("seekable", "streamed"):
        sink = io.BytesIO() if mode == "seekable" else Unseekable()
        with zipfile.ZipFile(sink, "w") as zf:
            for name, data in members.items():
                ctype = zipfile.ZIP_STORED if name.endswith(".txt") else zipfile.ZIP_DEFLATED
                info = zipfile.ZipInfo(name)
                info.compress_type = ctype
                if name.endswith("1r"):
                    info.extra = struct.pack("<HH4s", 0xCAFE, 4, b"abcd")  # nonzero extra field
                zf.writestr(info, data)
        blob = bytes(sink.getvalue() if mode == "seekable" else sink.buf)
        tail = blob[-100:]
        info = parse_eocd(tail, len(blob) - len(tail), len(blob))
        entries = parse_cd(blob[info["cd_offset"] : info["cd_offset"] + info["cd_size"]])
        assert len(entries) == info["entries"] == len(members)
        assign_ranges(entries, info["cd_offset"])
        for e in entries:
            out = extract_member(blob[e["start"] : e["end"] + 1], e)
            assert out == members[e["name"]], e["name"]
            if mode == "streamed" and e["method"] == 8:
                assert e["flags"] & 0x08, "expected a data descriptor in streamed mode"
        # a local extra field that the CD does not carry must be skipped correctly
        e = next(x for x in entries if x["name"].endswith("/fid"))
        rec = blob[e["start"] : e["end"] + 1]
        nl, el = struct.unpack_from("<2H", rec, 26)
        pad = struct.pack("<HH8s", 0xBEEF, 8, b"12345678")
        grown = rec[:26] + struct.pack("<2H", nl, el + len(pad)) + rec[30 : 30 + nl + el] + pad + rec[30 + nl + el :]
        assert extract_member(grown, e) == members[e["name"]]
        # corruption must be detected
        bad = bytearray(blob[e["start"] : e["end"] + 1])
        bad[60] ^= 0xFF
        try:
            extract_member(bytes(bad), e)
        except (ValueError, zlib.error):
            pass
        else:
            raise AssertionError("corrupted member accepted")
        try:
            extract_member(blob[e["start"] : e["end"]], e)
        except ValueError:
            pass
        else:
            raise AssertionError("truncated member accepted")
    p = parse_acqus(
        "##TITLE= Parameter file, TopSpin 4.0.5\n##ORIGIN= Bruker BioSpin GmbH\n"
        "##$BF1= 600.13\n##$BYTORDA= 0\n##$DTYPA= 2\n##$NUC1= <1H>\n##$PARMODE= 0\n"
        "##$PULPROG= <zg30>\n##$TD= 65536\n##$SOLVENT= <DMSO>\n##$INSTRUM= <Avance Neo 600>\n"
    )
    assert acqus_matches(p) and p["BF1"] == "600.13"
    p["PULPROG"] = "<noesyigld1d>"
    assert not acqus_matches(p)
    assert local_relpath("uuid//10043_M03/proton_03/fid") == "10043_M03/proton_03/fid"
    print("selftest ok (seekable + data-descriptor ZIPs, stored/deflated, mismatched local extra, corruption, acqus)")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("eocd")
    p.add_argument("--tail", required=True)
    p.add_argument("--archive-size", type=int, required=True)
    p = sub.add_parser("plan")
    p.add_argument("--cd", required=True)
    p.add_argument("--cd-offset", type=int, required=True)
    p.add_argument("--entries", type=int, required=True)
    p.add_argument("--all-out", required=True)
    p.add_argument("--acqus-out", required=True)
    p = sub.add_parser("extract")
    p.add_argument("--plan", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--range-file", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("select")
    p.add_argument("--members-dir", required=True)
    p.add_argument("--acqus-plan", required=True)
    p.add_argument("--all-plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--expect", type=int)
    sub.add_parser("selftest")
    args = ap.parse_args()
    {"eocd": cmd_eocd, "plan": cmd_plan, "extract": cmd_extract, "select": cmd_select, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    main()
