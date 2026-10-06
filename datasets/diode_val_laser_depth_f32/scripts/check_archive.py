#!/usr/bin/env python3
"""Validate a local DIODE val.tar.gz: exact size, publisher MD5, and head structure.

Usage: check_archive.py <path> <expected_bytes> <expected_md5>
Exit status 0 when valid; 1 when the file is missing or its size/MD5 differ
(corrupt or wrong file: safe to delete); 2 when size and MD5 match but the
structural head check fails (the exact published file: keep it and fix the
recipe). The head check inflates the first 8 MiB
of the gzip stream, walks the tar headers it contains, and parses the NPY
header of the first depth map (descr '<f4', C order, shape (768, 1024, 1)).
"""
from __future__ import annotations

import ast
import hashlib
import re
import struct
import sys
import zlib
from pathlib import Path

MEMBER_RE = re.compile(
    r"^val/(indoors|outdoor)/scene_\d{5}/scan_\d{5}/\d{5}_\d{5}_(indoors|outdoor)_\d{3}_\d{3}"
    r"(\.png|_depth\.npy|_depth_mask\.npy)$"
)
DIR_RE = re.compile(r"^val/((indoors|outdoor)(/scene_\d{5}(/scan_\d{5})?)?)?/?$")


class Corrupt(Exception):
    """Size or MD5 mismatch."""


def check(path: Path, expected_bytes: int, expected_md5: str) -> str | None:
    if not path.is_file():
        raise Corrupt(f"missing {path}")
    size = path.stat().st_size
    if size != expected_bytes:
        raise Corrupt(f"size {size} != {expected_bytes}")
    digest = hashlib.md5()
    with path.open("rb") as handle:
        head = handle.read(8 << 20)
        digest.update(head)
        while block := handle.read(16 << 20):
            digest.update(block)
    if digest.hexdigest() != expected_md5:
        raise Corrupt(f"md5 {digest.hexdigest()} != {expected_md5}")
    if head[:3] != b"\x1f\x8b\x08":
        return "not a gzip/deflate stream"
    tar = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(head)
    offset = 0
    depth_headers = 0
    names = 0
    while offset + 512 <= len(tar):
        block = tar[offset : offset + 512]
        if block == bytes(512):
            break
        if block[257:262] != b"ustar":
            return f"tar header at {offset} lacks ustar magic"
        name = block[0:100].rstrip(b"\0").decode("utf-8")
        prefix = block[345:500].rstrip(b"\0").decode("utf-8") if block[257:263] == b"ustar\0" else ""
        name = f"{prefix}/{name}" if prefix else name
        member_size = int(block[124:136].rstrip(b"\0 ") or b"0", 8)
        kind = block[156:157]
        names += 1
        if kind == b"5":
            if not DIR_RE.match(name):
                return f"unexpected directory {name!r}"
        elif kind in (b"0", b"\0"):
            if not MEMBER_RE.match(name):
                return f"unexpected member {name!r}"
            data = tar[offset + 512 : offset + 512 + 256]
            if name.endswith("_depth.npy") and len(data) >= 128:
                if data[:8] != b"\x93NUMPY\x01\x00":
                    return f"{name}: not NPY 1.0"
                header_len = struct.unpack_from("<H", data, 8)[0]
                header = ast.literal_eval(data[10 : 10 + header_len].decode("latin1"))
                if header != {"descr": "<f4", "fortran_order": False, "shape": (768, 1024, 1)}:
                    return f"{name}: unexpected NPY header {header!r}"
                depth_headers += 1
        else:
            return f"unexpected tar member type {kind!r} for {name!r}"
        offset += 512 + (member_size + 511) // 512 * 512
    if names == 0 or depth_headers == 0:
        return f"head check found {names} tar headers and {depth_headers} depth-map headers"
    print(f"archive_validation=ok bytes={size} md5={expected_md5} head_tar_headers={names} head_depth_headers={depth_headers}")
    return None


def main() -> int:
    try:
        problem = check(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
    except Corrupt as exc:
        print(f"archive_validation=failed (corrupt or wrong file): {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # structural parse error on an MD5-exact file
        problem = f"{type(exc).__name__}: {exc}"
    if problem:
        print(f"archive_validation=failed (MD5-exact file, unexpected structure): {problem}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
