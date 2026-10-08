#!/usr/bin/env python3
"""Acquisition-side tools for the NCLT 2013-01-10 Velodyne tarball.

Subcommands (all pure standard library, no network I/O; curl does the fetch):

  check-headers  validate the HTTP headers of the one-byte liveness range GET
                 (206 status, Content-Range total, ETag, Last-Modified)
  etag           recompute the S3 multipart ETag (8 MiB parts) and SHA-256 of
                 the downloaded archive and compare with the pinned ETag
  scan           stream gzip + tar to EOF (gzip CRC32/ISIZE checked by the
                 gzip module), validate every member, and write members.tsv,
                 the member listing that build.sh selects from
  self-test      run scan and etag on small synthetic archives, including
                 corrupted ones that must be rejected

The archive is never extracted to disk. The 2.77 GB velodyne_hits.bin packet
stream is only checked for its size and first packet magic; the velodyne_sync
revolution files are read in memory one at a time. The scan is structural
(gzip CRC32/ISIZE, tar framing, 8-byte hit records, laser_id 0..31); the
documented 0..40000 coordinate-code range is recorded here and enforced as
fatal by build.sh and verify.sh.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path

SESSION = "2013-01-10"
HIT_RECORD_BYTES = 8
MAX_LASER_ID = 31
MAX_CODE = 40000
HITS_MAGIC = b"\x9c\xad" * 4  # four little-endian uint16 0xAD9C
MEMBER_FIELDS = [
    "archive_index",
    "kind",
    "name",
    "size_bytes",
    "utime",
    "hit_count",
    "laser_id_max",
    "code_max",
    "sha256",
]


def sync_pattern(session: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(session)}/velodyne_sync/(\d{{16}})\.bin$")


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


# --------------------------------------------------------------------------
# check-headers


def check_headers(headers_text: str, size: int, etag: str, last_modified: str) -> None:
    responses = re.split(r"(?=^HTTP/)", headers_text, flags=re.MULTILINE)
    final = next((part for part in reversed(responses) if part.strip()), "")
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    if not status or status.group(1) != "206":
        fail(f"liveness range GET did not return 206: {status.group(1) if status else None}")
    content_range = re.search(r"^content-range:\s*bytes\s+0-0/(\d+)\s*$", final, flags=re.I | re.M)
    if not content_range or int(content_range.group(1)) != size:
        fail(f"archive size changed: Content-Range {content_range.group(0) if content_range else None!r}")
    got_etag = re.search(r"^etag:\s*(\S+)\s*$", final, flags=re.I | re.M)
    if not got_etag or got_etag.group(1) != etag:
        fail(f"archive ETag changed: {got_etag.group(1) if got_etag else None!r} != {etag!r}")
    got_lm = re.search(r"^last-modified:\s*(.+?)\s*$", final, flags=re.I | re.M)
    if not got_lm or got_lm.group(1) != last_modified:
        fail(f"archive Last-Modified changed: {got_lm.group(1) if got_lm else None!r}")
    print(f"headers=ok status=206 size={size} etag={etag} last_modified={last_modified!r}")


# --------------------------------------------------------------------------
# etag


def multipart_etag(path: Path, part_bytes: int) -> tuple[str, str, int]:
    digests: list[bytes] = []
    sha = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            part = handle.read(part_bytes)
            if not part:
                break
            digests.append(hashlib.md5(part).digest())
            sha.update(part)
            total += len(part)
    if len(digests) == 1:
        etag = digests[0].hex()
    else:
        etag = f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}"
    return f'"{etag}"', sha.hexdigest(), total


# --------------------------------------------------------------------------
# scan


def scan_archive(path: Path, session: str, hits_bytes: int, min_sync: int) -> tuple[list[dict], dict]:
    """Stream the gzip tar to EOF; validate members; return listing and report."""
    if sys.byteorder != "little":
        fail("this tool reads little-endian uint16 codes through native memoryviews; big-endian hosts are unsupported")
    pattern = sync_pattern(session)
    hits_name = f"{session}/velodyne_hits.bin"
    members: list[dict] = []
    seen: set[str] = set()
    directories: list[str] = []
    hits_seen = 0
    sync_bytes = 0
    with gzip.open(path, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r|") as tar:
            for archive_index, member in enumerate(tar):
                name = member.name
                if name in seen:
                    fail(f"duplicate tar member {name!r}")
                seen.add(name)
                if member.isdir():
                    directories.append(name)
                    continue
                if not member.isfile():
                    fail(f"unexpected non-regular tar member {name!r} type={member.type!r}")
                row = {
                    "archive_index": archive_index,
                    "kind": "other",
                    "name": name,
                    "size_bytes": member.size,
                    "utime": "",
                    "hit_count": "",
                    "laser_id_max": "",
                    "code_max": "",
                    "sha256": "",
                }
                match = pattern.match(name)
                if name == hits_name:
                    if member.size != hits_bytes:
                        fail(f"{name} size {member.size} != pinned {hits_bytes}")
                    handle = tar.extractfile(member)
                    head = handle.read(24) if handle else b""
                    if head[:8] != HITS_MAGIC:
                        fail(f"{name} does not start with the 4 x 0xAD9C packet magic: {head[:8].hex()}")
                    row["kind"] = "hits"
                    hits_seen += 1
                elif match:
                    handle = tar.extractfile(member)
                    body = handle.read() if handle else b""
                    if len(body) != member.size:
                        fail(f"{name}: short read {len(body)} != {member.size}")
                    if member.size % HIT_RECORD_BYTES:
                        fail(f"{name}: size {member.size} is not a multiple of {HIT_RECORD_BYTES}")
                    hit_count = member.size // HIT_RECORD_BYTES
                    laser_max = max(body[7::8]) if hit_count else -1
                    if laser_max > MAX_LASER_ID:
                        fail(f"{name}: laser_id {laser_max} > {MAX_LASER_ID}")
                    code_max = 0
                    if hit_count:
                        words = memoryview(body).cast("H")  # native order; little-endian host checked above
                        code_max = max(max(words[0::4]), max(words[1::4]), max(words[2::4]))
                    row.update(
                        kind="sync",
                        utime=int(match.group(1)),
                        hit_count=hit_count,
                        laser_id_max=laser_max,
                        code_max=code_max,
                        sha256=hashlib.sha256(body).hexdigest(),
                    )
                    sync_bytes += member.size
                members.append(row)
        trailing = 0
        while True:
            chunk = gz.read(1 << 20)  # reading to EOF makes gzip check CRC32 and ISIZE
            if not chunk:
                break
            if chunk.count(0) != len(chunk):
                fail("non-zero bytes after the tar end-of-archive marker")
            trailing += len(chunk)
        uncompressed = gz.tell()
    if hits_seen != 1:
        fail(f"expected exactly one {hits_name}, found {hits_seen}")
    sync_rows = [row for row in members if row["kind"] == "sync"]
    if len(sync_rows) < min_sync:
        fail(f"only {len(sync_rows)} velodyne_sync members (< {min_sync})")
    utimes = [row["utime"] for row in sync_rows]
    if len(set(utimes)) != len(utimes):
        fail("duplicate velodyne_sync utimes")
    others = [row["name"] for row in members if row["kind"] == "other"]
    report = {
        "archive": path.name.removesuffix(".part"),
        "uncompressed_bytes": uncompressed,
        "gzip_crc32_isize": "ok",
        "trailing_zero_bytes_after_tar_member_stream": trailing,
        "directories": directories,
        "hits_member": hits_name,
        "hits_bytes": hits_bytes,
        "sync_members": len(sync_rows),
        "sync_bytes": sync_bytes,
        "sync_hits": sum(row["hit_count"] for row in sync_rows),
        "sync_utime_min": min(utimes),
        "sync_utime_max": max(utimes),
        "sync_archive_order_ascending": utimes == sorted(utimes),
        "sync_hit_count_min": min(row["hit_count"] for row in sync_rows),
        "sync_hit_count_max": max(row["hit_count"] for row in sync_rows),
        "sync_code_max": max(row["code_max"] for row in sync_rows),
        "sync_members_with_code_above_documented_max": sum(row["code_max"] > MAX_CODE for row in sync_rows),
        "other_members": others,
    }
    return members, report


def write_members(path: Path, members: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(MEMBER_FIELDS) + "\n")
        for row in members:
            handle.write("\t".join(str(row[key]) for key in MEMBER_FIELDS) + "\n")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# self-test


def synthetic_sync(n_hits: int, seed: int, laser_max: int = 31, code_max: int = 40000) -> bytes:
    out = bytearray()
    state = seed or 1
    for i in range(n_hits):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        x = 20000 + (state % 4000) - 2000
        y = 20000 + ((state >> 8) % 6000) - 3000
        z = 19000 + ((state >> 4) % 2000)
        out += x.to_bytes(2, "little") + y.to_bytes(2, "little") + z.to_bytes(2, "little")
        out += bytes([(state >> 3) & 0xFF, i % (laser_max + 1)])
    if n_hits:
        out[-1] = laser_max  # make sure the requested laser_id maximum occurs
    if code_max > 40000 and n_hits:
        out[0:2] = code_max.to_bytes(2, "little")
    return bytes(out)


def build_synthetic_archive(path: Path, session: str, sync_specs: list[tuple[int, int]], hits_body: bytes,
                            extra: dict[str, bytes] | None = None, trailing_garbage: bool = False,
                            bad_sync: bytes | None = None) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 1444020714
            info.mode = 0o664
            tar.addfile(info, io.BytesIO(data))

        info = tarfile.TarInfo(f"{session}/")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
        add(f"{session}/velodyne_hits.bin", hits_body)
        for utime, n_hits in sync_specs:
            add(f"{session}/velodyne_sync/{utime}.bin", synthetic_sync(n_hits, utime % 9973))
        if bad_sync is not None:
            add(f"{session}/velodyne_sync/1357848299999999.bin", bad_sync)
        for name, data in (extra or {}).items():
            add(name, data)
    payload = gzip.compress(raw.getvalue(), mtime=0)
    if trailing_garbage:
        payload = payload[:-8] + b"\x00\x00\x00\x00" + payload[-4:]  # break CRC32
    path.write_bytes(payload)


def expect_failure(label: str, func) -> None:
    try:
        func()
    except SystemExit as exc:
        if str(exc).startswith("FATAL"):
            print(f"self-test: rejected {label}: {exc}")
            return
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:  # gzip.BadGzipFile is an OSError
        print(f"self-test: rejected {label}: {type(exc).__name__}: {exc}")
        return
    raise SystemExit(f"self-test FAILED: {label} was accepted")


def self_test() -> None:
    session = SESSION
    hits = HITS_MAGIC + (7).to_bytes(4, "little") + (1357847237249109).to_bytes(8, "little") + b"\0" * 4
    hits += synthetic_sync(7, 5)
    specs = [(1357847300000000 + 200000 * i, n) for i, n in enumerate([50, 0, 3, 40, 41, 42, 43])]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        good = tmp_path / "good.tar.gz"
        build_synthetic_archive(good, session, specs, hits)
        members, report = scan_archive(good, session, len(hits), 5)
        sync = [row for row in members if row["kind"] == "sync"]
        assert len(sync) == 7 and report["sync_hits"] == sum(n for _, n in specs), report
        assert [row["hit_count"] for row in sync] == [n for _, n in specs]
        assert report["directories"] == [session] and report["other_members"] == []
        first = synthetic_sync(50, specs[0][0] % 9973)
        assert sync[0]["sha256"] == hashlib.sha256(first).hexdigest()
        assert sync[0]["laser_id_max"] == 31 and sync[0]["code_max"] <= MAX_CODE
        write_members(tmp_path / "members.tsv", members)
        lines = (tmp_path / "members.tsv").read_text().splitlines()
        assert lines[0].split("\t") == MEMBER_FIELDS and len(lines) == 1 + len(members)

        # multipart ETag: parts of 4 bytes over a 10-byte file -> 3 parts
        blob = tmp_path / "blob.bin"
        blob.write_bytes(b"0123456789")
        etag, sha, total = multipart_etag(blob, 4)
        parts = [b"0123", b"4567", b"89"]
        expected = hashlib.md5(b"".join(hashlib.md5(p).digest() for p in parts)).hexdigest() + "-3"
        assert etag == f'"{expected}"' and total == 10 and sha == hashlib.sha256(b"0123456789").hexdigest()
        etag1, _, _ = multipart_etag(blob, 64)
        assert etag1 == f'"{hashlib.md5(b"0123456789").hexdigest()}"'

        check_headers(
            "HTTP/1.1 200 Connection established\r\n\r\nHTTP/1.1 206 Partial Content\r\n"
            'Content-Range: bytes 0-0/99\r\nETag: "abc-2"\r\nLast-Modified: Tue, 27 Sep 2022 11:37:44 GMT\r\n',
            99, '"abc-2"', "Tue, 27 Sep 2022 11:37:44 GMT")
        expect_failure("changed ETag header", lambda: check_headers(
            'HTTP/1.1 206 Partial Content\r\nContent-Range: bytes 0-0/99\r\nETag: "abd-2"\r\n'
            "Last-Modified: Tue, 27 Sep 2022 11:37:44 GMT\r\n", 99, '"abc-2"', "Tue, 27 Sep 2022 11:37:44 GMT"))

        cases = {
            "bad gzip CRC32": dict(trailing_garbage=True),
            "sync size not a multiple of 8": dict(bad_sync=b"\x01" * 12),
            "laser_id 32": dict(bad_sync=synthetic_sync(10, 3, laser_max=32)),
        }
        for label, kwargs in cases.items():
            bad = tmp_path / "bad.tar.gz"
            build_synthetic_archive(bad, session, specs, hits, **kwargs)
            expect_failure(label, lambda bad=bad: scan_archive(bad, session, len(hits), 5))
        bad = tmp_path / "bad_magic.tar.gz"
        build_synthetic_archive(bad, session, specs, b"\0" * len(hits))
        expect_failure("hits magic", lambda: scan_archive(bad, session, len(hits), 5))
        expect_failure("hits size", lambda: scan_archive(good, session, len(hits) + 8, 5))
        expect_failure("too few sync members", lambda: scan_archive(good, session, len(hits), 8))
        truncated = tmp_path / "truncated.tar.gz"
        truncated.write_bytes(good.read_bytes()[:-100])
        expect_failure("truncated gzip", lambda: scan_archive(truncated, session, len(hits), 5))
        high = tmp_path / "high_code.tar.gz"
        build_synthetic_archive(high, session, specs, hits, bad_sync=synthetic_sync(10, 3, code_max=40001))
        _, report = scan_archive(high, session, len(hits), 5)
        assert report["sync_code_max"] == 40001 and report["sync_members_with_code_above_documented_max"] == 1
        other = tmp_path / "other.tar.gz"
        build_synthetic_archive(other, session, specs, hits, extra={f"{session}/README.txt": b"x"})
        _, report = scan_archive(other, session, len(hits), 5)
        assert report["other_members"] == [f"{session}/README.txt"], report
    print("self-test=ok")


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-headers")
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--etag", required=True)
    p.add_argument("--last-modified", required=True)
    p = sub.add_parser("etag")
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--part-bytes", type=int, required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--expected-etag", required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p = sub.add_parser("scan")
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--session", default=SESSION)
    p.add_argument("--hits-bytes", type=int, required=True)
    p.add_argument("--min-sync", type=int, required=True)
    p.add_argument("--members", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()

    if args.command == "check-headers":
        check_headers(args.headers.read_text(encoding="iso-8859-1"), args.size, args.etag, args.last_modified)
    elif args.command == "etag":
        etag, sha, total = multipart_etag(args.archive, args.part_bytes)
        if total != args.size:
            fail(f"archive size {total} != pinned {args.size}")
        if etag != args.expected_etag:
            fail(f"S3 multipart ETag mismatch: computed {etag} expected {args.expected_etag}")
        receipt = {"size_bytes": total, "s3_multipart_etag": etag, "part_bytes": args.part_bytes, "sha256": sha}
        tmp = args.receipt.with_suffix(".tmp")
        tmp.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, args.receipt)
        print(f"etag=ok {etag} size={total} sha256={sha}")
    elif args.command == "scan":
        members, report = scan_archive(args.archive, args.session, args.hits_bytes, args.min_sync)
        write_members(args.members, members)
        tmp = args.report.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, args.report)
        print(
            "scan=ok uncompressed_bytes={uncompressed_bytes} sync_members={sync_members} sync_hits={sync_hits} "
            "sync_utime_min={sync_utime_min} sync_utime_max={sync_utime_max} "
            "archive_order_ascending={sync_archive_order_ascending} other_members={n_other}".format(
                n_other=len(report["other_members"]), **report)
        )
    else:
        self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
