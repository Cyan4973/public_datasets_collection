#!/usr/bin/env python3
"""Range-oriented ZIP structure helpers for the Monado SLAM Valve Index recipe.

Pure standard library. Network I/O is done by curl in the shell scripts; this
module only parses bytes that curl already fetched:

* ``tail``   parse the EOCD (and ZIP64 locator/record) from an archive tail
* ``find``   scan a central-directory window for one exact member name
* ``local``  parse a local file header and report the exact member byte range
* ``member`` validate a fetched "local header + stored member" range, check
             the CRC-32 and write the bare member payload
* ``check206`` require the final (post-redirect) response of a range GET to
             be HTTP 206 with the exact requested Content-Range and object size

Split (multi-disk) archives are supported for member lookup: the central
directory entry's disk-number-start selects the part file and the local-header
offset is relative to the start of that part.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from pathlib import Path

EOCD_SIG = b"PK\x05\x06"
ZIP64_LOCATOR_SIG = b"PK\x06\x07"
ZIP64_EOCD_SIG = b"PK\x06\x06"
CENTRAL_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"


class ZipError(Exception):
    pass


def parse_tail(tail: bytes, archive_size: int) -> dict:
    """Parse EOCD + optional ZIP64 records from the last bytes of a ZIP."""
    base = archive_size - len(tail)
    if base < 0:
        raise ZipError("tail longer than archive")
    pos = tail.rfind(EOCD_SIG)
    if pos < 0 or pos + 22 > len(tail):
        raise ZipError("EOCD signature not found in tail")
    (_, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, comment_len) = struct.unpack_from(
        "<4s4H2IH", tail, pos
    )
    if pos + 22 + comment_len != len(tail):
        raise ZipError("EOCD comment does not end at the archive end")
    info = {
        "archive_size": archive_size,
        "eocd_offset": base + pos,
        "zip64": False,
        "disk": disk,
        "cd_disk": cd_disk,
        "disk_entries": disk_entries,
        "total_entries": total_entries,
        "cd_size": cd_size,
        "cd_offset": cd_offset,
        "total_disks": disk + 1,
    }
    cd_end = base + pos
    loc = pos - 20
    if loc >= 0 and tail[loc : loc + 4] == ZIP64_LOCATOR_SIG:
        _, z64_disk, z64_offset, total_disks = struct.unpack_from("<4sIQI", tail, loc)
        rel = z64_offset - base
        if rel < 0 or rel + 56 > len(tail) or tail[rel : rel + 4] != ZIP64_EOCD_SIG:
            raise ZipError("ZIP64 EOCD record not inside the fetched tail")
        (_, _rec_size, _vm, _vn, disk64, cd_disk64, disk_entries64, total_entries64, cd_size64, cd_offset64) = (
            struct.unpack_from("<4sQ2H2I4Q", tail, rel)
        )
        info.update(
            zip64=True,
            disk=disk64,
            cd_disk=cd_disk64,
            disk_entries=disk_entries64,
            total_entries=total_entries64,
            cd_size=cd_size64,
            cd_offset=cd_offset64,
            total_disks=total_disks,
            zip64_eocd_offset=z64_offset,
            zip64_eocd_disk=z64_disk,
        )
        cd_end = z64_offset
    elif 0xFFFF in (disk_entries, total_entries) or 0xFFFFFFFF in (cd_size, cd_offset):
        raise ZipError("EOCD needs ZIP64 but no ZIP64 locator precedes it")
    if info["cd_disk"] != info["disk"]:
        raise ZipError("central directory does not start on the last disk")
    if info["cd_offset"] + info["cd_size"] != cd_end:
        raise ZipError("central directory is not contiguous with the end records")
    return info


def _apply_zip64_extra(extra: bytes, usz: int, csz: int, lho: int, disk: int) -> tuple[int, int, int, int]:
    j = 0
    while j + 4 <= len(extra):
        header_id, size = struct.unpack_from("<2H", extra, j)
        if j + 4 + size > len(extra):
            raise ZipError("truncated extra field")
        if header_id == 0x0001:
            k = j + 4
            end = k + size
            if usz == 0xFFFFFFFF:
                if k + 8 > end:
                    raise ZipError("ZIP64 extra lacks uncompressed size")
                usz = struct.unpack_from("<Q", extra, k)[0]
                k += 8
            if csz == 0xFFFFFFFF:
                if k + 8 > end:
                    raise ZipError("ZIP64 extra lacks compressed size")
                csz = struct.unpack_from("<Q", extra, k)[0]
                k += 8
            if lho == 0xFFFFFFFF:
                if k + 8 > end:
                    raise ZipError("ZIP64 extra lacks local header offset")
                lho = struct.unpack_from("<Q", extra, k)[0]
                k += 8
            if disk == 0xFFFF:
                if k + 4 > end:
                    raise ZipError("ZIP64 extra lacks disk number")
                disk = struct.unpack_from("<I", extra, k)[0]
                k += 4
        j += 4 + size
    if 0xFFFFFFFF in (usz, csz, lho) or disk == 0xFFFF:
        raise ZipError("ZIP64 placeholder without matching ZIP64 extra value")
    return usz, csz, lho, disk


def parse_central_entry(buf: bytes, i: int) -> tuple[dict, int]:
    if buf[i : i + 4] != CENTRAL_SIG or i + 46 > len(buf):
        raise ZipError("not a central directory entry")
    (_, _vm, _vn, flags, method, mtime, mdate, crc, csz, usz, nl, el, cl, disk, _ia, _ea, lho) = struct.unpack_from(
        "<4s6H3I5H2I", buf, i
    )
    end = i + 46 + nl + el + cl
    if end > len(buf):
        raise ZipError("central directory entry truncated")
    raw_name = buf[i + 46 : i + 46 + nl]
    name = raw_name.decode("utf-8" if flags & 0x800 else "cp437")
    usz, csz, lho, disk = _apply_zip64_extra(buf[i + 46 + nl : i + 46 + nl + el], usz, csz, lho, disk)
    return (
        {
            "name": name,
            "flags": flags,
            "method": method,
            "crc32": crc,
            "compressed_size": csz,
            "uncompressed_size": usz,
            "disk": disk,
            "local_header_offset": lho,
            "dos_time": mtime,
            "dos_date": mdate,
        },
        end,
    )


def scan_central_window(buf: bytes) -> list[dict]:
    """Parse every complete central entry in a window that may start mid-entry.

    The scan resynchronises on the first signature and then walks entries
    back-to-back; a chain of consecutive valid entries is required so a stray
    signature inside a name cannot produce a false hit.
    """
    entries: list[dict] = []
    i = buf.find(CENTRAL_SIG)
    while i >= 0:
        try:
            entry, nxt = parse_central_entry(buf, i)
        except (ZipError, UnicodeDecodeError, struct.error):
            i = buf.find(CENTRAL_SIG, i + 1)
            continue
        entries.append(entry)
        if nxt + 4 <= len(buf) and buf[nxt : nxt + 4] == CENTRAL_SIG:
            i = nxt
        else:
            i = buf.find(CENTRAL_SIG, nxt)
    return entries


def parse_local_header(buf: bytes) -> dict:
    if len(buf) < 30 or buf[:4] != LOCAL_SIG:
        raise ZipError("local file header signature PK\\x03\\x04 missing")
    (_, _ver, flags, method, _mt, _md, crc, csz, usz, nl, el) = struct.unpack_from("<4s5H3I2H", buf, 0)
    if 30 + nl + el > len(buf):
        raise ZipError("local header truncated")
    name = buf[30 : 30 + nl].decode("utf-8" if flags & 0x800 else "cp437")
    extra = buf[30 + nl : 30 + nl + el]
    if usz == 0xFFFFFFFF or csz == 0xFFFFFFFF:
        j = 0
        while j + 4 <= len(extra):
            header_id, size = struct.unpack_from("<2H", extra, j)
            if header_id == 0x0001 and size >= 16:
                usz, csz = struct.unpack_from("<2Q", extra, j + 4)
                break
            j += 4 + size
        else:
            raise ZipError("local ZIP64 placeholder without ZIP64 extra")
    return {
        "name": name,
        "flags": flags,
        "method": method,
        "crc32": crc,
        "compressed_size": csz,
        "uncompressed_size": usz,
        "header_bytes": 30 + nl + el,
    }


def extract_member(range_path: Path, out_path: Path, expect: dict) -> dict:
    """Validate a fetched local-header+data range and write the member payload."""
    header_bytes = int(expect["local_header_bytes"])
    csz = int(expect["compressed_size"])
    usz = int(expect["uncompressed_size"])
    crc_expected = int(expect["crc32"], 16)
    method_expected = int(expect["method"])
    size = range_path.stat().st_size
    if size != header_bytes + csz:
        raise ZipError(f"range size {size} != local header {header_bytes} + member {csz}")
    with range_path.open("rb") as handle:
        header = parse_local_header(handle.read(header_bytes))
        if header["name"] != expect["member"]:
            raise ZipError(f"local header names {header['name']!r}, expected {expect['member']!r}")
        if header["header_bytes"] != header_bytes:
            raise ZipError("local header length changed")
        if header["method"] != method_expected:
            raise ZipError(f"compression method {header['method']} != pinned {method_expected}")
        if not header["flags"] & 0x8:
            if header["crc32"] != crc_expected:
                raise ZipError("local header CRC-32 disagrees with the central directory")
            if (header["compressed_size"], header["uncompressed_size"]) != (csz, usz):
                raise ZipError("local header sizes disagree with the central directory")
        crc = 0
        written = 0
        tmp = out_path.with_name(out_path.name + ".tmp")
        with tmp.open("wb") as out:
            if method_expected == 0:
                if csz != usz:
                    raise ZipError("stored member with csz != usz")
                remaining = csz
                while remaining:
                    block = handle.read(min(remaining, 8 << 20))
                    if not block:
                        raise ZipError("short read in member payload")
                    remaining -= len(block)
                    crc = zlib.crc32(block, crc)
                    written += len(block)
                    out.write(block)
            elif method_expected == 8:
                inflater = zlib.decompressobj(-15)
                remaining = csz
                while remaining:
                    block = handle.read(min(remaining, 8 << 20))
                    if not block:
                        raise ZipError("short read in member payload")
                    remaining -= len(block)
                    data = inflater.decompress(block)
                    crc = zlib.crc32(data, crc)
                    written += len(data)
                    out.write(data)
                data = inflater.flush()
                crc = zlib.crc32(data, crc)
                written += len(data)
                out.write(data)
                if not inflater.eof or inflater.unused_data:
                    raise ZipError("DEFLATE stream did not end at the member boundary")
            else:
                raise ZipError(f"unsupported compression method {method_expected}")
    crc &= 0xFFFFFFFF
    if written != usz or crc != crc_expected:
        tmp.unlink(missing_ok=True)
        raise ZipError(f"member payload mismatch: bytes={written}/{usz} crc32={crc:08x}/{crc_expected:08x}")
    tmp.replace(out_path)
    return {"member": expect["member"], "bytes": written, "crc32": f"{crc:08x}", "method": method_expected}


def check_partial_response(headers_text: str, start: int, end: int, total: int) -> None:
    """The final response of a (possibly redirected) range GET must be an exact 206."""
    blocks = [b for b in re.split(r"(?=^HTTP/)", headers_text, flags=re.MULTILINE) if b.strip()]
    if not blocks:
        raise ZipError("no HTTP response headers recorded")
    final = blocks[-1]
    status = re.match(r"HTTP/\S+\s+(\d+)", final)
    if not status or status.group(1) != "206":
        raise ZipError(f"expected HTTP 206, got {status.group(1) if status else 'nothing'}")
    content_range = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, re.IGNORECASE | re.MULTILINE)
    if not content_range:
        raise ZipError("206 response without Content-Range")
    got = tuple(map(int, content_range.groups()))
    if got != (start, end, total):
        raise ZipError(f"Content-Range {got} != requested {(start, end, total)}")


def _cmd_check206(args: argparse.Namespace) -> None:
    try:
        check_partial_response(Path(args.headers).read_text(encoding="iso-8859-1"), args.start, args.end, args.total)
    except ZipError as exc:
        raise SystemExit(f"FATAL range response: {exc}")


def _cmd_tail(args: argparse.Namespace) -> None:
    info = parse_tail(Path(args.tail).read_bytes(), args.archive_size)
    print(json.dumps(info, sort_keys=True))


def _cmd_find(args: argparse.Namespace) -> None:
    buf = Path(args.window).read_bytes()
    entries = scan_central_window(buf)
    hits = [e for e in entries if e["name"] == args.member]
    if len(hits) > 1:
        raise SystemExit(f"member {args.member!r} appears {len(hits)} times in the window")
    siblings = sorted(e["name"].rsplit("/", 1)[-1] for e in entries if e["name"].startswith(args.member.rsplit("/", 1)[0] + "/"))
    result = {"parsed_entries": len(entries), "found": bool(hits), "siblings": siblings}
    if hits:
        result["entry"] = hits[0]
    print(json.dumps(result, sort_keys=True))


def _cmd_local(args: argparse.Namespace) -> None:
    print(json.dumps(parse_local_header(Path(args.header).read_bytes()), sort_keys=True))


def _cmd_member(args: argparse.Namespace) -> None:
    expect = json.loads(args.expect)
    try:
        result = extract_member(Path(args.range), Path(args.out), expect)
    except ZipError as exc:
        raise SystemExit(f"FATAL member validation: {exc}")
    print(json.dumps(result, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tail")
    p.add_argument("tail")
    p.add_argument("archive_size", type=int)
    p.set_defaults(func=_cmd_tail)
    p = sub.add_parser("find")
    p.add_argument("window")
    p.add_argument("member")
    p.set_defaults(func=_cmd_find)
    p = sub.add_parser("local")
    p.add_argument("header")
    p.set_defaults(func=_cmd_local)
    p = sub.add_parser("member")
    p.add_argument("range")
    p.add_argument("out")
    p.add_argument("expect", help="JSON with member, local_header_bytes, compressed_size, uncompressed_size, crc32, method")
    p.set_defaults(func=_cmd_member)
    p = sub.add_parser("check206")
    p.add_argument("headers")
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p.add_argument("total", type=int)
    p.set_defaults(func=_cmd_check206)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
