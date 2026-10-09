#!/usr/bin/env python3
"""Validate one downloaded COPC tile against its pinned sources.tsv facts.

Checks: exact byte size; the S3 multipart ETag (MD5 of the concatenated
8 MiB part MD5s, '-N' suffix = part count; plain MD5 for single-part
objects); optional pinned SHA-256; and the LAS 1.4 / PDRF 6 / record length
30 header with the pinned point count. Prints the SHA-256 on success.
Usage: check_payload.py FILE SIZE ETAG POINT_COUNT [SHA256]
"""
import hashlib
import struct
import sys

PART = 8 * 1024 * 1024


def main():
    path, size, etag, count = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    want_sha = sys.argv[5] if len(sys.argv) > 5 else ""
    sha = hashlib.sha256()
    part_md5s = []
    total = 0
    with open(path, "rb") as fh:
        head = fh.read(375)
        fh.seek(0)
        while True:
            block = fh.read(PART)
            if not block:
                break
            total += len(block)
            sha.update(block)
            part_md5s.append(hashlib.md5(block).digest())
    if total != size:
        raise SystemExit(f"size mismatch: {total} != {size}")
    if "-" in etag:
        digest, parts = etag.split("-")
        if int(parts) != len(part_md5s):
            raise SystemExit(f"part count mismatch: {len(part_md5s)} != {parts}")
        got = hashlib.md5(b"".join(part_md5s)).hexdigest()
    else:
        digest = etag
        with open(path, "rb") as fh:
            got = hashlib.md5(fh.read()).hexdigest()
    if got != digest:
        raise SystemExit(f"ETag mismatch: {got} != {digest}")
    if head[:4] != b"LASF" or head[24:26] != b"\x01\x04":
        raise SystemExit("not a LAS 1.4 file")
    pf = head[104]
    (rlen,) = struct.unpack_from("<H", head, 105)
    (n,) = struct.unpack_from("<Q", head, 247)
    if pf & 0x3F != 6 or not pf & 0x80 or rlen != 30:
        raise SystemExit(f"unexpected point format {pf} / record length {rlen}")
    if n != count:
        raise SystemExit(f"point count {n} != pinned {count}")
    hexsha = sha.hexdigest()
    if want_sha and hexsha != want_sha:
        raise SystemExit(f"SHA-256 mismatch: {hexsha} != {want_sha}")
    print(hexsha)


if __name__ == "__main__":
    main()
