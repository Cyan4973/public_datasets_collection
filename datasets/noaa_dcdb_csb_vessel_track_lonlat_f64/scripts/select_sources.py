#!/usr/bin/env python3
"""Metadata-only helpers for discover.sh.

Subcommands:
  parse-listing PAGE.xml        print key/size/etag/last_modified rows of one
                                ListObjectsV2 page to stdout; write the
                                truncation flag and the URL-encoded
                                continuation token to the --state file
  select                        combine the listing with the head/tail range
                                probes and write selection.tsv

The selection rules are documented in README.md and repeated here:

1. Providers whose LON/LAT text is not on the 1e-6 degree decimal lattice are
   excluded: AquaMap (full binary-float repr, 14-15 fractional digits) and PGS
   (files split between a 1e-4 and a 1e-6 lattice).
2. FarSounder is excluded: in this window its files are hourly rolling
   re-uploads with overlapping time ranges (one moored vessel) plus one
   50-second test file re-uploaded many times.
3. Among Rosepoint, GLOS and COMIT USF, exact re-uploads (same UNIQUE_ID,
   same object size, same first and last row TIME/LON/LAT) keep only the
   lexicographically first S3 key.
4. A remaining file whose first TIME precedes the latest last TIME of an
   earlier kept file of the same UNIQUE_ID is excluded as an overlapping
   re-submission (touching endpoints are allowed).
5. Any provider not listed above is excluded as unreviewed.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
HEADER = "UNIQUE_ID,FILE_UUID,LON,LAT,DEPTH,TIME,PLATFORM_NAME,PROVIDER"
KEEP_PROVIDERS = {"Rosepoint", "GLOS", "COMIT USF"}
EXCLUDED_PROVIDERS = {
    "AquaMap": "provider_off_lattice_float_repr",
    "PGS": "provider_mixed_1e-4_and_1e-6_lattice",
    "FarSounder": "provider_rolling_overlapping_resubmissions",
}
SELECTION_COLUMNS = [
    "key", "size_bytes", "etag", "last_modified", "provider", "unique_id",
    "first_time", "last_time", "decision", "reason",
]


def parse_listing(page: Path, state: Path) -> None:
    root = ET.parse(page).getroot()
    out = sys.stdout
    for item in root.findall("s:Contents", NS):
        key = item.find("s:Key", NS).text
        size = item.find("s:Size", NS).text
        etag = item.find("s:ETag", NS).text.strip('"')
        modified = item.find("s:LastModified", NS).text
        out.write(f"{key}\t{size}\t{etag}\t{modified}\n")
    truncated = root.find("s:IsTruncated", NS).text.strip().lower() == "true"
    token_node = root.find("s:NextContinuationToken", NS)
    token = token_node.text if token_node is not None and token_node.text else ""
    state.write_text(
        ("true" if truncated else "false") + "\n" + urllib.parse.quote(token, safe="") + "\n",
        encoding="utf-8",
    )


def parse_time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)


def rows_of(text: str, skip_first: bool) -> list[list[str]]:
    lines = text.split("\n")
    if skip_first:
        lines = lines[1:]
    if lines and not text.endswith("\n"):
        lines = lines[:-1]
    rows = []
    for row in csv.reader(io.StringIO("\n".join(line for line in lines if line.strip()))):
        if len(row) == 8:
            rows.append(row)
    return rows


def select(listing: Path, heads: Path, tails: Path, output: Path) -> None:
    entries = []
    for line in listing.read_text(encoding="utf-8").splitlines():
        key, size, etag, modified = line.split("\t")
        entries.append({"key": key, "size_bytes": int(size), "etag": etag, "last_modified": modified})
    entries.sort(key=lambda entry: entry["key"])
    if len({entry["key"] for entry in entries}) != len(entries):
        raise SystemExit("duplicate keys in listing")
    names = [entry["key"].rsplit("/", 1)[1] for entry in entries]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate object basenames in listing")

    for entry in entries:
        name = entry["key"].rsplit("/", 1)[1]
        head = (heads / name).read_bytes().decode("utf-8", "replace")
        tail = (tails / name).read_bytes().decode("utf-8", "replace")
        if head.split("\n", 1)[0].rstrip("\r") != HEADER:
            raise SystemExit(f"unexpected header in {name}")
        head_rows = rows_of(head, skip_first=True)
        # The tail probe either starts mid-row (large object) or is the whole
        # object starting with the header; both cases drop the first line.
        tail_rows = rows_of(tail, skip_first=True)
        if not head_rows or not tail_rows:
            raise SystemExit(f"no parsable data rows in probes of {name}")
        first, last = head_rows[0], tail_rows[-1]
        if first[1] + "_pointData.csv" != name:
            raise SystemExit(f"FILE_UUID does not match key for {name}")
        entry.update(
            provider=first[7],
            unique_id=first[0],
            first_time=first[5],
            last_time=last[5],
            signature=(first[5], first[2], first[3], last[5], last[2], last[3]),
        )

    seen_signature: dict[tuple, str] = {}
    for entry in entries:
        provider = entry["provider"]
        if provider in EXCLUDED_PROVIDERS:
            entry["decision"], entry["reason"] = "exclude", EXCLUDED_PROVIDERS[provider]
            continue
        if provider not in KEEP_PROVIDERS:
            entry["decision"], entry["reason"] = "exclude", "provider_unreviewed"
            continue
        signature = (entry["unique_id"], entry["size_bytes"], entry["signature"])
        if signature in seen_signature:
            entry["decision"] = "exclude"
            entry["reason"] = "exact_reupload_of:" + seen_signature[signature].rsplit("/", 1)[1]
            continue
        seen_signature[signature] = entry["key"]
        entry["decision"], entry["reason"] = "keep", "unique_1e-6_lattice_submission"

    by_vessel: dict[str, list[dict]] = {}
    for entry in entries:
        if entry["decision"] == "keep":
            by_vessel.setdefault(entry["unique_id"], []).append(entry)
    for group in by_vessel.values():
        group.sort(key=lambda entry: (parse_time(entry["first_time"]), entry["key"]))
        latest_end = None
        latest_key = ""
        for entry in group:
            start, end = parse_time(entry["first_time"]), parse_time(entry["last_time"])
            if latest_end is not None and start < latest_end:
                entry["decision"] = "exclude"
                entry["reason"] = "overlaps_earlier_submission:" + latest_key.rsplit("/", 1)[1]
                continue
            if latest_end is None or end > latest_end:
                latest_end, latest_key = end, entry["key"]

    with output.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(SELECTION_COLUMNS) + "\n")
        for entry in entries:
            values = [str(entry[column]) for column in SELECTION_COLUMNS]
            if any("\t" in value or "\n" in value for value in values):
                raise SystemExit(f"tab or newline in selection field for {entry['key']}")
            handle.write("\t".join(values) + "\n")

    kept = [entry for entry in entries if entry["decision"] == "keep"]
    summary: dict[str, list[int]] = {}
    for entry in entries:
        bucket = summary.setdefault(f"{entry['provider']}|{entry['decision']}|{entry['reason'].split(':')[0]}", [0, 0])
        bucket[0] += 1
        bucket[1] += entry["size_bytes"]
    for name, (count, size) in sorted(summary.items()):
        print(f"{name}\tfiles={count}\tbytes={size}")
    print(f"listed_files={len(entries)} listed_bytes={sum(e['size_bytes'] for e in entries)}")
    print(f"keep_files={len(kept)} keep_bytes={sum(e['size_bytes'] for e in kept)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("parse-listing")
    listing.add_argument("page", type=Path)
    listing.add_argument("--state", type=Path, required=True)
    chooser = sub.add_parser("select")
    chooser.add_argument("--listing", type=Path, required=True)
    chooser.add_argument("--heads", type=Path, required=True)
    chooser.add_argument("--tails", type=Path, required=True)
    chooser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "parse-listing":
        parse_listing(args.page, args.state)
    else:
        select(args.listing, args.heads, args.tails, args.output)


if __name__ == "__main__":
    main()
