#!/usr/bin/env python3
"""GazeBase EyeLink 1000 gaze-position recipe helper (pure standard library).

Subcommands:
  check-api   validate the figshare article JSON (identity, license, file pins)
  extract     validate one outer-ZIP byte range and write the inflated inner
              per-subject ZIP
  check-inner validate an already extracted inner per-subject ZIP
  build       emit one little-endian float64 sample per recording CSV and series
  verify      independently re-derive every sample and check index/manifest

Missing-value policy (shared by build and verify): the literal token "NaN" in
the x or y column (EyeLink track loss / blink; val == 4 in the source) is kept
in place as the canonical IEEE-754 quiet NaN 0x7FF8000000000000, so each
sample keeps the 1 kHz row alignment of its recording. A recording is excluded
(both series) only if a series has fewer than MIN_FINITE finite values or a NaN
fraction above MAX_NAN_FRACTION. Any other non-numeric token, an inf, or a
decimal that does not round-trip through float64 is fatal.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import struct
import sys
import tomllib
import zipfile
import zlib
from decimal import Decimal
from pathlib import Path

DATASET_ID = "gazebase_eyelink1000_gaze_position_f64"
ARTICLE_ID = 12912257
FILE_ID = 27039812
FILE_NAME = "GazeBase_v2_0.zip"
FILE_BYTES = 6710984652
FILE_MD5 = "cb7eb895fb48f8661decf038ab998c9a"
SERIES = (("gaze_x_deg_f64", "x"), ("gaze_y_deg_f64", "y"))
NAN_BYTES = struct.pack("<d", float("nan"))
MIN_FINITE = 1000
MAX_NAN_FRACTION = 0.5
CSV_NAME_RE = re.compile(
    r"^S(?P<session>[12])/S(?P=session)_(?P<taskdir>[A-Za-z0-9_]+)/"
    r"S_(?P<subject>\d{4})_S(?P=session)_(?P<task>[A-Z0-9]{3})\.csv$"
)
TASKS = {"BLG", "FXS", "HSS", "RAN", "TEX", "VD1", "VD2"}
REQUIRED_COLUMNS = {"n", "x", "y", "val", "dP", "lab", "xT", "yT"}


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def read_pins(path: Path) -> list[dict]:
    pins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, offset, span, comp, uncomp, crc = line.split("\t")
        pins.append(
            dict(
                name=name,
                offset=int(offset),
                span=int(span),
                compressed=int(comp),
                uncompressed=int(uncomp),
                crc32=int(crc, 16),
            )
        )
    if not pins:
        fail("no pinned members")
    return pins


# ---------------------------------------------------------------- download side


def cmd_check_api(args: argparse.Namespace) -> None:
    record = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if int(record.get("id") or 0) != ARTICLE_ID:
        fail(f"unexpected article id {record.get('id')!r}")
    if "GazeBase" not in str(record.get("title", "")):
        fail(f"article title changed: {record.get('title')!r}")
    lic = record.get("license") or {}
    if lic.get("name") != "CC BY 4.0" or "creativecommons.org/licenses/by/4.0" not in str(lic.get("url")):
        fail(f"article license changed: {lic!r}")
    files = [f for f in record.get("files") or [] if int(f.get("id") or 0) == FILE_ID]
    if len(files) != 1:
        fail(f"expected one file id {FILE_ID}, found {len(files)}")
    item = files[0]
    if item.get("name") != FILE_NAME or int(item.get("size") or 0) != FILE_BYTES:
        fail(f"bulk file identity changed: {item.get('name')!r} {item.get('size')!r}")
    if str(item.get("computed_md5") or item.get("supplied_md5")).lower() != FILE_MD5:
        fail(f"bulk file md5 changed: {item.get('computed_md5')!r}")
    print(
        f"api_validation=ok article={ARTICLE_ID} version={record.get('version')} "
        f"license=CC-BY-4.0 file={FILE_NAME} bytes={FILE_BYTES} md5={FILE_MD5}"
    )


def check_inner_bytes(inner: bytes, subject_name: str) -> int:
    subject = re.search(r"Subject_(\d{4})\.zip$", subject_name).group(1)
    zf = zipfile.ZipFile(io.BytesIO(inner))
    bad = zf.testzip()
    if bad is not None:
        fail(f"{subject_name}: inner CRC failure at {bad}")
    csvs = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        m = CSV_NAME_RE.match(info.filename)
        if not m or m.group("subject") != subject or m.group("task") not in TASKS:
            fail(f"{subject_name}: unexpected inner member {info.filename!r}")
        with zf.open(info) as handle:
            header = handle.readline().decode("ascii").strip().split(",")
        if set(header) != REQUIRED_COLUMNS or len(header) != len(REQUIRED_COLUMNS):
            fail(f"{subject_name}:{info.filename}: unexpected header {header!r}")
        csvs += 1
    if csvs == 0:
        fail(f"{subject_name}: no recording CSVs")
    return csvs


def cmd_extract(args: argparse.Namespace) -> None:
    pin = next((p for p in read_pins(Path(args.pins)) if p["name"] == args.member), None)
    if pin is None:
        fail(f"member not pinned: {args.member}")
    start, end = pin["offset"], pin["offset"] + pin["span"] - 1
    headers = Path(args.headers).read_text(encoding="iso-8859-1")
    responses = [r for r in re.split(r"(?=^HTTP/)", headers, flags=re.MULTILINE) if r.strip()]
    final = responses[-1] if responses else ""
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    crange = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.I | re.M)
    if not status or int(status.group(1)) != 206 or not crange:
        fail(f"{args.member}: server did not answer 206 with Content-Range")
    if tuple(map(int, crange.groups())) != (start, end, FILE_BYTES):
        fail(f"{args.member}: unexpected Content-Range {crange.groups()}")
    payload = Path(args.range_file).read_bytes()
    if len(payload) != pin["span"] or payload[:4] != b"PK\x03\x04":
        fail(f"{args.member}: invalid range payload ({len(payload)} bytes)")
    (_, _, flags, method, _, _, crc, csize, usize, nlen, elen) = struct.unpack_from("<4s5H3I2H", payload, 0)
    name = payload[30 : 30 + nlen].decode("cp437")
    data_off = 30 + nlen + elen
    if (
        name != pin["name"]
        or flags != 0
        or method != 8
        or crc != pin["crc32"]
        or csize != pin["compressed"]
        or usize != pin["uncompressed"]
        or data_off + csize != len(payload)
    ):
        fail(f"{args.member}: local header mismatch name={name!r} flags={flags} method={method}")
    dec = zlib.decompressobj(-zlib.MAX_WBITS)
    inner = dec.decompress(payload[data_off:]) + dec.flush()
    if not dec.eof or dec.unused_data:
        fail(f"{args.member}: DEFLATE stream did not end at member boundary")
    if len(inner) != pin["uncompressed"] or zlib.crc32(inner) != pin["crc32"]:
        fail(f"{args.member}: inflated size/CRC mismatch")
    csvs = check_inner_bytes(inner, pin["name"])
    Path(args.output).write_bytes(inner)
    print(f"member_validation=ok member={pin['name']} bytes={len(inner)} crc32={pin['crc32']:08x} csvs={csvs}")


def cmd_check_inner(args: argparse.Namespace) -> None:
    pin = next((p for p in read_pins(Path(args.pins)) if p["name"] == args.member), None)
    if pin is None:
        fail(f"member not pinned: {args.member}")
    inner = Path(args.path).read_bytes()
    if len(inner) != pin["uncompressed"] or zlib.crc32(inner) != pin["crc32"]:
        fail(f"{args.member}: cached inner zip size/CRC mismatch")
    csvs = check_inner_bytes(inner, pin["name"])
    print(f"cache_hit member={pin['name']} bytes={len(inner)} crc32={pin['crc32']:08x} csvs={csvs}")


# ---------------------------------------------------------------- build side


def iter_recordings(downloads: Path, pins: list[dict]):
    for pin in pins:
        path = downloads / pin["name"]
        inner = path.read_bytes()
        if len(inner) != pin["uncompressed"] or zlib.crc32(inner) != pin["crc32"]:
            fail(f"{path}: local inner zip does not match pin; re-run download.sh")
        zf = zipfile.ZipFile(io.BytesIO(inner))
        for info in sorted((i for i in zf.infolist() if not i.is_dir()), key=lambda i: i.filename):
            m = CSV_NAME_RE.match(info.filename)
            if not m:
                fail(f"unexpected member {info.filename}")
            yield pin["name"], info.filename, m, zf.read(info).decode("ascii")


def parse_build(text: str, label: str):
    """Build-side parser: plain line splitting with a header map."""
    lines = text.splitlines()
    header = lines[0].split(",")
    ix, iy, i_n = header.index("x"), header.index("y"), header.index("n")
    cols = ([], [])
    nan_counts = [0, 0]
    gaps = 0
    expected_n = 0
    for lineno, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != len(header):
            fail(f"{label}:{lineno}: field count {len(parts)} != {len(header)}")
        n = int(parts[i_n])
        if n != expected_n:
            gaps += 1
        expected_n = n + 1
        for k, idx in enumerate((ix, iy)):
            token = parts[idx]
            if token == "NaN":
                cols[k].append(math.nan)
                nan_counts[k] += 1
                continue
            value = float(token)
            if not math.isfinite(value):
                fail(f"{label}:{lineno}: non-finite token {token!r}")
            if repr(value) != token and Decimal(repr(value)) != Decimal(token):
                fail(f"{label}:{lineno}: {token!r} does not round-trip through float64")
            cols[k].append(value)
    return cols, nan_counts, gaps


def pack(values: list[float]) -> bytes:
    out = bytearray(struct.pack(f"<{len(values)}d", *values))
    # canonicalize NaN bit patterns (struct already emits 0x7FF8..., enforce anyway)
    for i, v in enumerate(values):
        if v != v:
            out[8 * i : 8 * i + 8] = NAN_BYTES
    return bytes(out)


def finite_stats(values: list[float]):
    finite = [v for v in values if v == v]
    return finite, (min(finite) if finite else None), (max(finite) if finite else None)


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    samples_dir = Path(args.samples_dir)
    pins = read_pins(Path(args.pins))
    for sid, _ in SERIES:
        d = samples_dir / sid
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.bin"):
            old.unlink()
    rows_out = []
    excluded = []
    per_task = {}
    for member, csv_name, m, text in iter_recordings(downloads, pins):
        label = f"{member}:{csv_name}"
        cols, nan_counts, gaps = parse_build(text, label)
        rows = len(cols[0])
        stem = Path(csv_name).stem
        reasons = []
        for k, (sid, _) in enumerate(SERIES):
            finite = rows - nan_counts[k]
            if finite < MIN_FINITE:
                reasons.append(f"{sid}: finite={finite}<{MIN_FINITE}")
            if rows and nan_counts[k] / rows > MAX_NAN_FRACTION:
                reasons.append(f"{sid}: nan_fraction={nan_counts[k] / rows:.4f}>{MAX_NAN_FRACTION}")
        if reasons:
            excluded.append({"recording": stem, "rows": rows, "reasons": reasons})
            print(f"excluded recording={stem} reasons={reasons}")
            continue
        for k, (sid, column) in enumerate(SERIES):
            values = cols[k]
            finite, lo, hi = finite_stats(values)
            if lo == hi:
                fail(f"{label}: series {sid} is constant over finite values")
            payload = pack(values)
            out = samples_dir / sid / f"{stem}.bin"
            out.write_bytes(payload)
            rows_out.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": sid,
                    "sample_path": str(out.relative_to(data_root)),
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": len(payload),
                    "value_count": rows,
                    "source_member": member,
                    "source_csv": csv_name,
                    "source_column": column,
                    "subject": m.group("subject"),
                    "session": int(m.group("session")),
                    "task": m.group("task"),
                    "nan_count": nan_counts[k],
                    "nan_fraction": round(nan_counts[k] / rows, 6),
                    "n_sequence_gaps": gaps,
                    "min": lo,
                    "max": hi,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        task = m.group("task")
        per_task[task] = per_task.get(task, 0) + 1
        print(f"recording={stem} rows={rows} nan_x={nan_counts[0]} nan_y={nan_counts[1]} gaps={gaps}")
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {}
    for sid, _ in SERIES:
        sel = [r for r in rows_out if r["series_id"] == sid]
        values = sum(r["value_count"] for r in sel)
        nans = sum(r["nan_count"] for r in sel)
        summary[sid] = {
            "sample_count": len(sel),
            "total_size_bytes": sum(r["sample_size_bytes"] for r in sel),
            "value_count": values,
            "nan_count": nans,
            "nan_fraction": round(nans / values, 6) if values else None,
            "max_sample_nan_fraction": max((r["nan_fraction"] for r in sel), default=None),
        }
    stats = {
        "dataset_id": DATASET_ID,
        "subjects": [p["name"] for p in pins],
        "recordings_emitted": len(rows_out) // len(SERIES),
        "recordings_per_task": dict(sorted(per_task.items())),
        "excluded_recordings": excluded,
        "series": summary,
    }
    Path(args.stats).parent.mkdir(parents=True, exist_ok=True)
    Path(args.stats).write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats["series"], sort_keys=True))
    print(f"build_ok recordings={stats['recordings_emitted']} excluded={len(excluded)}")


# ---------------------------------------------------------------- verify side


def parse_verify(text: str, label: str):
    """Verify-side parser: csv.DictReader, Decimal normalization check."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if set(reader.fieldnames or []) != REQUIRED_COLUMNS:
        fail(f"{label}: header {reader.fieldnames!r}")
    xs, ys = [], []
    max_decimals = 0
    for row in reader:
        for token, dest in ((row["x"], xs), (row["y"], ys)):
            if token == "NaN":
                dest.append(None)
                continue
            if not re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", token):
                fail(f"{label}: malformed numeric token {token!r}")
            max_decimals = max(max_decimals, -Decimal(token).as_tuple().exponent)
            value = float(token)
            if Decimal(repr(value)).normalize() != Decimal(token).normalize():
                fail(f"{label}: {token!r} does not round-trip")
            dest.append(value)
    return xs, ys, max_decimals


