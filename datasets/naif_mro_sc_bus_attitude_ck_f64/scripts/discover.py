#!/usr/bin/env python3
"""Metadata-only discovery that produced sources.tsv (run via discover.sh).

Selection rule (documented in README.md):

1. Parse the PDS volume MROSP_1000 data/ck directory listing and keep names
   matching ^mro_sc_psp_YYMMDD_yymmdd(_vN)?.bc$ (weekly reconstructed
   spacecraft-bus CKs; predicted ...p.bc files never match).
2. Per week (YYMMDD start), keep the highest archived version.
3. Per calendar year 2007..2017, keep the first week. The window stops
   before 2018, when MRO moved routine attitude determination to
   star-tracker-only "all-stellar" mode and the rate channel stopped being
   IMU-gyro based.
4. Walk the DAF summary chain (file record + every summary record, a few KB
   per file) on the PDS archive and on the USGS Astrogeology mirror; require
   identical segment descriptors on both.
5. Take segment ordinals floor(i*M/K), i = 0..K-1 (K = 4, M = segments in
   the file), spreading the samples across the week while keeping whole
   natural segments.

Network I/O goes through curl (respecting ~/.curlrc); Python only parses.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ck_type3 as ck  # noqa: E402

PDS_BASE = "https://naif.jpl.nasa.gov/pub/naif/pds/data/mro-m-spice-6-v1.0/mrosp_1000/data/ck"
MIRROR_BASE = "https://asc-isisdata.s3.us-west-2.amazonaws.com/usgs_data/mro/kernels/ck"
NAME_RE = re.compile(r"^mro_sc_psp_(\d{6})_(\d{6})(?:_v(\d+))?\.bc$")
FIRST_YEAR = 2007
LAST_YEAR = 2017
SEGMENTS_PER_FILE = 4
COLUMNS = [
    "year",
    "file_name",
    "segment_ordinal",
    "segment_count",
    "n_records",
    "nints",
    "sclk_begin",
    "sclk_end",
    "pds_size_bytes",
    "pds_start_word",
    "pds_end_word",
    "mirror_size_bytes",
    "mirror_start_word",
    "mirror_end_word",
    "label_sha256",
    "segment_sha256",
]


def curl_range(url: str, first: int, last: int) -> tuple[bytes, int]:
    proc = subprocess.run(
        ["curl", "-sS", "-f", "-L", "--max-time", "120", "--retry", "3", "-r", f"{first}-{last}", "-D", "-", "-o", "-", url],
        capture_output=True,
        check=True,
    )
    blob = proc.stdout
    # Split header blocks (proxy CONNECT + final response) from the body.
    total = None
    body_start = 0
    pos = 0
    while True:
        end = blob.find(b"\r\n\r\n", pos)
        if end < 0 or not blob[pos:].startswith(b"HTTP/"):
            break
        head = blob[pos:end].decode("latin-1")
        match = re.search(r"(?im)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)", head)
        if match:
            total = int(match.group(3))
        pos = end + 4
        body_start = pos
    body = blob[body_start:]
    if len(body) != last - first + 1:
        raise SystemExit(f"short range from {url}: wanted {last - first + 1}, got {len(body)}")
    if total is None:
        raise SystemExit(f"no Content-Range total from {url}")
    return body, total


def curl_small(url: str) -> bytes:
    return subprocess.run(["curl", "-sS", "-f", "-L", "--max-time", "120", "--retry", "3", url], capture_output=True, check=True).stdout


def summary_chain(url: str) -> dict:
    record, size = curl_range(url, 0, ck.DAF_RECORD_BYTES - 1)
    header = ck.parse_file_record(record)
    summaries = []
    number = header["fward"]
    previous = 0
    while number:
        rec, _ = curl_range(url, (number - 1) * 1024, number * 1024 - 1)
        parsed = ck.parse_summary_record(rec, header["endian"], number)
        if parsed["prev"] != previous:
            raise SystemExit(f"{url}: broken PREV pointer in summary record {number}")
        summaries.extend(parsed["summaries"])
        previous = number
        number = parsed["next"]
    if previous != header["bward"]:
        raise SystemExit(f"{url}: summary chain does not end at BWARD")
    for ordinal, item in enumerate(summaries):
        ck.check_summary_identity(item, f"{url} segment {ordinal}")
        if item["end_word"] * 8 > size:
            raise SystemExit(f"{url}: segment {ordinal} beyond end of file")
    return {"size": size, "header": header, "summaries": summaries}


def select_files(listing_html: str) -> list[tuple[int, str]]:
    names = set(re.findall(r'href="(mro_sc_psp_[^"/]+\.bc)"', listing_html))
    weeks: dict[str, tuple[int, str]] = {}
    for name in names:
        match = NAME_RE.match(name)
        if not match:
            continue
        version = int(match.group(3) or 1)
        week = match.group(1)
        if week not in weeks or version > weeks[week][0]:
            weeks[week] = (version, name)
    chosen = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        prefix = f"{year % 100:02d}"
        candidates = sorted(week for week in weeks if week.startswith(prefix))
        if not candidates:
            raise SystemExit(f"no weekly bus CK found for {year}")
        chosen.append((year, weeks[candidates[0]][1]))
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listing", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    files = select_files(args.listing.read_text(encoding="utf-8", errors="replace"))
    rows = []
    for year, name in files:
        pds = summary_chain(f"{PDS_BASE}/{name}")
        mirror = summary_chain(f"{MIRROR_BASE}/{name}")
        if len(pds["summaries"]) != len(mirror["summaries"]):
            raise SystemExit(f"{name}: segment count differs between PDS and mirror")
        label_name = name[:-3] + ".lbl"
        label = curl_small(f"{PDS_BASE}/{label_name}")
        label_text = label.decode("ascii", errors="replace")
        for needle in ('DATA_SET_ID                  = "MRO-M-SPICE-6-V1.0"', "NAIF_INSTRUMENT_ID           = -74000", f'PRODUCT_ID                   = "{name}"', "PRODUCT_VERSION_TYPE         = ACTUAL"):
            if needle not in label_text:
                raise SystemExit(f"{label_name}: missing {needle!r}")
        m = len(pds["summaries"])
        ordinals = sorted({(i * m) // SEGMENTS_PER_FILE for i in range(SEGMENTS_PER_FILE)})
        for ordinal in ordinals:
            a = pds["summaries"][ordinal]
            b = mirror["summaries"][ordinal]
            same = (a["sclk_begin"], a["sclk_end"], a["end_word"] - a["start_word"]) == (b["sclk_begin"], b["sclk_end"], b["end_word"] - b["start_word"])
            if not same:
                raise SystemExit(f"{name} segment {ordinal}: PDS and mirror descriptors differ")
            trailer, _ = curl_range(f"{PDS_BASE}/{name}", (a["end_word"] - 2) * 8, a["end_word"] * 8 - 1)
            nints, n = ck.decode_words(trailer, pds["header"]["endian"])
            n, nints = int(n), int(nints)
            if ck.type3_expected_length(n, nints) != a["end_word"] - a["start_word"] + 1:
                raise SystemExit(f"{name} segment {ordinal}: trailer (N={n}, NINTS={nints}) inconsistent with length")
            rows.append(
                {
                    "year": year,
                    "file_name": name,
                    "segment_ordinal": ordinal,
                    "segment_count": m,
                    "n_records": n,
                    "nints": nints,
                    "sclk_begin": repr(a["sclk_begin"]),
                    "sclk_end": repr(a["sclk_end"]),
                    "pds_size_bytes": pds["size"],
                    "pds_start_word": a["start_word"],
                    "pds_end_word": a["end_word"],
                    "mirror_size_bytes": mirror["size"],
                    "mirror_start_word": b["start_word"],
                    "mirror_end_word": b["end_word"],
                    "label_sha256": hashlib.sha256(label).hexdigest(),
                    "segment_sha256": "-",  # filled in after the first realized download
                }
            )
        print(f"{year} {name} segments={m} chosen={ordinals} pds_size={pds['size']} mirror_size={mirror['size']}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(str(row[c]) for c in COLUMNS) + "\n")
    print(f"wrote {len(rows)} segment rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
