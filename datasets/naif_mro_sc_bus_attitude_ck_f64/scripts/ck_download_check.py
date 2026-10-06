#!/usr/bin/env python3
"""Parsing/validation helper called by download.sh (no network I/O here).

Subcommands
  files SOURCES                      unique pinned file names, in order
  segments SOURCES FILE HOST         "ordinal first_byte last_byte" per pinned segment
  next-summary FILEREC SUMMARIES     next DAF summary record number to fetch (0 = done)
  check-headers SOURCES FILE HOST FILEREC HTTPHDR SUMMARIES
  check-label SOURCES FILE LABEL
  check-segment SOURCES FILE ORDINAL SEGMENT   prints the segment sha256
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ck_type3 as ck  # noqa: E402

HOSTS = ("pds", "mirror")


def load_sources(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise SystemExit("sources.tsv is empty")
    return rows


def rows_for(rows: list[dict], name: str) -> list[dict]:
    selected = [row for row in rows if row["file_name"] == name]
    if not selected:
        raise SystemExit(f"{name} is not pinned in sources.tsv")
    return selected


def host_key(host: str, field: str) -> str:
    if host not in HOSTS:
        raise SystemExit(f"unknown host {host!r}")
    return f"{host}_{field}"


def read_chain(filerec_path: str, summaries_path: str) -> tuple[dict, list[dict], list[dict]]:
    header = ck.parse_file_record(Path(filerec_path).read_bytes())
    blob = Path(summaries_path).read_bytes() if Path(summaries_path).exists() else b""
    if len(blob) % ck.DAF_RECORD_BYTES:
        raise SystemExit("summary record file is not a whole number of DAF records")
    records = []
    expected = header["fward"]
    previous = 0
    for index in range(len(blob) // ck.DAF_RECORD_BYTES):
        if expected == 0:
            raise SystemExit("extra summary records after the end of the chain")
        parsed = ck.parse_summary_record(blob[index * 1024 : (index + 1) * 1024], header["endian"], expected)
        if parsed["prev"] != previous:
            raise SystemExit(f"broken PREV pointer in summary record {expected}")
        records.append(parsed)
        previous = expected
        expected = parsed["next"]
    summaries = [item for record in records for item in record["summaries"]]
    return header, records, summaries


def cmd_files(args: list[str]) -> None:
    seen = []
    for row in load_sources(args[0]):
        if row["file_name"] not in seen:
            seen.append(row["file_name"])
    print("\n".join(seen))


def cmd_segments(args: list[str]) -> None:
    sources, name, host = args
    for row in rows_for(load_sources(sources), name):
        start = int(row[host_key(host, "start_word")])
        end = int(row[host_key(host, "end_word")])
        print(f"{int(row['segment_ordinal'])} {(start - 1) * 8} {end * 8 - 1}")


def cmd_next_summary(args: list[str]) -> None:
    filerec, summaries = args
    header, records, _ = read_chain(filerec, summaries)
    print(header["fward"] if not records else records[-1]["next"])


def cmd_check_headers(args: list[str]) -> None:
    sources, name, host, filerec, httphdr, summaries_path = args
    rows = rows_for(load_sources(sources), name)
    header, records, summaries = read_chain(filerec, summaries_path)
    if not records or records[-1]["next"] != 0:
        raise SystemExit(f"{name}: summary chain incomplete")
    if header["bward"] != records[-1]["record_number"]:
        raise SystemExit(f"{name}: last summary record {records[-1]['record_number']} != BWARD {header['bward']}")
    if header["internal_name"] != "MRO TLM-Based SC Bus CK File by NAIF/JPL":
        raise SystemExit(f"{name}: unexpected DAF internal file name {header['internal_name']!r}")
    http = Path(httphdr).read_text(encoding="latin-1")
    totals = re.findall(r"(?im)^content-range:\s*bytes\s+0-1023/(\d+)\s*$", http)
    if not totals:
        raise SystemExit(f"{name}: no Content-Range total in the file-record response")
    size = int(totals[-1])
    pinned_size = int(rows[0][host_key(host, "size_bytes")])
    if size != pinned_size:
        raise SystemExit(f"{name}: {host} object size {size} != pinned {pinned_size}")
    if header["free"] * 8 > size + 8:
        raise SystemExit(f"{name}: DAF FREE address beyond the object size")
    if len(summaries) != int(rows[0]["segment_count"]):
        raise SystemExit(f"{name}: {len(summaries)} segments != pinned {rows[0]['segment_count']}")
    for ordinal, item in enumerate(summaries):
        ck.check_summary_identity(item, f"{name} segment {ordinal}")
        if item["end_word"] * 8 > size:
            raise SystemExit(f"{name}: segment {ordinal} extends beyond the object")
    for row in rows:
        ordinal = int(row["segment_ordinal"])
        item = summaries[ordinal]
        want = (int(row[host_key(host, "start_word")]), int(row[host_key(host, "end_word")]), float(row["sclk_begin"]), float(row["sclk_end"]))
        got = (item["start_word"], item["end_word"], item["sclk_begin"], item["sclk_end"])
        if got != want:
            raise SystemExit(f"{name} segment {ordinal}: descriptor {got} != pinned {want}")
        length = item["end_word"] - item["start_word"] + 1
        if length != ck.type3_expected_length(int(row["n_records"]), int(row["nints"])):
            raise SystemExit(f"{name} segment {ordinal}: pinned N/NINTS inconsistent with length {length}")
    print(f"headers ok file={name} host={host} size={size} segments={len(summaries)} fward={header['fward']} bward={header['bward']}")


def cmd_check_label(args: list[str]) -> None:
    sources, name, label_path = args
    rows = rows_for(load_sources(sources), name)
    raw = Path(label_path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != rows[0]["label_sha256"]:
        raise SystemExit(f"{label_path}: sha256 {digest} != pinned {rows[0]['label_sha256']}")
    text = raw.decode("ascii", errors="replace")
    for needle in (
        'DATA_SET_ID                  = "MRO-M-SPICE-6-V1.0"',
        "KERNEL_TYPE_ID               = CK",
        "NAIF_INSTRUMENT_ID           = -74000",
        "PRODUCT_VERSION_TYPE         = ACTUAL",
        f'PRODUCT_ID                   = "{name}"',
    ):
        if needle not in text:
            raise SystemExit(f"{label_path}: missing {needle!r}")
    print(f"label ok file={name} sha256={digest}")


def cmd_check_segment(args: list[str]) -> None:
    sources, name, ordinal_text, segment_path = args
    ordinal = int(ordinal_text)
    row = next((r for r in rows_for(load_sources(sources), name) if int(r["segment_ordinal"]) == ordinal), None)
    if row is None:
        raise SystemExit(f"{name} segment {ordinal} is not pinned")
    raw = Path(segment_path).read_bytes()
    n, nints = int(row["n_records"]), int(row["nints"])
    if len(raw) != ck.type3_expected_length(n, nints) * 8:
        raise SystemExit(f"{segment_path}: {len(raw)} bytes, expected {ck.type3_expected_length(n, nints) * 8}")
    summary = {"sclk_begin": float(row["sclk_begin"]), "sclk_end": float(row["sclk_end"])}
    result = ck.split_type3(raw, ">", summary, label=f"{name} segment {ordinal}")
    if (result["n"], result["nints"]) != (n, nints):
        raise SystemExit(f"{segment_path}: trailer (N, NINTS)=({result['n']}, {result['nints']}) != pinned ({n}, {nints})")
    digest = hashlib.sha256(raw).hexdigest()
    pinned = row.get("segment_sha256", "").strip()
    if pinned not in ("", "-") and digest != pinned:
        raise SystemExit(f"{segment_path}: sha256 {digest} != pinned {pinned}")
    print(digest)


COMMANDS = {
    "files": (cmd_files, 1),
    "segments": (cmd_segments, 3),
    "next-summary": (cmd_next_summary, 2),
    "check-headers": (cmd_check_headers, 6),
    "check-label": (cmd_check_label, 3),
    "check-segment": (cmd_check_segment, 4),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(__doc__)
    func, arity = COMMANDS[sys.argv[1]]
    if len(sys.argv) - 2 != arity:
        raise SystemExit(f"{sys.argv[1]} expects {arity} arguments")
    try:
        func(sys.argv[2:])
    except ck.CKError as error:
        raise SystemExit(f"invalid CK payload: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