def cmd_verify(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    pins = read_pins(Path(args.pins))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    index_rows = [json.loads(l) for l in Path(args.index).read_text(encoding="utf-8").splitlines() if l.strip()]
    by_path = {}
    for row in index_rows:
        for key, want in (
            ("dataset_id", DATASET_ID),
            ("numeric_kind", "float"),
            ("bit_width", 64),
            ("endianness", "little"),
            ("element_size_bytes", 8),
        ):
            if row.get(key) != want:
                fail(f"index row {row.get('sample_path')}: {key}={row.get(key)!r}")
        if row["sample_path"] in by_path:
            fail(f"duplicate index row {row['sample_path']}")
        by_path[row["sample_path"]] = row
    seen = set()
    excluded = 0
    max_dec_seen = 0
    totals = {sid: [0, 0, 0, 0] for sid, _ in SERIES}  # samples, bytes, values, nans
    for member, csv_name, _m, text in iter_recordings(Path(args.downloads), pins):
        label = f"{member}:{csv_name}"
        xs, ys, max_dec = parse_verify(text, label)
        max_dec_seen = max(max_dec_seen, max_dec)
        rows = len(xs)
        stem = Path(csv_name).stem
        cols = (xs, ys)
        nan_counts = [sum(1 for v in c if v is None) for c in cols]
        is_excluded = any(
            rows - n < MIN_FINITE or (rows and n / rows > MAX_NAN_FRACTION) for n in nan_counts
        )
        for k, (sid, _) in enumerate(SERIES):
            rel = f"samples/{DATASET_ID}/{sid}/{stem}.bin"
            path = data_root / rel
            if is_excluded:
                if path.exists() or rel in by_path:
                    fail(f"{rel}: excluded recording was emitted")
                continue
            if rel not in by_path or not path.is_file():
                fail(f"{rel}: missing sample or index row")
            expected = b"".join(NAN_BYTES if v is None else struct.pack("<d", v) for v in cols[k])
            actual = path.read_bytes()
            if actual != expected:
                fail(f"{rel}: bytes differ from independent re-derivation")
            row = by_path[rel]
            finite = [v for v in cols[k] if v is not None]
            if min(finite) == max(finite):
                fail(f"{rel}: constant series")
            distinct = len(set(finite[:20000]))
            if distinct < 10:
                fail(f"{rel}: degenerate series ({distinct} distinct values)")
            checks = {
                "sample_size_bytes": len(expected),
                "value_count": rows,
                "nan_count": nan_counts[k],
                "min": min(finite),
                "max": max(finite),
                "sha256": hashlib.sha256(expected).hexdigest(),
            }
            for key, want in checks.items():
                if row.get(key) != want:
                    fail(f"{rel}: index {key}={row.get(key)!r} expected {want!r}")
            seen.add(rel)
            t = totals[sid]
            t[0] += 1
            t[1] += len(expected)
            t[2] += rows
            t[3] += nan_counts[k]
        if is_excluded:
            excluded += 1
    if seen != set(by_path):
        fail(f"index rows without source recording: {sorted(set(by_path) - seen)[:5]}")
    for sid, _ in SERIES:
        files = sorted((data_root / "samples" / DATASET_ID / sid).glob("*.bin"))
        if len(files) != totals[sid][0]:
            fail(f"{sid}: {len(files)} files on disk but {totals[sid][0]} verified")
    series_cfg = {s["id"]: s for s in manifest.get("series", [])}
    for sid, _ in SERIES:
        cfg = series_cfg.get(sid)
        if cfg is None:
            fail(f"manifest lacks series {sid}")
        n, size, values, nans = totals[sid]
        if cfg.get("sample_count") != n or cfg.get("total_size_bytes") != size:
            fail(
                f"manifest {sid}: sample_count={cfg.get('sample_count')} total_size_bytes={cfg.get('total_size_bytes')} "
                f"realized {n} / {size}"
            )
        print(f"series={sid} samples={n} bytes={size} values={values} nan_fraction={nans / values:.6f}")
    if max_dec_seen > 6:
        fail(f"source decimals exceed the documented 6 places ({max_dec_seen})")
    print(f"verify_ok samples={len(seen)} excluded_recordings={excluded} max_source_decimals={max_dec_seen}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check-api")
    a.add_argument("--json", required=True)
    e = sub.add_parser("extract")
    for k in ("pins", "member", "headers", "range-file", "output"):
        e.add_argument(f"--{k}", required=True)
    c = sub.add_parser("check-inner")
    for k in ("pins", "member", "path"):
        c.add_argument(f"--{k}", required=True)
    for name in ("build", "verify"):
        s = sub.add_parser(name)
        for k in ("pins", "downloads", "samples-dir", "index", "data-root"):
            s.add_argument(f"--{k}", required=True)
        s.add_argument("--stats", required=name == "build")
        s.add_argument("--manifest", required=name == "verify")
    args = p.parse_args()
    {
        "check-api": cmd_check_api,
        "extract": cmd_extract,
        "check-inner": cmd_check_inner,
        "build": cmd_build,
        "verify": cmd_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
