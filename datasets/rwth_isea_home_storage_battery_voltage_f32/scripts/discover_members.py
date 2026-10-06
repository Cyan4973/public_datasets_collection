#!/usr/bin/env python3
"""Rebuild selection.tsv from Zenodo metadata and ZIP central-directory tails.

discover.sh fetches, with curl, the record JSON and the last 128 KiB of each
Data_ID_07..21 zip (which holds the end-of-central-directory record and the
whole central directory). This script parses them, prints a per-system list of
months whose uncompressed bytes-per-second look like a complete month, and
writes or checks selection.tsv for the fixed month selection below.

  discover_members.py <discover_dir> --check <selection.tsv>
  discover_members.py <discover_dir> --write <selection.tsv>
"""
from __future__ import annotations

import argparse
import calendar
import collections
import json
import struct
from pathlib import Path

# Systems 7-21 are the 46-51.8 V nominal packs (Metadata_Systems.xlsx); 13 and
# 17 are dropped for their coarser 1 mV / 10 mV voltage print lattice, and 18
# because none of its months is complete and free of disconnection readings.
# Three months per system, spread over the system's record and the seasons.
# The final list came from two download/build rounds: candidates that failed the
# completeness or range policy were replaced by the next candidate in order
# (README "Selection history" lists them).
SELECTED = {
    7: ["2016_08", "2019_11", "2022_05"],
    8: ["2016_07", "2019_01", "2022_06"],
    9: ["2016_06", "2018_12", "2022_08"],
    10: ["2018_09", "2020_01", "2022_05"],
    11: ["2019_12", "2021_05", "2022_08"],
    12: ["2019_07", "2021_02", "2022_09"],
    14: ["2015_09", "2017_11", "2020_04"],
    15: ["2016_08", "2020_05", "2022_07"],
    16: ["2019_06", "2020_12", "2022_08"],
    19: ["2016_04", "2017_12", "2020_07"],
    20: ["2016_09", "2018_07", "2020_01"],
    21: ["2016_09", "2018_01", "2020_06"],
}
COLUMNS = ["system_id", "month", "zip_key", "zip_bytes", "zip_md5", "member_name", "local_header_offset",
           "span_bytes", "compressed_bytes", "uncompressed_bytes", "crc32", "expected_rows"]


def parse_central_directory(tail: bytes, zip_size: int) -> tuple[list[dict], int]:
    base = zip_size - len(tail)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit("no end-of-central-directory record in tail")
    _sig, _d, _cd, _n_this, n_total, _cd_size, cd_offset, _cl = struct.unpack_from("<IHHHHIIH", tail, eocd)
    if cd_offset == 0xFFFFFFFF or n_total == 0xFFFF:
        locator = tail.rfind(b"PK\x06\x07")
        z64_offset = struct.unpack_from("<Q", tail, locator + 8)[0]
        rec = z64_offset - base
        n_total = struct.unpack_from("<Q", tail, rec + 32)[0]
        cd_offset = struct.unpack_from("<Q", tail, rec + 48)[0]
    pos = cd_offset - base
    if pos < 0:
        raise SystemExit("central directory starts before the fetched tail")
    entries = []
    for _ in range(n_total):
        fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
        if fields[0] != 0x02014B50:
            raise SystemExit("bad central-directory signature")
        flags, method, crc, csize, usize, name_len, extra_len, comment_len, offset = (
            fields[3], fields[4], fields[7], fields[8], fields[9], fields[10], fields[11], fields[12], fields[16])
        name = tail[pos + 46 : pos + 46 + name_len].decode("utf-8" if flags & 0x800 else "cp437")
        extra = tail[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        cursor = 0
        while cursor + 4 <= len(extra):
            header_id, length = struct.unpack_from("<HH", extra, cursor)
            if header_id == 0x0001:
                inner = cursor + 4
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack_from("<Q", extra, inner)[0]
                    inner += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack_from("<Q", extra, inner)[0]
                    inner += 8
                if offset == 0xFFFFFFFF:
                    offset = struct.unpack_from("<Q", extra, inner)[0]
            cursor += 4 + length
        entries.append({"name": name, "flags": flags, "method": method, "crc": crc, "csize": csize, "usize": usize, "offset": offset})
        pos += 46 + name_len + extra_len + comment_len
    entries.sort(key=lambda item: item["offset"])
    for i, item in enumerate(entries):
        item["end"] = entries[i + 1]["offset"] if i + 1 < len(entries) else cd_offset
    return entries, cd_offset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("discover_dir", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", type=Path)
    group.add_argument("--write", type=Path)
    args = parser.parse_args()
    record = json.loads((args.discover_dir / "record.json").read_text(encoding="utf-8"))
    files = {item["key"]: item for item in record["files"]}
    rows = []
    for sid, months in SELECTED.items():
        key = f"Data_ID_{sid:02d}.zip"
        zip_size = int(files[key]["size"])
        md5 = files[key]["checksum"].split(":", 1)[1]
        tail = (args.discover_dir / f"{key}.tail").read_bytes()
        entries, _ = parse_central_directory(tail, zip_size)
        by_name = {item["name"]: item for item in entries}
        per_month = collections.defaultdict(float)
        csv_entries = [item for item in entries if item["name"].endswith(".csv")]
        for item in csv_entries:
            year, month = int(item["name"][3:7]), int(item["name"][8:10])
            per_month[month] = max(per_month[month], item["usize"] / (calendar.monthrange(year, month)[1] * 86400))
        likely = []
        for item in csv_entries:
            year, month = int(item["name"][3:7]), int(item["name"][8:10])
            bps = item["usize"] / (calendar.monthrange(year, month)[1] * 86400)
            if bps >= 0.97 * per_month[month]:
                likely.append(f"{year}-{month:02d}")
        print(f"system {sid:02d}: {len(csv_entries)} monthly CSVs; likely complete: {' '.join(likely)}")
        for month_key in months:
            name = f"{sid:02d}/{month_key}_System_ID_{sid:02d}.csv"
            item = by_name[name]
            if item["method"] != 8 or item["flags"] & 0x9:
                raise SystemExit(f"{name}: unsupported method/flags")
            year, month = (int(part) for part in month_key.split("_"))
            rows.append([f"{sid:02d}", month_key, key, str(zip_size), md5, name, str(item["offset"]),
                         str(item["end"] - item["offset"]), str(item["csize"]), str(item["usize"]),
                         f"{item['crc']:08x}", str(calendar.monthrange(year, month)[1] * 86400)])
    text = "\t".join(COLUMNS) + "\n" + "".join("\t".join(row) + "\n" for row in rows)
    if args.write:
        args.write.write_text(text, encoding="utf-8")
        print(f"wrote {len(rows)} rows to {args.write}")
    else:
        current = args.check.read_text(encoding="utf-8")
        if current != text:
            raise SystemExit(f"{args.check} differs from the rediscovered selection")
        print(f"selection_check=ok rows={len(rows)} span_bytes={sum(int(r[7]) for r in rows)} values={sum(int(r[11]) for r in rows)}")


if __name__ == "__main__":
    main()
