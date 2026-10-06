#!/usr/bin/env python3
"""USAF RSTN Sagamore Hill Solar Radio Spectrograph (SRS) day-file helper.

Pure standard library. Network I/O is done by curl in the shell scripts; this
helper only parses what curl fetched.

SRS record layout (NCEI documentation/Srsdispl.doc, section 2.2): fixed
826-byte records with no separators.

    byte 0      year, last two digits (24 for 2024)
    bytes 1-5   month, day, hour, minute, second (UT, start of sweep)
    byte 6      site number (5 = Sagamore Hill)
    byte 7      number of bands (2)
    bytes 8-15  band A descriptor: >HHHBB start MHz, end MHz, bytes, ref, atten
    bytes 16-23 band B descriptor, same layout
    bytes 24-424   401 analyser levels, band A 25..75 MHz, increasing freq
    bytes 425-825  401 analyser levels, band B 75..180 MHz, increasing freq

Subcommands:
    parse-listing   list kYYMMDD.srs.gz names in an Apache index page
    probe           check a candidate day from a head range + tail range
    validate        full validation of one downloaded .gz day file
    build           emit per-band uint8 samples, aux time series and index
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

DATASET_ID = "noaa_rstn_sagamore_hill_srs_spectra_u8"
RECORD_BYTES = 826
HEADER_BYTES = 24
CHANNELS = 401
SITE = 5
NBANDS = 2
BAND_A = (25, 75, 401, 20, 0)
BAND_B = (75, 180, 401, 20, 0)
MIN_RECORDS = 5000
SERIES_A = "srs_band_a_25_75mhz_u8"
SERIES_B = "srs_band_b_75_180mhz_u8"
SERIES_T = "srs_sweep_start_utc_seconds_u32"
SOURCE_COLUMNS = [
    "requested_date",
    "selected_date",
    "filename",
    "url",
    "size_bytes",
    "last_modified",
    "gzip_crc32",
    "gzip_isize",
    "records",
    "first_sweep_utc",
    "sha256",
]


def die(message: str, code: int = 1) -> None:
    print(f"FATAL: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != SOURCE_COLUMNS:
        die(f"{path}: unexpected header {header}")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != len(header):
            die(f"{path}: bad row {line!r}")
        rows.append(dict(zip(header, parts)))
    return rows


def check_header(rec: bytes, allowed_dates: set[tuple[int, int, int]], where: str) -> tuple[int, int, int, int]:
    """Validate one 24-byte record header; return (y, m, d, seconds_of_day)."""
    yy, mo, dd, hh, mi, ss, site, nb = rec[:8]
    if site != SITE or nb != NBANDS:
        raise ValueError(f"{where}: site/nbands {site}/{nb} != {SITE}/{NBANDS}")
    band_a = struct.unpack(">HHHBB", rec[8:16])
    band_b = struct.unpack(">HHHBB", rec[16:24])
    if band_a != BAND_A or band_b != BAND_B:
        raise ValueError(f"{where}: band descriptors {band_a}/{band_b} != {BAND_A}/{BAND_B}")
    if (2000 + yy, mo, dd) not in allowed_dates:
        raise ValueError(f"{where}: header date {2000 + yy}-{mo:02d}-{dd:02d} not in {sorted(allowed_dates)}")
    if hh > 23 or mi > 59 or ss > 59:
        raise ValueError(f"{where}: invalid time {hh}:{mi}:{ss}")
    return 2000 + yy, mo, dd, hh * 3600 + mi * 60 + ss


def allowed_dates_for(day: dt.date) -> set[tuple[int, int, int]]:
    # A local-day file may run past 00 UT (Srsdispl.doc section 2.1).
    nxt = day + dt.timedelta(days=1)
    return {(day.year, day.month, day.day), (nxt.year, nxt.month, nxt.day)}


def sweep_seconds(day: dt.date, y: int, m: int, d: int, sod: int) -> int:
    return (dt.date(y, m, d) - day).days * 86400 + sod


def parse_day(raw: bytes, day: dt.date, label: str) -> dict:
    """Validate every record of a decompressed day file."""
    if len(raw) % RECORD_BYTES:
        raise ValueError(f"{label}: decompressed length {len(raw)} is not a multiple of {RECORD_BYTES}")
    n = len(raw) // RECORD_BYTES
    if n < MIN_RECORDS:
        raise ValueError(f"{label}: {n} records < minimum {MIN_RECORDS}")
    allowed = allowed_dates_for(day)
    times = []
    for i in range(n):
        y, m, d, sod = check_header(raw[i * RECORD_BYTES:i * RECORD_BYTES + HEADER_BYTES], allowed, f"{label} record {i}")
        times.append(sweep_seconds(day, y, m, d, sod))
    steps: dict[int, int] = {}
    for a, b in zip(times, times[1:]):
        steps[b - a] = steps.get(b - a, 0) + 1
    return {"records": n, "times": times, "steps": steps}


# ----------------------------------------------------------------- listing --

def cmd_parse_listing(args: argparse.Namespace) -> None:
    text = Path(args.html).read_text(encoding="utf-8", errors="replace")
    names = sorted(set(re.findall(r'href="(k7\d{6}\.srs\.gz)"', text)))
    prefix = f"k7{args.year % 100:02d}{args.month:02d}"
    for name in names:
        if name.startswith(prefix):
            print(name)


# ------------------------------------------------------------------- probe --

def parse_http_headers(path: Path) -> dict:
    """Return status and headers of the final response in a curl -D dump."""
    blocks = re.split(r"\r?\n\r?\n", path.read_text(encoding="latin-1").strip())
    final = [b for b in blocks if b.startswith("HTTP/")][-1]
    lines = final.splitlines()
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return {"status": status, "headers": headers}


def cmd_probe(args: argparse.Namespace) -> None:
    """Decide whether one candidate day file is acceptable; print a TSV row."""
    day = dt.date.fromisoformat(args.date)
    head = Path(args.head_bin).read_bytes()
    tail = Path(args.tail_bin).read_bytes()
    tail_hdr = parse_http_headers(Path(args.tail_headers))
    reason = None
    size = isize = crc = records = 0
    first = ""
    lm = tail_hdr["headers"].get("last-modified", "")
    try:
        if tail_hdr["status"] != 206:
            raise ValueError(f"tail range status {tail_hdr['status']}")
        m = re.match(r"bytes (\d+)-(\d+)/(\d+)", tail_hdr["headers"].get("content-range", ""))
        if not m or len(tail) != 8 or int(m.group(2)) - int(m.group(1)) != 7 or int(m.group(2)) + 1 != int(m.group(3)):
            raise ValueError("tail range is not the last 8 bytes")
        size = int(m.group(3))
        crc, isize = struct.unpack("<II", tail)
        if head[:3] != b"\x1f\x8b\x08":
            raise ValueError("not a gzip/deflate stream")
        part = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(head)
        if len(part) < 4 * RECORD_BYTES:
            raise ValueError("head range decompressed to fewer than 4 records")
        allowed = {(day.year, day.month, day.day)}
        for i in range(len(part) // RECORD_BYTES):
            check_header(part[i * RECORD_BYTES:i * RECORD_BYTES + HEADER_BYTES], allowed, f"head record {i}")
        hh, mi, ss = part[3:6]
        first = f"{hh:02d}:{mi:02d}:{ss:02d}"
        if isize % RECORD_BYTES:
            raise ValueError(f"gzip ISIZE {isize} not a multiple of {RECORD_BYTES}")
        records = isize // RECORD_BYTES
        if records < MIN_RECORDS:
            raise ValueError(f"{records} records < {MIN_RECORDS}")
    except (ValueError, zlib.error, IndexError) as exc:
        reason = str(exc)
    if reason:
        print(f"REJECT\t{args.date}\t{reason}")
    else:
        print(f"OK\t{size}\t{lm}\t{crc:08x}\t{isize}\t{records}\t{first}")


# ---------------------------------------------------------------- validate --

def validate_file(gz_path: Path, row: dict) -> tuple[bytes, dict]:
    label = row["filename"]
    blob = gz_path.read_bytes()
    if len(blob) != int(row["size_bytes"]):
        raise ValueError(f"{label}: size {len(blob)} != pinned {row['size_bytes']}")
    sha = hashlib.sha256(blob).hexdigest()
    if row["sha256"] != "-" and sha != row["sha256"]:
        raise ValueError(f"{label}: sha256 {sha} != pinned {row['sha256']}")
    try:
        raw = gzip.decompress(blob)  # verifies every member's CRC32 and ISIZE
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"{label}: gzip decode failed: {exc}") from exc
    if len(raw) != int(row["gzip_isize"]) or f"{zlib.crc32(raw):08x}" != row["gzip_crc32"]:
        raise ValueError(f"{label}: decompressed length/CRC32 differ from the pinned gzip trailer")
    day = dt.date.fromisoformat(row["selected_date"])
    info = parse_day(raw, day, label)
    if info["records"] != int(row["records"]):
        raise ValueError(f"{label}: {info['records']} records != pinned {row['records']}")
    hh, mi, ss = raw[3:6]
    if f"{hh:02d}:{mi:02d}:{ss:02d}" != row["first_sweep_utc"]:
        raise ValueError(f"{label}: first sweep time differs from pinned {row['first_sweep_utc']}")
    info["sha256"] = sha
    return raw, info


def cmd_validate(args: argparse.Namespace) -> None:
    rows = {r["filename"]: r for r in read_sources(Path(args.sources))}
    row = rows.get(args.filename) or die(f"{args.filename} not in sources")
    try:
        _, info = validate_file(Path(args.gz), row)
    except ValueError as exc:
        die(str(exc), 2)
    steps = sorted(info["steps"].items(), key=lambda kv: -kv[1])[:6]
    print(f"valid {args.filename} records={info['records']} sha256={info['sha256']} steps={steps}")


# ------------------------------------------------------------------- build --

def band_stats(plane: bytes) -> dict:
    hist = [0] * 256
    counts = {}
    for v in range(256):  # bytes.count runs in C; 256 passes stay fast
        c = plane.count(v)
        if c:
            counts[v] = c
            hist[v] = c
    total = len(plane)
    mean = sum(v * c for v, c in counts.items()) / total
    mode = max(counts.values())
    return {
        "min": min(counts),
        "max": max(counts),
        "mean": round(mean, 6),
        "distinct_codes": len(counts),
        "code0_fraction": round(hist[0] / total, 6),
        "code255_fraction": round(hist[255] / total, 6),
        "mode_fraction": round(mode / total, 6),
    }


def cmd_build(args: argparse.Namespace) -> None:
    downloads = Path(args.downloads)
    samples = Path(args.samples_dir)
    data_root = Path(args.data_root)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    rows = read_sources(Path(args.sources))
    for sid in (SERIES_A, SERIES_B, SERIES_T):
        (samples / sid).mkdir(parents=True, exist_ok=True)
        for old in (samples / sid).iterdir():
            old.unlink()
    index_rows = []
    stats = {"days": [], "totals": {}}
    for row in rows:
        try:
            raw, info = validate_file(downloads / row["filename"], row)
        except ValueError as exc:
            die(str(exc), 2)
        n = info["records"]
        mv = memoryview(raw)
        plane_a = b"".join(mv[i * RECORD_BYTES + 24:i * RECORD_BYTES + 425] for i in range(n))
        plane_b = b"".join(mv[i * RECORD_BYTES + 425:i * RECORD_BYTES + 826] for i in range(n))
        times = struct.pack(f"<{n}I", *info["times"])
        stem = "sagamore_hill_" + row["selected_date"].replace("-", "")
        common = {
            "dataset_id": DATASET_ID,
            "endianness": "little",
            "station": "Sagamore Hill (RSTN site 5)",
            "requested_date": row["requested_date"],
            "observing_date_local_file": row["selected_date"],
            "source_file": row["filename"],
            "source_url": row["url"],
            "source_sha256": info["sha256"],
            "records": n,
        }
        outputs = [
            (SERIES_A, f"{stem}_band_a.u8", plane_a, "uint", 8, 1,
             {"band": "A", "freq_first_mhz": 25.0, "freq_last_mhz": 75.0, "ref_level": 20, "attenuation_db": 0,
              "sample_shape": [n, CHANNELS], "sample_axes": ["sweep", "frequency_channel"]}),
            (SERIES_B, f"{stem}_band_b.u8", plane_b, "uint", 8, 1,
             {"band": "B", "freq_first_mhz": 75.0, "freq_last_mhz": 180.0, "ref_level": 20, "attenuation_db": 0,
              "sample_shape": [n, CHANNELS], "sample_axes": ["sweep", "frequency_channel"]}),
            (SERIES_T, f"{stem}_sweep_start_utc_s.u32", times, "uint", 32, 4,
             {"sample_shape": [n], "sample_axes": ["sweep"], "min": min(info["times"]), "max": max(info["times"]),
              "time_origin": f"{row['selected_date']}T00:00:00Z"}),
        ]
        for sid, name, payload, kind, width, elem, extra in outputs:
            path = samples / sid / name
            path.write_bytes(payload)
            entry = dict(common)
            entry.update({
                "series_id": sid,
                "sample_path": str(path.relative_to(data_root)),
                "numeric_kind": kind,
                "bit_width": width,
                "element_size_bytes": elem,
                "sample_size_bytes": len(payload),
                "value_count": len(payload) // elem,
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
            if width == 8:
                entry.update(band_stats(payload))
            entry.update(extra)
            index_rows.append(entry)
        steps = sorted(info["steps"].items(), key=lambda kv: -kv[1])
        stats["days"].append({
            "date": row["selected_date"], "requested": row["requested_date"], "records": n,
            "first_sweep_s": info["times"][0], "last_sweep_s": info["times"][-1],
            "step_histogram_top": steps[:8],
            "non_increasing_steps": sum(c for s, c in info["steps"].items() if s <= 0),
        })
        print(f"built {row['selected_date']} records={n} band_a={len(plane_a)} band_b={len(plane_b)}")
    index_rows.sort(key=lambda r: r["sample_path"])
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as fh:
        for entry in index_rows:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    for sid in (SERIES_A, SERIES_B, SERIES_T):
        sel = [r for r in index_rows if r["series_id"] == sid]
        stats["totals"][sid] = {"samples": len(sel), "bytes": sum(r["sample_size_bytes"] for r in sel),
                                "values": sum(r["value_count"] for r in sel)}
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(stats["totals"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse-listing")
    p.add_argument("--html", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int, required=True)
    p.set_defaults(func=cmd_parse_listing)
    p = sub.add_parser("probe")
    p.add_argument("--date", required=True)
    p.add_argument("--head-bin", required=True)
    p.add_argument("--tail-bin", required=True)
    p.add_argument("--tail-headers", required=True)
    p.set_defaults(func=cmd_probe)
    p = sub.add_parser("validate")
    p.add_argument("--sources", required=True)
    p.add_argument("--filename", required=True)
    p.add_argument("--gz", required=True)
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("build")
    for name in ("--sources", "--downloads", "--samples-dir", "--index", "--stats", "--data-root"):
        p.add_argument(name, required=True)
    p.set_defaults(func=cmd_build)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
