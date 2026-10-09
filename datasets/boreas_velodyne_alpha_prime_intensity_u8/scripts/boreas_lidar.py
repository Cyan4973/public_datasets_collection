#!/usr/bin/env python3
"""Boreas Velodyne Alpha Prime sweep helper (pure standard library).

Boreas `lidar/<timestamp_us>.bin` files hold N points x 6 little-endian
float32 fields: x, y, z (m, sensor frame), intensity (calibrated 8-bit
reflectivity stored as an exactly integral float), laser_number (ring
0..127) and time (s, offset relative to the timestamp in the file name).
See pyboreas `load_lidar` ("[x, y, z, intensity, laser_number, time]").

Subcommands
  self-test        exercise the parser/validator on synthetic sweeps
  parse-listing    parse one S3 ListObjectsV2 XML page, append rows, print the
                   URL-encoded continuation token (empty when done)
  select           pick evenly spaced sweeps per sequence from listing TSVs
  check-payloads   validate downloaded sweeps against sources.tsv
  check-file       validate one downloaded sweep (size, MD5, semantics)

Validation policy (shared by download, build and verify): the file size must
be a positive multiple of 24, every field must be finite, intensity must be
an integer in 0..255 and laser_number an integer in 0..127. Any violation is
fatal; nothing is clamped, dropped or imputed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import sys
import urllib.parse
from array import array
from pathlib import Path

POINT_FIELDS = 6
POINT_BYTES = 24
INTENSITY_FIELD = 3
RING_FIELD = 4
TIME_FIELD = 5
MIN_POINTS = 50_000
SEQ_RE = re.compile(r"^boreas-(2020-1[12]|2021-(0[1-9]|1[01]))-\d{2}-\d{2}-\d{2}$")
KEY_RE = re.compile(r"^(boreas-\d{4}-\d{2}-\d{2}-\d{2}-\d{2})/lidar/(\d{16})\.bin$")
SOURCES_FIELDS = ["sequence", "timestamp_us", "key", "size_bytes", "md5", "point_count",
                  "sequence_sweep_index", "sequence_sweep_count"]


def float_array(raw: bytes) -> array:
    values = array("f")
    if values.itemsize != 4:
        raise SystemExit("platform float is not 32-bit")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def decode_sweep(raw: bytes, label: str = "sweep") -> dict:
    """Validate one sweep and return intensity bytes plus diagnostics.

    Raises ValueError on any policy violation.
    """
    if len(raw) == 0 or len(raw) % POINT_BYTES != 0:
        raise ValueError(f"{label}: size {len(raw)} is not a positive multiple of {POINT_BYTES}")
    n = len(raw) // POINT_BYTES
    if n < MIN_POINTS:
        raise ValueError(f"{label}: only {n} points (< {MIN_POINTS})")
    values = float_array(raw)
    # |values| are far below 1e30, so a finite float64 sum proves every field finite.
    total = sum(values)
    if not math.isfinite(total):
        bad = sum(1 for v in values if not math.isfinite(v))
        raise ValueError(f"{label}: {bad} non-finite fields")
    inten = values[INTENSITY_FIELD::POINT_FIELDS]
    ring = values[RING_FIELD::POINT_FIELDS]
    tim = values[TIME_FIELD::POINT_FIELDS]
    out = bytearray(n)
    hist = [0] * 256
    for i, v in enumerate(inten):
        iv = int(v)
        if iv != v or iv < 0 or iv > 255:
            raise ValueError(f"{label}: point {i} intensity {v!r} is not an integer in 0..255")
        out[i] = iv
        hist[iv] += 1
    rings = set()
    for i, v in enumerate(ring):
        iv = int(v)
        if iv != v or iv < 0 or iv > 127:
            raise ValueError(f"{label}: point {i} laser_number {v!r} is not an integer in 0..127")
        rings.add(iv)
    return {
        "point_count": n,
        "intensity": bytes(out),
        "hist": hist,
        "distinct_rings": len(rings),
        "ring_min": min(rings),
        "ring_max": max(rings),
        "time_min": min(tim),
        "time_max": max(tim),
    }


def synth_sweep(n: int, intensity_fn, ring_fn) -> bytes:
    vals = array("f")
    for i in range(n):
        vals.extend([1.5 + i * 1e-3, -2.0, 0.25, float(intensity_fn(i)), float(ring_fn(i)), i * 1e-6])
    if sys.byteorder != "little":
        vals.byteswap()
    return vals.tobytes()


def cmd_self_test(_args) -> int:
    n = MIN_POINTS + 7
    raw = synth_sweep(n, lambda i: (i * 37) % 256, lambda i: i % 128)
    res = decode_sweep(raw, "synthetic")
    assert res["point_count"] == n
    assert res["intensity"] == bytes((i * 37) % 256 for i in range(n))
    assert res["distinct_rings"] == 128 and res["ring_max"] == 127
    assert sum(res["hist"]) == n
    failures = 0
    bad_cases = {
        "truncated": raw[:-5],
        "fractional_intensity": synth_sweep(n, lambda i: 3.5 if i == 11 else 4, lambda i: 0),
        "negative_intensity": synth_sweep(n, lambda i: -1 if i == 2 else 4, lambda i: 0),
        "over_255": synth_sweep(n, lambda i: 256 if i == 99 else 4, lambda i: 0),
        "bad_ring": synth_sweep(n, lambda i: 4, lambda i: 128 if i == 5 else 0),
        "nan": synth_sweep(n, lambda i: float("nan") if i == 3 else 4, lambda i: 0),
        "too_few_points": synth_sweep(100, lambda i: 4, lambda i: 0),
    }
    for name, payload in bad_cases.items():
        try:
            decode_sweep(payload, name)
        except ValueError:
            continue
        print(f"self-test: case {name} was not rejected", file=sys.stderr)
        failures += 1
    if failures:
        return 1
    print(f"self-test ok (synthetic sweep of {n} points; {len(bad_cases)} invalid cases rejected)")
    return 0


def cmd_parse_listing(args) -> int:
    text = Path(args.xml).read_text(encoding="utf-8")
    if "<ListBucketResult" not in text:
        raise SystemExit(f"{args.xml}: not a ListBucketResult page")
    rows = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
        key = re.search(r"<Key>([^<]*)</Key>", block).group(1)
        size = int(re.search(r"<Size>(\d+)</Size>", block).group(1))
        etag = re.search(r"<ETag>([^<]*)</ETag>", block).group(1).replace("&quot;", "").strip('"')
        rows.append((key, size, etag))
    with open(args.append, "a", encoding="utf-8") as handle:
        for key, size, etag in rows:
            handle.write(f"{key}\t{size}\t{etag}\n")
    truncated = re.search(r"<IsTruncated>(true|false)</IsTruncated>", text).group(1) == "true"
    token = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", text)
    if truncated:
        if not token:
            raise SystemExit(f"{args.xml}: truncated page without continuation token")
        print(urllib.parse.quote(token.group(1).replace("&amp;", "&"), safe=""))
    else:
        print("")
    return 0


def cmd_select(args) -> int:
    per_seq = args.per_sequence
    out_rows = []
    sequences = []
    for path in sorted(Path(args.listing_dir).glob("*.tsv")):
        seq = path.stem
        if not SEQ_RE.match(seq):
            raise SystemExit(f"unexpected sequence listing {seq}")
        sweeps = []
        for line in path.read_text(encoding="utf-8").splitlines():
            key, size, etag = line.split("\t")
            m = KEY_RE.match(key)
            if not m or m.group(1) != seq:
                raise SystemExit(f"{seq}: unexpected key {key}")
            if not re.fullmatch(r"[0-9a-f]{32}", etag):
                raise SystemExit(f"{seq}: multipart or odd ETag {etag} for {key}")
            size = int(size)
            if size % POINT_BYTES:
                raise SystemExit(f"{seq}: {key} size {size} not a multiple of {POINT_BYTES}")
            sweeps.append((m.group(2), key, size, etag))
        sweeps.sort()
        n = len(sweeps)
        if n < per_seq * 10:
            raise SystemExit(f"{seq}: only {n} sweeps")
        sequences.append((seq, n))
        for k in range(per_seq):
            idx = ((2 * k + 1) * n) // (2 * per_seq)
            ts, key, size, etag = sweeps[idx]
            out_rows.append({
                "sequence": seq, "timestamp_us": ts, "key": key, "size_bytes": size, "md5": etag,
                "point_count": size // POINT_BYTES, "sequence_sweep_index": idx,
                "sequence_sweep_count": n,
            })
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCES_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)
    total = sum(r["size_bytes"] for r in out_rows)
    print(f"sequences={len(sequences)} selected={len(out_rows)} bytes={total} "
          f"points={sum(r['point_count'] for r in out_rows)}")
    for seq, n in sequences:
        print(f"  {seq} sweeps={n}")
    return 0


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != SOURCES_FIELDS:
        raise SystemExit(f"{path}: unexpected header")
    for row in rows:
        for key in ("size_bytes", "point_count", "sequence_sweep_index", "sequence_sweep_count"):
            row[key] = int(row[key])
        if not SEQ_RE.match(row["sequence"]):
            raise SystemExit(f"{path}: sequence {row['sequence']} outside the 2020-11..2021-11 Alpha Prime era")
        m = KEY_RE.match(row["key"])
        if not m or m.group(1) != row["sequence"] or m.group(2) != row["timestamp_us"]:
            raise SystemExit(f"{path}: inconsistent key {row['key']}")
    return rows


def local_path(download_dir: Path, row: dict) -> Path:
    return download_dir / row["sequence"] / f"{row['timestamp_us']}.bin"


def check_one(path: Path, row: dict, semantic: bool = True) -> str | None:
    if not path.is_file():
        return "missing"
    size = path.stat().st_size
    if size != row["size_bytes"]:
        return f"size {size} != {row['size_bytes']}"
    raw = path.read_bytes()
    md5 = hashlib.md5(raw).hexdigest()
    if md5 != row["md5"]:
        return f"md5 {md5} != {row['md5']}"
    if semantic:
        try:
            decode_sweep(raw, row["key"])
        except ValueError as exc:
            return str(exc)
    return None


def cmd_check_file(args) -> int:
    rows = {r["key"]: r for r in load_sources(Path(args.sources))}
    row = rows.get(args.key)
    if row is None:
        raise SystemExit(f"key {args.key} not pinned")
    problem = check_one(Path(args.file), row)
    if problem:
        print(f"INVALID {args.key}: {problem}", file=sys.stderr)
        return 1
    return 0


def cmd_check_payloads(args) -> int:
    rows = load_sources(Path(args.sources))
    download_dir = Path(args.download_dir)
    bad = []
    for row in rows:
        # --list only needs a cheap check: size + MD5 (the semantic check ran at fetch time).
        problem = check_one(local_path(download_dir, row), row, semantic=not args.list)
        if problem:
            bad.append((row, problem))
    if args.list:
        for row, _ in bad:
            print(row["key"])
        return 0
    for row, problem in bad:
        print(f"INVALID {row['key']}: {problem}", file=sys.stderr)
    if bad:
        return 1
    print(f"payloads ok: {len(rows)} sweeps, {sum(r['size_bytes'] for r in rows)} bytes")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test")
    p = sub.add_parser("parse-listing")
    p.add_argument("--xml", required=True)
    p.add_argument("--append", required=True)
    p = sub.add_parser("select")
    p.add_argument("--listing-dir", required=True)
    p.add_argument("--per-sequence", type=int, default=6)
    p.add_argument("--out", required=True)
    p = sub.add_parser("check-payloads")
    p.add_argument("--sources", required=True)
    p.add_argument("--download-dir", required=True)
    p.add_argument("--list", action="store_true")
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("check-file")
    p.add_argument("--sources", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--file", required=True)
    args = parser.parse_args()
    return {
        "self-test": cmd_self_test,
        "parse-listing": cmd_parse_listing,
        "select": cmd_select,
        "check-payloads": cmd_check_payloads,
        "check-file": cmd_check_file,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
