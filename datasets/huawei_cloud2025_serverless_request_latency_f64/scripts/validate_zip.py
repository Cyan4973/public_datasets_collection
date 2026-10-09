#!/usr/bin/env python3
"""Semantic validation of the Huawei Cloud Trace 2025 R5.zip request table.

Usage: validate_zip.py <zip> <expected_size> <expected_central_directory_sha256>

Rejects HTML interstitials, truncated or substituted payloads: checks the
byte size, the local-header magic, the end-of-central-directory record
(200 entries), the SHA-256 of the central directory (which pins every member
name, size and CRC-32), the CRC-32 of every inflated member, and the exact
CSV header of every member.
"""
import hashlib
import re
import struct
import sys
import zipfile
from pathlib import Path

EXPECTED_HEADER = (
    "time_worker,time_frontend,requestID,clusterName,funcName,podID,userID,"
    "totalCost_worker,workerCost,runtimeCost,totalCost_frontend,frontendCost,"
    "busCost,readBodyCost,writeRspCost,cpu_usage,memory_usage,requestBodySize"
)
EXPECTED_MEMBERS = 200
EXPECTED_UNCOMPRESSED = 730289350
MEMBER_RE = re.compile(r"^R5/part-(\d{5})-7553bf50-4dbd-4c65-84df-39bf88b4f156-c000\.csv$")


def fail(message: str) -> None:
    raise SystemExit(f"validate_zip: {message}")


def main() -> None:
    path = Path(sys.argv[1])
    expected_size = int(sys.argv[2])
    expected_cd_sha = sys.argv[3]
    size = path.stat().st_size
    if size != expected_size:
        fail(f"size {size} != {expected_size}")
    with path.open("rb") as fh:
        if fh.read(4) != b"PK\x03\x04":
            fail("missing zip local-header magic (HTML interstitial?)")
        fh.seek(size - 22)
        eocd = fh.read(22)
        if eocd[:4] != b"PK\x05\x06":
            fail("end-of-central-directory record not at file end")
        _sig, _d, _cd, n_disk, n_total, cd_size, cd_off, _cl = struct.unpack("<4s4H2LH", eocd)
        if n_disk != EXPECTED_MEMBERS or n_total != EXPECTED_MEMBERS:
            fail(f"EOCD lists {n_total} entries, expected {EXPECTED_MEMBERS}")
        if cd_off + cd_size + 22 != size:
            fail("central directory does not end at EOCD")
        fh.seek(cd_off)
        cd_sha = hashlib.sha256(fh.read(cd_size)).hexdigest()
    if cd_sha != expected_cd_sha:
        fail(f"central directory sha256 {cd_sha} != {expected_cd_sha}")

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        indices = []
        for name in names:
            match = MEMBER_RE.match(name)
            if not match:
                fail(f"unexpected member {name!r}")
            indices.append(int(match.group(1)))
        if indices != list(range(EXPECTED_MEMBERS)):
            fail("members are not part-00000 .. part-00199 in order")
        total = sum(info.file_size for info in infos)
        if total != EXPECTED_UNCOMPRESSED:
            fail(f"uncompressed total {total} != {EXPECTED_UNCOMPRESSED}")
        rows = 0
        for info in infos:
            # Reading to EOF makes zipfile verify the member CRC-32.
            with zf.open(info) as member:
                header = member.readline().decode("utf-8").rstrip("\r\n")
                if header != EXPECTED_HEADER:
                    fail(f"{info.filename}: unexpected header {header[:120]!r}")
                while True:
                    chunk = member.read(1 << 22)
                    if not chunk:
                        break
                    rows += chunk.count(b"\n")
    print(f"validated_zip={path.name} bytes={size} members={len(infos)} uncompressed={total} data_lines={rows} cd_sha256={cd_sha}")


if __name__ == "__main__":
    main()
