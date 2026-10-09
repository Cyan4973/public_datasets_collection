#!/usr/bin/env python3
"""HMDA 2023 snapshot public LAR: per-state closing-cost columns as float64.

Subcommands:
  validate  check the downloaded zip (single zip64 member, pinned size, CRC,
            exact 99-column header) by streaming the whole member once
  build     emit one little-endian float64 sample per (cost field, state)
  verify    independently re-parse the CSV (byte-split parser, not csv
            module) and check every sample, the index, and the manifest

Pure standard library.
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
from array import array
from pathlib import Path

DATASET_ID = "cfpb_hmda2023_lar_closing_costs_f64"
MEMBER = "2023_public_lar_csv.csv"
ZIP_BYTES = 624_535_331
MEMBER_BYTES = 4_339_556_230
MEMBER_CRC = 1_354_180_223
HEADER_SHA256 = "dbef604276f5b4e28b72634d143f23f6b3b5a7ed9284671ac79cbba8bd126063"
HEADER_COLUMNS = 99
STATE_FIELD = "state_code"
YEAR_FIELD = "activity_year"
# (source column, series id); kept as four separate series, never mixed.
FIELDS = [
    ("total_loan_costs", "hmda2023_total_loan_costs_f64"),
    ("origination_charges", "hmda2023_origination_charges_f64"),
    ("discount_points", "hmda2023_discount_points_f64"),
    ("lender_credits", "hmda2023_lender_credits_f64"),
]
MISSING_TOKENS = {"", "NA", "Exempt"}
MIN_VALUES_PER_SAMPLE = 1_000
STATE_RE = re.compile(r"^[A-Z]{2}$")
NUMBER_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")
NEG_NUMBER_RE = re.compile(r"^-[0-9]+(\.[0-9]+)?$")
CHUNK = 8 << 20


def log(message: str) -> None:
    print(message, flush=True)


def open_member(archive: Path) -> tuple[zipfile.ZipFile, zipfile.ZipInfo]:
    zf = zipfile.ZipFile(archive)
    infos = zf.infolist()
    if len(infos) != 1 or infos[0].filename != MEMBER:
        raise SystemExit(f"unexpected zip members: {[i.filename for i in infos]}")
    info = infos[0]
    if info.file_size != MEMBER_BYTES or info.CRC != MEMBER_CRC or info.compress_type != zipfile.ZIP_DEFLATED:
        raise SystemExit(
            f"member identity mismatch: size={info.file_size} crc={info.CRC} method={info.compress_type}"
        )
    return zf, info


def check_header(line: str) -> list[str]:
    line = line.rstrip("\r\n")
    if hashlib.sha256(line.encode("ascii")).hexdigest() != HEADER_SHA256:
        raise SystemExit(f"CSV header does not match pinned header sha256: {line[:200]!r}")
    columns = line.split(",")
    if len(columns) != HEADER_COLUMNS:
        raise SystemExit(f"header has {len(columns)} columns, expected {HEADER_COLUMNS}")
    for name in [STATE_FIELD, YEAR_FIELD] + [f for f, _ in FIELDS]:
        if columns.count(name) != 1:
            raise SystemExit(f"header column {name!r} missing or duplicated")
    return columns


# ---------------------------------------------------------------- validate


def cmd_validate(args: argparse.Namespace) -> None:
    archive = Path(args.archive)
    if archive.stat().st_size != ZIP_BYTES:
        raise SystemExit(f"zip size {archive.stat().st_size} != {ZIP_BYTES}")
    zf, info = open_member(archive)
    total = 0
    newlines = 0
    first = b""
    with zf.open(info) as fh:  # zipfile checks CRC-32 when the stream is exhausted
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            if not first:
                first = block[: block.index(b"\n") + 1]
            total += len(block)
            newlines += block.count(b"\n")
    if total != MEMBER_BYTES:
        raise SystemExit(f"decompressed {total} bytes, expected {MEMBER_BYTES}")
    check_header(first.decode("ascii"))
    if newlines < 1_000_000:
        raise SystemExit(f"only {newlines} lines; not a national LAR")
    log(f"member_ok name={MEMBER} bytes={total} crc={info.CRC} lines={newlines} header_sha256={HEADER_SHA256}")


# ------------------------------------------------------------------- build


def parse_cost(token: str) -> float | None | str:
    """Return a float, None for a documented missing token, or a reason string."""
    if token in MISSING_TOKENS:
        return None
    if NUMBER_RE.match(token):
        return float(token)
    if NEG_NUMBER_RE.match(token):
        return "negative"
    return "malformed"


def cmd_build(args: argparse.Namespace) -> None:
    archive = Path(args.archive)
    data_root = Path(args.data_root)
    samples_dir = Path(args.samples_dir)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    zf, info = open_member(archive)
    buckets: dict[tuple[str, str], array] = {}
    skipped = {f: {"missing": 0, "negative": 0, "malformed": 0, "state_na": 0} for f, _ in FIELDS}
    over_two_decimals = {f: 0 for f, _ in FIELDS}
    rows = 0
    bad_state_rows = 0
    with zf.open(info) as raw:
        text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
        reader = csv.reader(text)
        header = next(reader)
        check_header(",".join(header))
        state_i = header.index(STATE_FIELD)
        year_i = header.index(YEAR_FIELD)
        cols = [(header.index(f), f) for f, _ in FIELDS]
        for row in reader:
            rows += 1
            if len(row) != HEADER_COLUMNS:
                raise SystemExit(f"row {rows}: {len(row)} columns")
            if row[year_i] != "2023":
                raise SystemExit(f"row {rows}: activity_year {row[year_i]!r}")
            state = row[state_i]
            state_ok = state != "NA" and bool(STATE_RE.match(state))
            if not state_ok:
                if state not in ("NA", ""):
                    raise SystemExit(f"row {rows}: unexpected state_code {state!r}")
                bad_state_rows += 1
            for i, field in cols:
                token = row[i]
                result = parse_cost(token)
                if result is None:
                    skipped[field]["missing"] += 1
                    continue
                if isinstance(result, str):
                    skipped[field][result] += 1
                    continue
                if not state_ok:
                    skipped[field]["state_na"] += 1
                    continue
                dot = token.find(".")
                if dot >= 0 and len(token) - dot - 1 > 2:
                    over_two_decimals[field] += 1
                key = (field, state)
                bucket = buckets.get(key)
                if bucket is None:
                    bucket = buckets[key] = array("d")
                bucket.append(result)
            if rows % 2_000_000 == 0:
                log(f"rows={rows}")
    log(f"rows_total={rows} state_na_rows={bad_state_rows}")
    for field, counts in skipped.items():
        kept = sum(len(b) for (f, _), b in buckets.items() if f == field)
        if counts["malformed"] > max(100, kept // 1000):
            raise SystemExit(f"{field}: {counts['malformed']} malformed tokens (> 0.1% of {kept} kept)")
    if sys.byteorder != "little":
        for bucket in buckets.values():
            bucket.byteswap()

    samples_dir.mkdir(parents=True, exist_ok=True)
    for old in samples_dir.glob("*/*.bin"):
        old.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    index_rows = []
    dropped_small = []
    series_totals = {}
    for field, series_id in FIELDS:
        out_dir = samples_dir / series_id
        out_dir.mkdir(parents=True, exist_ok=True)
        n_samples = n_values = 0
        for (f, state) in sorted(k for k in buckets if k[0] == field):
            values = buckets[(f, state)]
            if len(values) < MIN_VALUES_PER_SAMPLE:
                dropped_small.append({"field": field, "state_code": state, "values": len(values)})
                continue
            if min(values) == max(values):
                raise SystemExit(f"constant sample {field}/{state}")
            payload = values.tobytes()
            path = out_dir / f"{state}.f64le.bin"
            path.write_bytes(payload)
            zeros = sum(1 for v in values if v == 0.0)
            index_rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "sample_path": str(path.relative_to(data_root)),
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": len(payload),
                    "value_count": len(values),
                    "source_field": field,
                    "state_code": state,
                    "min": min(values),
                    "max": max(values),
                    "zero_fraction": round(zeros / len(values), 6),
                    "distinct_values": len(set(values)),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            n_samples += 1
            n_values += len(values)
        series_totals[series_id] = {"samples": n_samples, "values": n_values, "bytes": n_values * 8}
        log(f"series={series_id} samples={n_samples} values={n_values} bytes={n_values * 8}")
    with index_path.open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "rows_total": rows,
        "state_na_rows": bad_state_rows,
        "skipped": skipped,
        "values_with_more_than_two_decimals": over_two_decimals,
        "dropped_small_samples": dropped_small,
        "series": series_totals,
        "states_per_series": {
            sid: sorted(r["state_code"] for r in index_rows if r["series_id"] == sid) for _, sid in FIELDS
        },
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log(json.dumps({k: stats[k] for k in ("rows_total", "skipped", "values_with_more_than_two_decimals")}))
    log(f"samples_total={len(index_rows)} bytes_total={sum(r['sample_size_bytes'] for r in index_rows)}")


# ------------------------------------------------------------------ verify


def iter_lines(archive: Path):
    """Independent line splitter over raw member bytes (no csv module)."""
    zf, info = open_member(archive)
    with zf.open(info) as fh:
        tail = b""
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            block = tail + block
            lines = block.split(b"\n")
            tail = lines.pop()
            yield from lines
        if tail:
            yield tail


def cmd_verify(args: argparse.Namespace) -> None:
    archive = Path(args.archive)
    data_root = Path(args.data_root)
    index_path = Path(args.index)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    lines = iter_lines(archive)
    header = next(lines).decode("ascii").rstrip("\r").split(",")
    check_header(",".join(header))
    state_i = header.index(STATE_FIELD)
    cols = [(header.index(f), f) for f, _ in FIELDS]
    expect: dict[tuple[str, str], tuple[hashlib._Hash, list[int]]] = {}
    pack = struct.Struct("<d").pack
    rows = 0
    quoted = 0
    for raw in lines:
        if not raw:
            continue
        rows += 1
        if b'"' in raw:
            quoted += 1
            parts = next(csv.reader([raw.decode("latin-1").rstrip("\r")]))
        else:
            parts = raw.decode("latin-1").rstrip("\r").split(",")
        if len(parts) != HEADER_COLUMNS:
            raise SystemExit(f"verify row {rows}: {len(parts)} columns")
        state = parts[state_i]
        if state in ("NA", ""):
            continue
        if not STATE_RE.match(state):
            raise SystemExit(f"verify row {rows}: bad state {state!r}")
        for i, field in cols:
            token = parts[i]
            if token in MISSING_TOKENS or NEG_NUMBER_RE.match(token):
                continue
            if not NUMBER_RE.match(token):
                continue  # malformed: skipped by the same documented policy as build
            value = float(token)
            entry = expect.get((field, state))
            if entry is None:
                entry = expect[(field, state)] = (hashlib.sha256(), [0, 0])
            entry[0].update(pack(value))
            entry[1][0] += 1
            if value == 0.0:
                entry[1][1] += 1
    log(f"verify_rows={rows} quoted_rows={quoted}")

    index_rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_key = {(r["source_field"], r["state_code"]): r for r in index_rows}
    expected_keys = {k for k, (_, c) in expect.items() if c[0] >= MIN_VALUES_PER_SAMPLE}
    if set(by_key) != expected_keys:
        raise SystemExit(
            f"sample set mismatch: missing={sorted(expected_keys - set(by_key))[:10]} extra={sorted(set(by_key) - expected_keys)[:10]}"
        )
    series_of = dict(FIELDS)
    for key, row in sorted(by_key.items()):
        field, state = key
        digest, (count, zeros) = expect[key]
        path = data_root / row["sample_path"]
        payload = path.read_bytes()
        if row["series_id"] != series_of[field] or row["dataset_id"] != DATASET_ID:
            raise SystemExit(f"{key}: wrong series/dataset id")
        if row["numeric_kind"] != "float" or row["bit_width"] != 64 or row["endianness"] != "little" or row["element_size_bytes"] != 8:
            raise SystemExit(f"{key}: wrong dtype metadata")
        if len(payload) != count * 8 or row["value_count"] != count or row["sample_size_bytes"] != len(payload):
            raise SystemExit(f"{key}: size mismatch file={len(payload)} expected_values={count}")
        if hashlib.sha256(payload).hexdigest() != digest.hexdigest() or row["sha256"] != digest.hexdigest():
            raise SystemExit(f"{key}: sample bytes differ from independent re-derivation")
        values = array("d", payload)
        if sys.byteorder != "little":
            values.byteswap()
        lo, hi = min(values), max(values)
        if lo == hi:
            raise SystemExit(f"{key}: constant sample")
        if lo < 0 or not all(math.isfinite(v) for v in (lo, hi)):
            raise SystemExit(f"{key}: out-of-policy values")
        if row["min"] != lo or row["max"] != hi:
            raise SystemExit(f"{key}: index min/max mismatch")
        distinct = len(set(values))
        if distinct < 50:
            raise SystemExit(f"{key}: degenerate ({distinct} distinct values)")
        if zeros / count > 0.9:
            raise SystemExit(f"{key}: zero-dominated ({zeros}/{count})")
        if abs(row["zero_fraction"] - round(zeros / count, 6)) > 1e-9:
            raise SystemExit(f"{key}: zero_fraction mismatch")
    sample_files = sorted(p for p in (data_root / "samples" / DATASET_ID).glob("*/*.bin"))
    if len(sample_files) != len(index_rows):
        raise SystemExit(f"{len(sample_files)} sample files on disk vs {len(index_rows)} index rows")
    for series in manifest["series"]:
        rows_s = [r for r in index_rows if r["series_id"] == series["id"]]
        size = sum(r["sample_size_bytes"] for r in rows_s)
        if series["sample_count"] != len(rows_s) or series["total_size_bytes"] != size:
            raise SystemExit(
                f"manifest {series['id']}: sample_count={series['sample_count']} total_size_bytes={series['total_size_bytes']} realized={len(rows_s)}/{size}"
            )
        zf = sorted(r["zero_fraction"] for r in rows_s)
        log(
            f"series={series['id']} samples={len(rows_s)} values={size // 8} bytes={size} "
            f"zero_fraction_min={zf[0]} median={zf[len(zf) // 2]} max={zf[-1]}"
        )
    log(f"verify_ok samples={len(index_rows)} bytes={sum(r['sample_size_bytes'] for r in index_rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--archive", required=True)
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("build")
    for name in ("archive", "samples-dir", "index", "stats", "data-root"):
        p.add_argument(f"--{name}", required=True)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("verify")
    for name in ("archive", "index", "data-root", "manifest"):
        p.add_argument(f"--{name}", required=True)
    p.set_defaults(func=cmd_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
