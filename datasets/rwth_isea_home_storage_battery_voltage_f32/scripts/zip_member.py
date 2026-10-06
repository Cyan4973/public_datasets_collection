#!/usr/bin/env python3
"""Validate Zenodo record metadata and raw ZIP member spans for the ISEA recipe.

Used by download.sh only. Network I/O stays in curl; this file parses what curl
fetched.

  zip_member.py record <record.json> <selection.tsv> <meta_key> <meta_bytes> <meta_md5>
  zip_member.py member <span_file> <member_name> <span_bytes> <compressed> <uncompressed> <crc32hex>
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import struct
import sys
import zlib
from pathlib import Path

RECORD_ID = 12091223
EXPECTED_HEADER = b"Time,P_in_W,V_in_V,I_in_A,T_Bat_in_C,T_Room_in_C,Interpolated"
LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
LOCAL_SIG = 0x04034B50


def read_selection(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def check_record(record_path: Path, selection_path: Path, meta_key: str, meta_bytes: int, meta_md5: str) -> None:
    text = record_path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("<"):
        raise SystemExit("record response is HTML, not JSON (rate-limit or error page)")
    record = json.loads(text)
    if int(record.get("id") or 0) != RECORD_ID:
        raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
    metadata = record.get("metadata") or {}
    title = html.unescape(re.sub(r"<[^>]+>", " ", str(metadata.get("title", ""))))
    if "home storage systems" not in title.lower() or "capacity estimation" not in title.lower():
        raise SystemExit(f"record title changed: {title!r}")
    license_value = metadata.get("license")
    license_id = license_value.get("id") if isinstance(license_value, dict) else license_value
    if str(license_id or "").lower() != "cc-by-4.0":
        raise SystemExit(f"record license changed: {license_value!r}")
    access = (record.get("access") or {}).get("record") if isinstance(record.get("access"), dict) else None
    if access not in (None, "public"):
        raise SystemExit(f"record access is not public: {access!r}")
    files = {item.get("key"): item for item in record.get("files") or [] if isinstance(item, dict)}
    wanted: dict[str, tuple[int, str]] = {meta_key: (meta_bytes, meta_md5)}
    for row in read_selection(selection_path):
        wanted[row["zip_key"]] = (int(row["zip_bytes"]), row["zip_md5"])
    for key, (size, md5) in sorted(wanted.items()):
        item = files.get(key)
        if item is None:
            raise SystemExit(f"record no longer lists {key}")
        if int(item.get("size") or -1) != size:
            raise SystemExit(f"{key}: size changed {item.get('size')!r} != {size}")
        if str(item.get("checksum") or "").lower() != f"md5:{md5}":
            raise SystemExit(f"{key}: checksum changed {item.get('checksum')!r} != md5:{md5}")
    print(f"record_validation=ok record={RECORD_ID} license=cc-by-4.0 files_checked={len(wanted)}")


def check_member(span_path: Path, member_name: str, span_bytes: int, compressed: int, uncompressed: int, crc_hex: str) -> None:
    expected_crc = int(crc_hex, 16)
    size = span_path.stat().st_size
    if size != span_bytes:
        raise SystemExit(f"{member_name}: span is {size} bytes, expected {span_bytes}")
    digest = hashlib.sha256()
    with span_path.open("rb") as handle:
        head = handle.read(LOCAL_HEADER.size)
        if len(head) != LOCAL_HEADER.size:
            raise SystemExit(f"{member_name}: truncated local header")
        sig, _version, flags, method, _mtime, _mdate, crc, csize, usize, name_len, extra_len = LOCAL_HEADER.unpack(head)
        if sig != LOCAL_SIG:
            raise SystemExit(f"{member_name}: missing PK local-header signature (HTML or error body?)")
        name_raw = handle.read(name_len)
        extra = handle.read(extra_len)
        name = name_raw.decode("utf-8" if flags & 0x800 else "cp437")
        if name != member_name:
            raise SystemExit(f"{member_name}: local header names {name!r}")
        if flags & 0x0009:
            raise SystemExit(f"{member_name}: encrypted or data-descriptor member (flags={flags:#x})")
        if method != 8:
            raise SystemExit(f"{member_name}: compression method {method}, expected 8 (deflate)")
        if csize == 0xFFFFFFFF or usize == 0xFFFFFFFF:
            pos = 0
            while pos + 4 <= len(extra):
                header_id, length = struct.unpack_from("<HH", extra, pos)
                if header_id == 0x0001:
                    cursor = pos + 4
                    if usize == 0xFFFFFFFF:
                        usize = struct.unpack_from("<Q", extra, cursor)[0]
                        cursor += 8
                    if csize == 0xFFFFFFFF:
                        csize = struct.unpack_from("<Q", extra, cursor)[0]
                pos += 4 + length
        if (crc, csize, usize) != (expected_crc, compressed, uncompressed):
            raise SystemExit(
                f"{member_name}: local header crc/sizes {crc:08x}/{csize}/{usize} != pinned {expected_crc:08x}/{compressed}/{uncompressed}"
            )
        data_offset = LOCAL_HEADER.size + name_len + extra_len
        if data_offset + compressed != span_bytes:
            raise SystemExit(f"{member_name}: header+data {data_offset + compressed} != span {span_bytes}")
        digest.update(head + name_raw + extra)
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        running_crc = 0
        written = 0
        first = b""
        remaining = compressed
        while remaining:
            block = handle.read(min(remaining, 4 * 1024 * 1024))
            if not block:
                raise SystemExit(f"{member_name}: unexpected end of span")
            remaining -= len(block)
            digest.update(block)
            out = inflater.decompress(block)
            if len(first) < 256:
                first += out[: 256 - len(first)]
            running_crc = zlib.crc32(out, running_crc)
            written += len(out)
        out = inflater.flush()
        running_crc = zlib.crc32(out, running_crc)
        written += len(out)
        if not inflater.eof or inflater.unused_data:
            raise SystemExit(f"{member_name}: deflate stream does not end at the member boundary")
    if written != uncompressed or running_crc & 0xFFFFFFFF != expected_crc:
        raise SystemExit(f"{member_name}: inflated {written} bytes crc {running_crc & 0xFFFFFFFF:08x}; expected {uncompressed} {expected_crc:08x}")
    if not first.startswith(EXPECTED_HEADER):
        raise SystemExit(f"{member_name}: CSV header changed: {first[:80]!r}")
    print(f"member_validation=ok member={member_name} inflated={written} crc32={expected_crc:08x} span_sha256={digest.hexdigest()}")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "record" and len(sys.argv) == 7:
        check_record(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], int(sys.argv[5]), sys.argv[6])
    elif len(sys.argv) >= 2 and sys.argv[1] == "member" and len(sys.argv) == 8:
        check_member(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]), sys.argv[7])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
