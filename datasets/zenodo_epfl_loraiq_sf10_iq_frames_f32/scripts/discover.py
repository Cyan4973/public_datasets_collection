#!/usr/bin/env python3
"""Derive the pinned LoRaIQ SF10 member selection from range-fetched metadata.

Inputs (fetched by discover.sh, never by this script):
  - the ZIP64 tail of sigmfs.zip (EOCD record, ZIP64 locator, ZIP64 EOCD),
  - the exact central-directory byte range named by the ZIP64 EOCD,
  - dataset.csv from the same Zenodo record.

Output: selection.tsv with, per selected recording, the byte range that
spans the .sigmf-data local header + deflated member + the adjacent
.sigmf-meta local header + member (ending right before the next member in
archive offset order), plus the central-directory CRC32 and sizes.

Selection rule: rows with sf=10, cr=1, fc=862.5, bandwidth=250000,
rx_sample_rate=500000 (one frame per file). Stratify by (session, rrh),
sort each stratum by integer file number, and take PER_STRATUM files at
positions floor((k + 0.5) * N / PER_STRATUM).
"""
from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import defaultdict
from pathlib import Path

ARCHIVE_BYTES = 49_746_561_196
EXPECTED_ENTRIES = 143_275
EXPECTED_CD_SIZE = 17_305_251
EXPECTED_CD_OFFSET = 49_729_255_847
PER_STRATUM = 4
CONFIG = {"sf": "10", "cr": "1", "fc": "862.5", "bandwidth": "250000", "rx_sample_rate": "500000"}

COLUMNS = [
    "session", "rrh", "file_no", "area_type", "snr", "frame_n_samples",
    "range_start", "range_end",
    "data_name", "data_offset", "data_crc32", "data_csize", "data_usize",
    "meta_name", "meta_offset", "meta_crc32", "meta_csize", "meta_usize",
]


def parse_tail(tail: bytes) -> tuple[int, int, int]:
    base = ARCHIVE_BYTES - len(tail)
    loc = tail.rfind(b"PK\x06\x07")
    if loc < 0:
        raise SystemExit("ZIP64 EOCD locator not found in tail")
    _, _, z64_offset, _ = struct.unpack_from("<4sIQI", tail, loc)
    rel = z64_offset - base
    if rel < 0 or tail[rel:rel + 4] != b"PK\x06\x06":
        raise SystemExit("ZIP64 EOCD record not at locator offset")
    fields = struct.unpack_from("<4sQ2H2I4Q", tail, rel)
    entries, cd_size, cd_offset = fields[7], fields[8], fields[9]
    return entries, cd_size, cd_offset


def parse_cd(cd: bytes) -> list[tuple]:
    out = []
    pos = 0
    while pos < len(cd):
        (sig, _vm, _vn, flags, method, _mt, _md, crc, csize, usize, nlen, elen, clen,
         _dn, _ia, _ea, offset) = struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, pos)
        if sig != 0x02014B50:
            raise SystemExit(f"bad central-directory signature at {pos}")
        name = cd[pos + 46:pos + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
        extra = cd[pos + 46 + nlen:pos + 46 + nlen + elen]
        q = 0
        while q + 4 <= len(extra):
            hid, hsz = struct.unpack_from("<HH", extra, q)
            if hid == 1:
                r = q + 4
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack_from("<Q", extra, r)[0]
                    r += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack_from("<Q", extra, r)[0]
                    r += 8
                if offset == 0xFFFFFFFF:
                    offset = struct.unpack_from("<Q", extra, r)[0]
                    r += 8
            q += 4 + hsz
        out.append((name, flags, method, crc, csize, usize, offset))
        pos += 46 + nlen + elen + clen
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", required=True, type=Path)
    ap.add_argument("--cd", required=True, type=Path)
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    entries, cd_size, cd_offset = parse_tail(args.tail.read_bytes())
    if (entries, cd_size, cd_offset) != (EXPECTED_ENTRIES, EXPECTED_CD_SIZE, EXPECTED_CD_OFFSET):
        raise SystemExit(f"ZIP64 EOCD changed: {entries} {cd_size} {cd_offset}")
    cd = args.cd.read_bytes()
    if len(cd) != cd_size:
        raise SystemExit("central directory length mismatch")
    members = parse_cd(cd)
    if len(members) != entries:
        raise SystemExit(f"parsed {len(members)} entries, expected {entries}")
    by_name = {m[0]: m for m in members}
    offsets = sorted(m[6] for m in members)
    next_offset = {offsets[i]: (offsets[i + 1] if i + 1 < len(offsets) else cd_offset) for i in range(len(offsets))}

    with args.csv.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if all(r[k] == v for k, v in CONFIG.items())]
    strata: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    seen = set()
    for r in rows:
        parts = r["sigmf_file"].split("/")
        if len(parts) != 5 or parts[:2] != [".", "sigmfs"]:
            raise SystemExit(f"unexpected sigmf_file {r['sigmf_file']!r}")
        if r["sigmf_file"] in seen:
            raise SystemExit(f"file referenced by more than one SF10 frame: {r['sigmf_file']}")
        seen.add(r["sigmf_file"])
        strata[(parts[2], parts[3])].append((int(parts[4]), r))

    selected = []
    for key in sorted(strata):
        items = sorted(strata[key], key=lambda t: t[0])
        n = len(items)
        take = min(PER_STRATUM, n)
        picks = sorted({int((k + 0.5) * n / take) for k in range(take)})
        for idx in picks:
            file_no, r = items[idx]
            base = r["sigmf_file"][2:]
            d = by_name[base + ".sigmf-data"]
            m = by_name[base + ".sigmf-meta"]
            for mem in (d, m):
                if mem[1] & 0x8 or mem[2] != 8:
                    raise SystemExit(f"unexpected flags/method for {mem[0]}: {mem[1]} {mem[2]}")
            if next_offset[d[6]] != m[6]:
                raise SystemExit(f"meta member does not directly follow data member for {base}")
            selected.append({
                "session": key[0], "rrh": key[1], "file_no": file_no,
                "area_type": r["area_type"], "snr": r["snr"],
                "frame_n_samples": r["sigmf_file_n_samples"],
                "range_start": d[6], "range_end": next_offset[m[6]] - 1,
                "data_name": d[0], "data_offset": d[6], "data_crc32": f"{d[3]:08x}",
                "data_csize": d[4], "data_usize": d[5],
                "meta_name": m[0], "meta_offset": m[6], "meta_crc32": f"{m[3]:08x}",
                "meta_csize": m[4], "meta_usize": m[5],
            })
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for s in selected:
            handle.write("\t".join(str(s[c]) for c in COLUMNS) + "\n")
    range_bytes = sum(s["range_end"] - s["range_start"] + 1 for s in selected)
    data_bytes = sum(s["data_usize"] for s in selected)
    print(f"config_rows={len(rows)} strata={len(strata)} selected={len(selected)} "
          f"range_bytes={range_bytes} data_bytes={data_bytes}", file=sys.stderr)


if __name__ == "__main__":
    main()
