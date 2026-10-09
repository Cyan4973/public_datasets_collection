#!/usr/bin/env python3
"""Validation helpers for the `nodes/time` zarr array inside a tskit .trees.tsz.

A .trees.tsz file from Wohns et al. (2022) is a zarr v2 ZipStore written with
ZIP_STORED members. The recipe only ever holds two local artefacts per arm:

  <arm>.cd.bin           bytes [cd_offset, file_size) = central directory + EOCD
  <arm>.nodes_time.bin   bytes [range_start, range_end] = local header +
                         `nodes/time/.zarray`, then local header +
                         `nodes/time/0` (the single blosc chunk)

Subcommands (used by download.sh; build.sh imports the functions):
  check-headers HEADERS START END TOTAL
  validate-cd   RESOURCES_TSV ARM CD_FILE
  validate-range RESOURCES_TSV ARM RANGE_FILE
"""
from __future__ import annotations

import csv
import json
import re
import struct
import sys
import zlib
from pathlib import Path

ZARRAY_NAME = "nodes/time/.zarray"
CHUNK_NAME = "nodes/time/0"
EXPECTED_COMPRESSOR = {"id": "blosc", "cname": "zstd", "shuffle": 1}


class TszError(ValueError):
    pass


def load_resources(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    out = {}
    for r in rows:
        for k, v in r.items():
            if k not in {"arm", "file_key", "file_md5", "zarray_crc32", "chunk_crc32"}:
                r[k] = int(v)
        out[r["arm"]] = r
    return out


def check_headers(headers: str, start: int, end: int, total: int) -> None:
    responses = re.split(r"(?=^HTTP/)", headers, flags=re.MULTILINE)
    final = next((part for part in reversed(responses) if part.strip()), "")
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    cr = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if not status or int(status.group(1)) != 206 or not cr:
        raise TszError(f"server did not answer 206 with Content-Range (status={status.group(1) if status else None})")
    if tuple(map(int, cr.groups())) != (start, end, total):
        raise TszError(f"unexpected Content-Range {cr.groups()} != {(start, end, total)}")


def parse_cd(cd: bytes, row: dict) -> dict[str, dict]:
    """Parse the fetched CD+EOCD tail and check the pinned nodes/time members."""
    if len(cd) != row["file_size"] - row["cd_offset"]:
        raise TszError(f"CD tail is {len(cd)} bytes, expected {row['file_size'] - row['cd_offset']}")
    if len(cd) != row["cd_size"] + 22 or cd[-22:-18] != b"PK\x05\x06":
        raise TszError("EOCD record not at the end of the file (unexpected comment or ZIP64)")
    _, disk, cddisk, n_disk, n, cdsize, cdoff, clen = struct.unpack_from("<4s4H2IH", cd, len(cd) - 22)
    if (disk, cddisk, clen) != (0, 0, 0) or n_disk != n or n != row["cd_entries"]:
        raise TszError("EOCD disk/entry/comment fields changed")
    if cdsize != row["cd_size"] or cdoff != row["cd_offset"]:
        raise TszError("EOCD central-directory offset/size changed")
    entries: dict[str, dict] = {}
    p = 0
    for _ in range(n):
        f = struct.unpack_from("<4s6H3I5H2I", cd, p)
        if f[0] != b"PK\x01\x02":
            raise TszError(f"bad central-directory signature at {p}")
        nl, el, cl = f[10], f[11], f[12]
        name = cd[p + 46 : p + 46 + nl].decode("utf-8")
        if name in entries and name != ".zattrs":
            # zarr's ZipStore appends a fresh root .zattrs on every attribute
            # update (4 copies per file here); any other duplicate is fatal.
            raise TszError(f"duplicate member {name}")
        entries[name] = {"flags": f[3], "method": f[4], "crc32": f[7], "csize": f[8], "usize": f[9], "lho": f[16]}
        p += 46 + nl + el + cl
    if p != cdsize:
        raise TszError("central directory length mismatch")
    time_members = sorted(k for k in entries if k.startswith("nodes/time/"))
    if time_members != [ZARRAY_NAME, CHUNK_NAME]:
        raise TszError(f"nodes/time is not a single-chunk array: {time_members}")
    za, ch = entries[ZARRAY_NAME], entries[CHUNK_NAME]
    for name, e, off_key, size_key, crc_key in (
        (ZARRAY_NAME, za, "zarray_offset", "zarray_size", "zarray_crc32"),
        (CHUNK_NAME, ch, "chunk_offset", "chunk_size", "chunk_crc32"),
    ):
        if e["method"] != 0 or e["flags"] & 0x01:
            raise TszError(f"{name}: not a plain stored member (method={e['method']} flags={e['flags']})")
        if e["csize"] != e["usize"] or e["csize"] != row[size_key]:
            raise TszError(f"{name}: size {e['csize']}/{e['usize']} != pinned {row[size_key]}")
        if e["lho"] != row[off_key] or f"{e['crc32']:08x}" != row[crc_key]:
            raise TszError(f"{name}: offset/CRC32 changed")
    return entries


def _local_member(buf: bytes, pos: int, name: str, size: int, crc_hex: str) -> tuple[bytes, int]:
    if buf[pos : pos + 4] != b"PK\x03\x04":
        raise TszError(f"{name}: missing local header signature")
    _, _, flags, method, _, _, crc, csize, usize, nl, el = struct.unpack_from("<4s5H3I2H", buf, pos)
    got = buf[pos + 30 : pos + 30 + nl].decode("utf-8")
    if got != name or method != 0 or flags & 0x08:
        raise TszError(f"local header mismatch: name={got!r} method={method} flags={flags}")
    if (csize, usize) != (size, size) or f"{crc:08x}" != crc_hex:
        raise TszError(f"{name}: local header size/CRC differs from central directory pin")
    start = pos + 30 + nl + el
    data = buf[start : start + size]
    if len(data) != size:
        raise TszError(f"{name}: truncated member data")
    if f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != crc_hex:
        raise TszError(f"{name}: CRC32 mismatch")
    return data, start + size


def validate_zarray(meta: dict) -> int:
    shape, chunks = meta.get("shape"), meta.get("chunks")
    comp = meta.get("compressor") or {}
    if meta.get("zarr_format") != 2 or meta.get("dtype") != "<f8" or meta.get("order") != "C":
        raise TszError(f"unexpected zarr format/dtype/order: {meta}")
    if meta.get("filters") not in (None, []):
        raise TszError(f"unexpected zarr filters {meta.get('filters')}")
    if not (isinstance(shape, list) and len(shape) == 1 and shape == chunks and shape[0] > 0):
        raise TszError(f"nodes/time is not a single-chunk 1-D array: shape={shape} chunks={chunks}")
    if any(comp.get(k) != v for k, v in EXPECTED_COMPRESSOR.items()):
        raise TszError(f"unexpected compressor {comp}")
    return int(shape[0])


def parse_range(buf: bytes, row: dict) -> tuple[dict, bytes]:
    """Return (zarray metadata, blosc chunk frame) from the fetched member range."""
    if len(buf) != row["range_end"] - row["range_start"] + 1:
        raise TszError(f"range file is {len(buf)} bytes, expected {row['range_end'] - row['range_start'] + 1}")
    zbytes, pos = _local_member(buf, 0, ZARRAY_NAME, row["zarray_size"], row["zarray_crc32"])
    if row["range_start"] + pos != row["chunk_offset"]:
        raise TszError("nodes/time/0 local header is not adjacent to nodes/time/.zarray")
    chunk, end = _local_member(buf, pos, CHUNK_NAME, row["chunk_size"], row["chunk_crc32"])
    if end != len(buf):
        raise TszError("range has bytes after the chunk member")
    meta = json.loads(zbytes.decode("utf-8"))
    n = validate_zarray(meta)
    if len(chunk) < 16:
        raise TszError("chunk shorter than a blosc header")
    version, _, flags, typesize, nbytes, blocksize, cbytes = struct.unpack_from("<BBBBiii", chunk, 0)
    if version != 2 or typesize != 8 or flags & 0x04 or flags >> 5 != 4 or not flags & 0x01:
        raise TszError(f"unexpected blosc header version={version} flags=0x{flags:02x} typesize={typesize}")
    if nbytes != n * 8 or cbytes != len(chunk):
        raise TszError(f"blosc nbytes={nbytes} cbytes={cbytes} disagree with shape {n} / member size {len(chunk)}")
    return meta, chunk


def main(argv: list[str]) -> None:
    try:
        if argv[:1] == ["check-headers"] and len(argv) == 5:
            check_headers(Path(argv[1]).read_text(encoding="iso-8859-1"), int(argv[2]), int(argv[3]), int(argv[4]))
            print("range_headers=ok")
        elif argv[:1] == ["validate-cd"] and len(argv) == 4:
            row = load_resources(Path(argv[1]))[argv[2]]
            parse_cd(Path(argv[3]).read_bytes(), row)
            print(f"cd_validation=ok arm={argv[2]} entries={row['cd_entries']}")
        elif argv[:1] == ["validate-range"] and len(argv) == 4:
            row = load_resources(Path(argv[1]))[argv[2]]
            meta, chunk = parse_range(Path(argv[3]).read_bytes(), row)
            print(f"range_validation=ok arm={argv[2]} nodes={meta['shape'][0]} chunk_bytes={len(chunk)} "
                  f"crc32={row['chunk_crc32']}")
        else:
            raise SystemExit(__doc__)
    except TszError as exc:
        raise SystemExit(f"FATAL: {exc}")


if __name__ == "__main__":
    main(sys.argv[1:])
