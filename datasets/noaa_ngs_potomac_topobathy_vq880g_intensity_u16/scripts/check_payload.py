#!/usr/bin/env python3
"""Validate one downloaded COPC tile against its pinned sources.tsv facts.

Checks: exact byte size; the S3 ETag (multipart: MD5 of the concatenated
8 MiB part MD5s with '-N' part count, confirmed on a probe tile; single part:
plain MD5); optional pinned SHA-256; LAS 1.4 signature, compressed point
format 7 with 36-byte records, and the pinned 64-bit point count. Prints the
SHA-256 on success, exits non-zero otherwise.
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
    whole = hashlib.md5()
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
            whole.update(block)
            part_md5s.append(hashlib.md5(block).digest())
    if total != size:
        raise SystemExit(f"size mismatch: {total} != {size}")
    if "-" in etag:
        digest, parts = etag.split("-")
        if int(parts) != len(part_md5s):
            raise SystemExit(f"part count mismatch: {len(part_md5s)} != {parts}")
        got = hashlib.md5(b"".join(part_md5s)).hexdigest()
    else:
        digest, got = etag, whole.hexdigest()
    if got != digest:
        raise SystemExit(f"ETag mismatch: {got} != {digest}")
    if len(head) < 375 or head[:4] != b"LASF" or head[24:26] != b"\x01\x04":
        raise SystemExit("not a LAS 1.4 file")
    pf = head[104]
    (rlen,) = struct.unpack_from("<H", head, 105)
    (n,) = struct.unpack_from("<Q", head, 247)
    if pf & 0x3F != 7 or not pf & 0x80 or rlen != 36:
        raise SystemExit(f"unexpected point format byte {pf} / record length {rlen}")
    if n != count:
        raise SystemExit(f"point count {n} != pinned {count}")
    hexsha = sha.hexdigest()
    if want_sha and hexsha != want_sha:
        raise SystemExit(f"SHA-256 mismatch: {hexsha} != {want_sha}")
    print(hexsha)


if __name__ == "__main__":
    main()
