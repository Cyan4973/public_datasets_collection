#!/usr/bin/env python3
"""Download-time validation for the Cyprus PMU steady-state archives.

`record`: the live Zenodo record JSON must be the expected record, carry the
CC BY 4.0 license, describe PMU data from the Cyprus transmission system, and
list the pinned archive with the pinned size and MD5.

`archive`: the downloaded ZIP must contain exactly the pinned CSV members for
its archive key (outside `__MACOSX/`), each DEFLATE-compressed with the pinned
sizes and CRC32, and each member must open with a PMU CSV header
(`Date_Time,Mag_VA_...,Frequency,Dfrequency`).
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import zipfile
from pathlib import Path


def check_record(args: argparse.Namespace) -> None:
    raw = Path(args.record_json).read_bytes()
    if raw.lstrip()[:1] != b"{":
        raise SystemExit(f"record {args.record_id}: response is not JSON (HTML error page?)")
    record = json.loads(raw)
    if int(record.get("id") or 0) != args.record_id:
        raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
    metadata = record.get("metadata") or {}
    text = html.unescape(re.sub(r"<[^>]+>", " ", f"{metadata.get('title', '')} {metadata.get('description', '')}"))
    text = re.sub(r"\s+", " ", text).lower()
    if "pmu" not in text or "cyprus transmis" not in text:
        raise SystemExit(f"record {args.record_id} no longer describes Cyprus transmission PMU data: {metadata.get('title')!r}")
    license_value = metadata.get("license")
    license_id = (
        str(license_value.get("id") or "") if isinstance(license_value, dict) else str(license_value or "")
    )
    if license_id.lower() != "cc-by-4.0":
        raise SystemExit(f"record {args.record_id} license changed: {license_value!r}")
    if metadata.get("access_right") not in (None, "open"):
        raise SystemExit(f"record {args.record_id} access_right is {metadata.get('access_right')!r}")
    matches = [f for f in record.get("files") or [] if isinstance(f, dict) and f.get("key") == args.file_key]
    if len(matches) != 1:
        raise SystemExit(f"record {args.record_id}: expected one file {args.file_key!r}, found {len(matches)}")
    item = matches[0]
    if int(item.get("size") or 0) != args.size:
        raise SystemExit(f"record {args.record_id}: {args.file_key!r} size changed to {item.get('size')!r}")
    if str(item.get("checksum") or "").lower() != f"md5:{args.md5}":
        raise SystemExit(f"record {args.record_id}: {args.file_key!r} checksum changed to {item.get('checksum')!r}")
    print(
        f"record_validation=ok record={args.record_id} license=cc-by-4.0 "
        f"file={args.file_key!r} size={args.size} md5={args.md5} title={metadata.get('title')!r}"
    )


def load_members(path: Path, archive_key: str) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter="\t") if row["archive"] == archive_key]
    if not rows:
        raise SystemExit(f"members.tsv has no rows for archive {archive_key}")
    return rows


def check_archive(args: argparse.Namespace) -> None:
    archive = Path(args.archive)
    with archive.open("rb") as handle:
        if handle.read(4) != b"PK\x03\x04":
            raise SystemExit(f"{archive.name}: not a ZIP local-file header (HTML error page?)")
    expected = load_members(Path(args.members), args.archive_key)
    with zipfile.ZipFile(archive) as zf:
        infos = {info.filename: info for info in zf.infolist()}
        csv_names = {
            name for name in infos if name.lower().endswith(".csv") and not name.startswith("__MACOSX/")
        }
        wanted = {row["member"] for row in expected}
        if csv_names != wanted:
            raise SystemExit(
                f"{archive.name}: CSV member set changed; missing={sorted(wanted - csv_names)} "
                f"unexpected={sorted(csv_names - wanted)}"
            )
        for row in expected:
            info = infos[row["member"]]
            got = (info.compress_type, info.compress_size, info.file_size, f"{info.CRC:08x}")
            want = (zipfile.ZIP_DEFLATED, int(row["compressed_size"]), int(row["uncompressed_size"]), row["crc32"])
            if got != want:
                raise SystemExit(f"{archive.name}: member {row['member']!r} metadata {got} != pinned {want}")
            with zf.open(info) as member:
                head = member.read(65536).decode("ascii", errors="replace")
            first = head.split("\n", 1)[0]
            if not (first.startswith("Date_Time,Mag_VA_") and first.rstrip("\r").endswith(",Frequency,Dfrequency")):
                raise SystemExit(f"{archive.name}: member {row['member']!r} lacks the PMU CSV header: {first[:120]!r}")
            columns = first.rstrip("\r").split(",")
            voltage = [c for c in columns if re.fullmatch(r"Mag_V[ABC]_\d+_\d+", c)]
            print(
                f"member_ok archive={args.archive_key} pmu={row['pmu']} window={row['window']} "
                f"columns={len(columns)} voltage_magnitude_columns={len(voltage)} bytes={info.file_size}"
            )
    print(f"archive_validation=ok archive={args.archive_key} csv_members={len(expected)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--record-json", required=True)
    rec.add_argument("--record-id", type=int, required=True)
    rec.add_argument("--file-key", required=True)
    rec.add_argument("--size", type=int, required=True)
    rec.add_argument("--md5", required=True)
    arc = sub.add_parser("archive")
    arc.add_argument("--archive", required=True)
    arc.add_argument("--archive-key", required=True)
    arc.add_argument("--members", required=True)
    args = parser.parse_args()
    if args.command == "record":
        check_record(args)
    else:
        check_archive(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
