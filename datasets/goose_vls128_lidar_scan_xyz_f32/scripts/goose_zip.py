#!/usr/bin/env python3
"""ZIP helpers for range-fetching GOOSE 3D val LiDAR sweeps.

Pure standard library. The goose_3d_val.zip archive is 3.5 GB, so the recipe
never downloads it whole: it fetches the archive tail (the small LICENSE,
CHANGELOG and label-mapping members, followed by the central directory and
end records), checks that the pinned members are unchanged, and then
range-fetches only the selected stored (method 0) `*_vls128.bin` members.

Sub-commands:
  select        derive the pinned selection (sources.tsv) from a tail fetch
  check-tail    validate a tail fetch against the pinned constants and sources.tsv
  extract       validate one member range fetch and write its payload
  check-payloads  list pinned members whose local payload is missing or invalid
  self-test     exercise the parsers on synthetic archives
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import struct
import sys
import zlib
from pathlib import Path

ARCHIVE_URL = "https://goose-dataset.de/storage/goose_3d_val.zip"
ARCHIVE_BYTES = 3_498_402_435
ARCHIVE_ETAG = '"67da9ea9-d0856283"'
CD_OFFSET = 3_498_107_450
CD_SIZE = 294_887
ENTRY_COUNT = 1_925
BIN_COUNT = 961
# The tail fetch starts at the LICENSE local header, the first of three small
# metadata members stored after all lidar/label members.
TAIL_START = 3_498_085_530
TAIL_END = ARCHIVE_BYTES - 1
META_MEMBERS = {
    "LICENSE": (20_138, 0xAE93_DC2C),
    "CHANGELOG": (226, 0xA884_69F6),
    "goose_label_mapping.csv": (1_427, 0xCC25_06CF),
}
LICENSE_FIRST_LINE = "Attribution-ShareAlike 4.0 International"
CHANGELOG_NEEDLE = "2024-07-26: Initial upload of GOOSE 3D with 9892 annotated LiDAR scenes."
PER_SEQUENCE = 8
POINT_BYTES = 16  # x, y, z, remission as little-endian float32
MEMBER_RE = re.compile(
    r"^lidar/val/(?P<seq>[^/]+)/(?P=seq)__(?P<frame>\d{4})_(?P<ts>\d{19})_vls128\.bin$"
)
SOURCES_FIELDS = [
    "sequence",
    "frame",
    "timestamp_ns",
    "member_name",
    "local_header_offset",
    "range_start",
    "range_end",
    "payload_bytes",
    "crc32",
    "point_count",
]
SOURCES_INT_FIELDS = ("local_header_offset", "range_start", "range_end", "payload_bytes", "point_count")

LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
CENTRAL_HEADER = struct.Struct("<IHHHHHHIIIHHHHHII")
EOCD = struct.Struct("<IHHHHIIH")


def parse_zip64_extra(extra: bytes, usize: int, csize: int, offset: int, disk: int) -> tuple[int, int, int]:
    """Resolve 0xFFFFFFFF placeholders from a ZIP64 extended-information field."""
    pos = 0
    while pos + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, pos)
        body = extra[pos + 4 : pos + 4 + size]
        if len(body) != size:
            raise ValueError("truncated ZIP extra field")
        if header_id == 0x0001:
            cursor = 0

            def take() -> int:
                nonlocal cursor
                if cursor + 8 > len(body):
                    raise ValueError("ZIP64 extra field too short")
                (value,) = struct.unpack_from("<Q", body, cursor)
                cursor += 8
                return value

            if usize == 0xFFFFFFFF:
                usize = take()
            if csize == 0xFFFFFFFF:
                csize = take()
            if offset == 0xFFFFFFFF:
                offset = take()
            return usize, csize, offset
        pos += 4 + size
    if 0xFFFFFFFF in (usize, csize, offset):
        raise ValueError("ZIP64 placeholder without a ZIP64 extra field")
    return usize, csize, offset


def parse_central_directory(buf: bytes, buf_start: int, cd_offset: int, cd_size: int, count: int) -> list[dict]:
    """Parse `count` central-directory records located at absolute `cd_offset`."""
    pos = cd_offset - buf_start
    end = pos + cd_size
    if pos < 0 or end > len(buf):
        raise ValueError("central directory not inside the fetched buffer")
    entries = []
    while pos < end:
        fields = CENTRAL_HEADER.unpack_from(buf, pos)
        if fields[0] != 0x02014B50:
            raise ValueError(f"bad central-directory signature at buffer offset {pos}")
        (_, _, _, flags, method, _, _, crc, csize, usize, nlen, xlen, clen, disk, _, _, lho) = fields
        name_raw = buf[pos + 46 : pos + 46 + nlen]
        name = name_raw.decode("utf-8" if flags & 0x800 else "cp437")
        extra = buf[pos + 46 + nlen : pos + 46 + nlen + xlen]
        usize, csize, lho = parse_zip64_extra(extra, usize, csize, lho, disk)
        entries.append(
            {"name": name, "flags": flags, "method": method, "crc32": crc, "csize": csize, "usize": usize, "offset": lho}
        )
        pos += 46 + nlen + xlen + clen
    if pos != end or len(entries) != count:
        raise ValueError(f"central directory size/count mismatch: parsed {len(entries)} entries")
    return entries


def parse_tail(buf: bytes, buf_start: int, archive_bytes: int) -> tuple[list[dict], int, int]:
    """Locate the end-of-central-directory record in a tail buffer and parse the directory.

    Returns (entries, central_directory_offset, central_directory_size).
    """
    if buf_start + len(buf) != archive_bytes:
        raise ValueError("tail buffer does not end at the archive end")
    eocd_pos = buf.rfind(b"PK\x05\x06")
    if eocd_pos < 0:
        raise ValueError("no end-of-central-directory record")
    _, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = EOCD.unpack_from(buf, eocd_pos)
    if eocd_pos + 22 + comment_len != len(buf) or disk != 0 or cd_disk != 0 or n_disk != n_total:
        raise ValueError("unexpected EOCD layout")
    if 0xFFFFFFFF in (cd_size, cd_offset) or n_total == 0xFFFF:
        locator = eocd_pos - 20
        if buf[locator : locator + 4] != b"PK\x06\x07":
            raise ValueError("ZIP64 EOCD locator missing")
        (record_offset,) = struct.unpack_from("<Q", buf, locator + 8)
        record = record_offset - buf_start
        if buf[record : record + 4] != b"PK\x06\x06":
            raise ValueError("ZIP64 EOCD record missing")
        n_total, cd_size, cd_offset = struct.unpack_from("<QQQ", buf, record + 32)
    return parse_central_directory(buf, buf_start, cd_offset, cd_size, n_total), cd_offset, cd_size


def read_local_member(buf: bytes, buf_start: int, entry: dict) -> bytes:
    """Return the payload of a stored member from a buffer that contains its local header."""
    pos = entry["offset"] - buf_start
    if pos < 0 or pos + LOCAL_HEADER.size > len(buf):
        raise ValueError(f"local header of {entry['name']} not inside buffer")
    (sig, _, flags, method, _, _, crc, csize, usize, nlen, xlen) = LOCAL_HEADER.unpack_from(buf, pos)
    if sig != 0x04034B50:
        raise ValueError(f"bad local-header signature for {entry['name']}")
    name = buf[pos + 30 : pos + 30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    if name != entry["name"]:
        raise ValueError(f"local name {name!r} != central name {entry['name']!r}")
    if method != 0 or entry["method"] != 0:
        raise ValueError(f"{name}: not a stored member (method {method})")
    if flags & 0x0009:
        raise ValueError(f"{name}: encrypted or data-descriptor member (flags {flags:#x})")
    extra = buf[pos + 30 + nlen : pos + 30 + nlen + xlen]
    usize, csize, _ = parse_zip64_extra(extra, usize, csize, 0, 0)
    if (crc, csize, usize) != (entry["crc32"], entry["csize"], entry["usize"]) or csize != usize:
        raise ValueError(f"{name}: local header crc/size disagree with central directory")
    start = pos + 30 + nlen + xlen  # skip using the LOCAL extra length, not the central one
    payload = bytes(buf[start : start + csize])
    if len(payload) != csize:
        raise ValueError(f"{name}: payload truncated")
    if zlib.crc32(payload) & 0xFFFFFFFF != entry["crc32"]:
        raise ValueError(f"{name}: CRC32 mismatch")
    return payload


def http_final_response(headers_text: str) -> tuple[int, tuple[int, int, int] | None, str | None]:
    # curl --dump-header records every response, including a proxy CONNECT reply; the last one counts.
    responses = [part for part in re.split(r"(?=^HTTP/)", headers_text, flags=re.MULTILINE) if part.strip()]
    final = responses[-1] if responses else ""
    status = re.match(r"HTTP/\S+\s+(\d+)", final)
    content_range = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    etag = re.search(r"^etag:\s*(\S+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    return (
        int(status.group(1)) if status else 0,
        tuple(int(v) for v in content_range.groups()) if content_range else None,
        etag.group(1) if etag else None,
    )


def check_range_headers(headers_path: Path, start: int, end: int) -> None:
    status, content_range, etag = http_final_response(headers_path.read_text(encoding="iso-8859-1"))
    if status != 206 or content_range != (start, end, ARCHIVE_BYTES):
        raise SystemExit(f"server did not honor the exact range {start}-{end}: status={status} content_range={content_range}")
    if etag is not None and etag != ARCHIVE_ETAG:
        raise SystemExit(f"archive ETag changed: {etag} != {ARCHIVE_ETAG}")


def select_members(entries: list[dict], per_sequence: int = PER_SEQUENCE) -> list[dict]:
    """Evenly spaced sweeps per val sequence, centred in equal frame-order strata."""
    by_sequence: dict[str, list[tuple[int, dict]]] = {}
    for entry in entries:
        match = MEMBER_RE.match(entry["name"])
        if not match:
            continue
        by_sequence.setdefault(match["seq"], []).append((int(match["frame"]), entry))
    chosen = []
    for sequence in sorted(by_sequence):
        members = sorted(by_sequence[sequence], key=lambda item: item[0])
        count = len(members)
        if count < per_sequence:
            raise ValueError(f"{sequence}: only {count} sweeps")
        for k in range(per_sequence):
            frame, entry = members[((2 * k + 1) * count) // (2 * per_sequence)]
            match = MEMBER_RE.match(entry["name"])
            assert match is not None
            chosen.append(
                {
                    "sequence": sequence,
                    "frame": f"{frame:04d}",
                    "timestamp_ns": match["ts"],
                    "member_name": entry["name"],
                    "local_header_offset": entry["offset"],
                    "range_start": entry["offset"],
                    "range_end": entry["offset"] + 30 + len(entry["name"].encode("utf-8")) + entry["csize"] - 1,
                    "payload_bytes": entry["csize"],
                    "crc32": f"{entry['crc32']:08x}",
                    "point_count": entry["csize"] // POINT_BYTES,
                }
            )
    return chosen


def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != SOURCES_FIELDS:
        raise SystemExit(f"{path}: unexpected sources.tsv header")
    for row in rows:
        for key in SOURCES_INT_FIELDS:
            row[key] = int(row[key])
    return rows


def sources_row_text(row: dict) -> dict:
    """Normalise a selection row to the string/int types read back from sources.tsv."""
    return {key: (int(row[key]) if key in SOURCES_INT_FIELDS else str(row[key])) for key in SOURCES_FIELDS}


def validate_entries(entries: list[dict], cd_offset: int, cd_size: int) -> dict[str, dict]:
    if len(entries) != ENTRY_COUNT:
        raise SystemExit(f"archive entry count changed: {len(entries)} != {ENTRY_COUNT}")
    if (cd_offset, cd_size) != (CD_OFFSET, CD_SIZE):
        raise SystemExit(f"central directory location changed: offset={cd_offset} size={cd_size}")
    bins = [entry for entry in entries if entry["name"].endswith(".bin")]
    if len(bins) != BIN_COUNT or not all(MEMBER_RE.match(entry["name"]) for entry in bins):
        raise SystemExit("unexpected set of lidar/val/*_vls128.bin members")
    for entry in bins:
        if entry["method"] != 0 or entry["csize"] != entry["usize"] or entry["csize"] % POINT_BYTES:
            raise SystemExit(f"{entry['name']}: not a stored N x 16-byte point record")
    return {entry["name"]: entry for entry in entries}


def cmd_select(args: argparse.Namespace) -> int:
    buf = args.tail.read_bytes()
    entries, cd_offset, cd_size = parse_tail(buf, TAIL_START, ARCHIVE_BYTES)
    validate_entries(entries, cd_offset, cd_size)
    chosen = select_members(entries, args.per_sequence)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCES_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(chosen)
    total_payload = sum(row["payload_bytes"] for row in chosen)
    total_range = sum(row["range_end"] - row["range_start"] + 1 for row in chosen)
    print(
        f"selected={len(chosen)} payload_bytes={total_payload} range_bytes={total_range} "
        f"points={sum(row['point_count'] for row in chosen)} xyz_bytes={total_payload // 16 * 12}"
    )
    return 0


def cmd_check_tail(args: argparse.Namespace) -> int:
    check_range_headers(args.headers, TAIL_START, TAIL_END)
    buf = args.tail.read_bytes()
    if len(buf) != TAIL_END - TAIL_START + 1:
        raise SystemExit(f"tail fetch has {len(buf)} bytes, expected {TAIL_END - TAIL_START + 1}")
    entries, cd_offset, cd_size = parse_tail(buf, TAIL_START, ARCHIVE_BYTES)
    by_name = validate_entries(entries, cd_offset, cd_size)
    args.meta_dir.mkdir(parents=True, exist_ok=True)
    for name, (size, crc) in META_MEMBERS.items():
        entry = by_name.get(name)
        if entry is None or entry["csize"] != size or entry["crc32"] != crc:
            raise SystemExit(f"metadata member {name} changed")
        payload = read_local_member(buf, TAIL_START, entry)
        (args.meta_dir / name).write_bytes(payload)
    license_text = (args.meta_dir / "LICENSE").read_text(encoding="utf-8")
    if license_text.splitlines()[0].strip() != LICENSE_FIRST_LINE or "ShareAlike" not in license_text:
        raise SystemExit("LICENSE member is not CC BY-SA 4.0")
    if CHANGELOG_NEEDLE not in (args.meta_dir / "CHANGELOG").read_text(encoding="utf-8"):
        raise SystemExit("CHANGELOG no longer names the 2024-07-26 GOOSE 3D upload")
    rows = read_sources(args.sources)
    # Re-derive the selection rule from the live directory; the pinned list must match exactly.
    live = [sources_row_text(row) for row in select_members(entries, PER_SEQUENCE)]
    if rows != live:
        raise SystemExit("pinned sources.tsv no longer matches the selection derived from the live central directory")
    for row in rows:
        entry = by_name[row["member_name"]]
        if (entry["offset"], entry["csize"], f"{entry['crc32']:08x}") != (
            row["local_header_offset"],
            row["payload_bytes"],
            row["crc32"],
        ):
            raise SystemExit(f"{row['member_name']}: offset/size/crc changed")
    print(
        f"tail_validation=ok entries={len(entries)} bins={BIN_COUNT} license=CC-BY-SA-4.0 "
        f"selected={len(rows)} sequences={len({row['sequence'] for row in rows})}"
    )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    rows = {row["member_name"]: row for row in read_sources(args.sources)}
    row = rows.get(args.member)
    if row is None:
        raise SystemExit(f"{args.member} is not pinned in sources.tsv")
    check_range_headers(args.headers, row["range_start"], row["range_end"])
    buf = args.range_file.read_bytes()
    if len(buf) != row["range_end"] - row["range_start"] + 1:
        raise SystemExit(f"{args.member}: range fetch has {len(buf)} bytes")
    entry = {
        "name": row["member_name"],
        "method": 0,
        "crc32": int(row["crc32"], 16),
        "csize": row["payload_bytes"],
        "usize": row["payload_bytes"],
        "offset": row["local_header_offset"],
    }
    payload = read_local_member(buf, row["range_start"], entry)
    if len(payload) % POINT_BYTES:
        raise SystemExit(f"{args.member}: payload is not a whole number of 16-byte points")
    args.out.write_bytes(payload)
    print(f"member_validation=ok name={Path(args.member).name} bytes={len(payload)} crc32={row['crc32']}")
    return 0


def cmd_check_payloads(args: argparse.Namespace) -> int:
    """List pinned members whose extracted payload is missing or invalid (one name per line)."""
    missing = 0
    for row in read_sources(args.sources):
        path = args.download_dir / "lidar" / "val" / row["sequence"] / Path(row["member_name"]).name
        ok = path.is_file() and path.stat().st_size == row["payload_bytes"]
        if ok:
            ok = f"{zlib.crc32(path.read_bytes()) & 0xFFFFFFFF:08x}" == row["crc32"]
            if not ok:
                path.unlink()
        if not ok:
            missing += 1
            if args.list:
                print(row["member_name"])
    if not args.list:
        print(f"payload_check missing_or_invalid={missing}")
    return 1 if (missing and args.strict) else 0


def _synthetic_zip(members: list[tuple[str, bytes]], local_extra: bytes = b"", zip64_offsets: bool = False) -> bytes:
    """Hand-built stored ZIP; optionally forces ZIP64 offsets in the central directory."""
    out = io.BytesIO()
    central = []
    for name, data in members:
        offset = out.tell()
        raw = name.encode()
        crc = zlib.crc32(data) & 0xFFFFFFFF
        out.write(LOCAL_HEADER.pack(0x04034B50, 20, 0, 0, 0, 0, crc, len(data), len(data), len(raw), len(local_extra)))
        out.write(raw + local_extra + data)
        if zip64_offsets:
            extra = struct.pack("<HHQ", 1, 8, offset)
            lho = 0xFFFFFFFF
        else:
            extra = b""
            lho = offset
        central.append(
            CENTRAL_HEADER.pack(0x02014B50, 45, 20, 0, 0, 0, 0, crc, len(data), len(data), len(raw), len(extra), 0, 0, 0, 0, lho)
            + raw
            + extra
        )
    cd_offset = out.tell()
    for record in central:
        out.write(record)
    cd_size = out.tell() - cd_offset
    out.write(EOCD.pack(0x06054B50, 0, 0, len(members), len(members), cd_size, cd_offset, 0))
    return out.getvalue()


def cmd_self_test(_: argparse.Namespace) -> int:
    import zipfile

    points = struct.pack("<8f", 1.5, -2.25, 0.125, 7.0, -100.0, 50.5, -3.0, 255.0)
    names = [
        "lidar/val/seqA/seqA__0003_1658494234334310308_vls128.bin",
        "lidar/val/seqA/seqA__0001_1658494234334310309_vls128.bin",
        "lidar/val/seqA/seqA__0002_1658494234334310310_vls128.bin",
        "LICENSE",
    ]
    data = [points, points[::-1], points * 2, b"Attribution-ShareAlike 4.0 International\n"]
    for zip64 in (False, True):
        for local_extra in (b"", b"\x55\x54\x05\x00\x01\x00\x00\x00\x00"):
            archive = _synthetic_zip(list(zip(names, data)), local_extra=local_extra, zip64_offsets=zip64)
            # Python's zipfile must agree with the hand-built archive.
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                assert [zf.read(name) for name in names] == data
            tail_start = 7  # parse from a non-zero buffer start, as in the real tail fetch
            entries, _, _ = parse_tail(archive[tail_start:], tail_start, len(archive))
            assert [entry["name"] for entry in entries] == names
            for entry, expected in zip(entries, data):
                if entry["offset"] >= tail_start:
                    assert read_local_member(archive[tail_start:], tail_start, entry) == expected
                assert read_local_member(archive, 0, entry) == expected
            chosen = select_members(entries, per_sequence=2)
            # 3 frames, 2 strata: centred indices (1*3)//4 = 0 and (3*3)//4 = 2 in frame order.
            assert [row["frame"] for row in chosen] == ["0001", "0003"], chosen
            assert chosen[0]["range_end"] - chosen[0]["range_start"] + 1 == 30 + len(names[1]) + len(points)
    # Corruption is rejected.
    archive = bytearray(_synthetic_zip(list(zip(names, data))))
    entries, _, _ = parse_tail(bytes(archive), 0, len(archive))
    archive[30 + len(names[0]) + 3] ^= 0xFF
    try:
        read_local_member(bytes(archive), 0, entries[0])
    except ValueError:
        pass
    else:
        raise AssertionError("CRC corruption not detected")
    # Real Python-written archive (with its own ZIP64/extra conventions).
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, payload in zip(names, data):
            zf.writestr(name, payload)
    archive = buffer.getvalue()
    entries, _, _ = parse_tail(archive, 0, len(archive))
    assert [read_local_member(archive, 0, entry) for entry in entries] == data
    headers = (
        "HTTP/1.1 200 Connection established\r\nVia: proxy\r\n\r\n"
        "HTTP/2 206 \r\ncontent-range: bytes 10-20/3498402435\r\netag: \"67da9ea9-d0856283\"\r\n\r\n"
    )
    assert http_final_response(headers) == (206, (10, 20, 3498402435), '"67da9ea9-d0856283"')
    print("self_test=ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("select")
    p.add_argument("--tail", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per-sequence", type=int, default=PER_SEQUENCE)
    p.set_defaults(func=cmd_select)
    p = sub.add_parser("check-tail")
    p.add_argument("--tail", type=Path, required=True)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--meta-dir", type=Path, required=True)
    p.set_defaults(func=cmd_check_tail)
    p = sub.add_parser("extract")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--member", required=True)
    p.add_argument("--range-file", type=Path, required=True)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("check-payloads")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--download-dir", type=Path, required=True)
    p.add_argument("--list", action="store_true", help="print members that still need fetching")
    p.add_argument("--strict", action="store_true", help="exit 1 if any member is missing or invalid")
    p.set_defaults(func=cmd_check_payloads)
    p = sub.add_parser("self-test")
    p.set_defaults(func=cmd_self_test)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
