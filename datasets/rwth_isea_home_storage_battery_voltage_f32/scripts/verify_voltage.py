#!/usr/bin/env python3
"""Independently re-derive and check the ISEA float32 pack-voltage samples.

Separate implementation from build_voltage.py: the raw deflate member is read
through a streaming io.RawIOBase into csv.reader, timestamps are parsed
arithmetically into second-of-month offsets, float32 encoding uses
struct.pack per value, and the logged-token round-trip uses decimal.Decimal.

Checks the same missing-value policy as build (complete 1 s month, finite
V_in_V in [25, 65] V, Interpolated in {0,1} with share <= 1%, logged tokens exact
in float32, six-significant-digit logger lattice), byte-compares every sample,
recomputes index fields from the stored float32 values, and rejects constant,
narrow, duplicate, or missing samples and manifest/index mismatches.
"""
from __future__ import annotations

import argparse
import calendar
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import os
import struct
import tomllib
import zlib
from decimal import Decimal
from pathlib import Path

DATASET_ID = "rwth_isea_home_storage_battery_voltage_f32"
SERIES_ID = "isea_hss_pack_terminal_voltage_f32"
MONTHS = {name: i + 1 for i, name in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
EXPECTED_HEADER = ["Time", "P_in_W", "V_in_V", "I_in_A", "T_Bat_in_C", "T_Room_in_C", "Interpolated"]
V_MIN, V_MAX = 25.0, 65.0
MAX_INTERPOLATED_SHARE = 0.01
MIN_SIX_DIGIT_SHARE = 0.5
ALLOWED_SYSTEMS = {7, 8, 9, 10, 11, 12, 14, 15, 16, 19, 20, 21}


class InflateRaw(io.RawIOBase):
    """Read-only raw stream over the deflate payload of one ZIP member span."""

    def __init__(self, path: Path, compressed: int, expected_crc: int, expected_size: int):
        self._handle = path.open("rb")
        header = self._handle.read(30)
        if header[:4] != b"PK\x03\x04":
            raise ValueError(f"{path}: no local header")
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        self._handle.seek(30 + name_len + extra_len)
        self._remaining = compressed
        self._inflater = zlib.decompressobj(wbits=-15)
        self._buffer = memoryview(b"")
        self._crc = 0
        self._size = 0
        self._expected = (expected_crc, expected_size)
        self._done = False

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:
        while not self._buffer and not self._done:
            if self._remaining:
                block = self._handle.read(min(self._remaining, 4 << 20))
                if not block:
                    raise ValueError("truncated member")
                self._remaining -= len(block)
                self._buffer = memoryview(self._inflater.decompress(block))
            else:
                self._buffer = memoryview(self._inflater.flush())
                self._done = True
                if not self._inflater.eof or self._inflater.unused_data:
                    raise ValueError("deflate stream does not end at member boundary")
            self._crc = zlib.crc32(self._buffer, self._crc)
            self._size += len(self._buffer)
        if self._done and not self._buffer:
            if (self._crc & 0xFFFFFFFF, self._size) != self._expected:
                raise ValueError(f"crc/size {self._crc & 0xFFFFFFFF:08x}/{self._size} != {self._expected[0]:08x}/{self._expected[1]}")
            return 0
        count = min(len(target), len(self._buffer))
        target[:count] = self._buffer[:count]
        self._buffer = self._buffer[count:]
        return count

    def close(self) -> None:
        self._handle.close()
        super().close()


def sig_digits(token: str) -> int:
    return len(token.lstrip("+-").replace(".", "").lstrip("0"))


def check_month(task: dict) -> dict:
    row = task["row"]
    name = row["member_name"]
    year, month = (int(p) for p in row["month"].split("_"))
    days = calendar.monthrange(year, month)[1]
    expected_rows = days * 86400
    raw = InflateRaw(Path(task["span_path"]), int(row["compressed_bytes"]), int(row["crc32"], 16), int(row["uncompressed_bytes"]))
    text = io.TextIOWrapper(io.BufferedReader(raw, 1 << 20), encoding="ascii", newline="")
    reader = csv.reader(text)
    if next(reader) != EXPECTED_HEADER:
        raise ValueError(f"{name}: header changed")
    digest = hashlib.sha256()
    chunk = []
    pack = struct.pack
    interpolated = logged = six = 0
    seen_logged: set[str] = set()
    count = 0
    for fields in reader:
        if len(fields) != 7:
            raise ValueError(f"{name}: row {count} has {len(fields)} fields")
        stamp = fields[0]
        if len(stamp) != 20 or MONTHS.get(stamp[3:6]) != month or int(stamp[7:11]) != year:
            raise ValueError(f"{name}: row {count} bad timestamp {stamp!r}")
        offset = (int(stamp[0:2]) - 1) * 86400 + int(stamp[12:14]) * 3600 + int(stamp[15:17]) * 60 + int(stamp[18:20])
        if offset != count:
            raise ValueError(f"{name}: row {count} timestamp {stamp!r} is second {offset}")
        token = fields[2].strip()
        if token == "" or token.lower() in {"nan", "na", "null"}:
            raise ValueError(f"{name}: row {count} missing V_in_V")
        value = float(token)
        if not math.isfinite(value) or value < V_MIN or value > V_MAX:
            raise ValueError(f"{name}: row {count} V_in_V {token} outside plausible range")
        flag = fields[6]
        if flag == "1":
            interpolated += 1
        elif flag == "0":
            logged += 1
            if sig_digits(token) == 6:
                six += 1
            if token not in seen_logged:
                stored = struct.unpack("<f", pack("<f", value))[0]
                if Decimal(format(stored, ".6g")) != Decimal(token):
                    raise ValueError(f"{name}: logged token {token} not exact in float32")
                seen_logged.add(token)
        else:
            raise ValueError(f"{name}: row {count} flag {flag!r}")
        chunk.append(value)
        count += 1
        if len(chunk) == 65536:
            digest.update(pack(f"<{len(chunk)}f", *chunk))
            chunk.clear()
    if chunk:
        digest.update(pack(f"<{len(chunk)}f", *chunk))
    text.close()
    if count != expected_rows:
        raise ValueError(f"{name}: {count} rows, complete month needs {expected_rows}")
    share = interpolated / count
    if share > MAX_INTERPOLATED_SHARE:
        raise ValueError(f"{name}: interpolated share {share:.4%} above threshold")
    if logged == 0 or six / logged < MIN_SIX_DIGIT_SHARE:
        raise ValueError(f"{name}: logger lattice check failed ({six}/{logged} six-digit tokens)")

    sample = Path(task["sample_path"])
    data = sample.read_bytes()
    if len(data) != 4 * count:
        raise ValueError(f"{sample}: {len(data)} bytes for {count} values")
    sample_sha = hashlib.sha256(data).hexdigest()
    if sample_sha != digest.hexdigest():
        raise ValueError(f"{sample}: bytes differ from re-derived float32 series")
    stored = struct.unpack(f"<{count}f", data)
    lo, hi = min(stored), max(stored)
    distinct = len(set(stored))
    if distinct < 100 or hi - lo < 0.5:
        raise ValueError(f"{sample}: degenerate (distinct={distinct}, range={hi - lo:.4f})")
    return {"key": (row["system_id"], row["month"]), "rows": count, "interpolated_rows": interpolated, "share": share,
            "min": lo, "max": hi, "sha256": sample_sha, "distinct": distinct, "six_share": six / logged}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()
    root = args.data_root
    downloads = root / "downloads" / DATASET_ID
    samples_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"

    with args.selection.open(encoding="utf-8", newline="") as handle:
        selection = list(csv.DictReader(handle, delimiter="\t"))
    systems = {int(row["system_id"]) for row in selection}
    if not systems <= ALLOWED_SYSTEMS:
        raise SystemExit(f"selection includes systems outside the 48 V lattice-homogeneous set: {sorted(systems - ALLOWED_SYSTEMS)}")

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key = {}
    for entry in index_rows:
        for key, expected in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                              ("bit_width", 32), ("endianness", "little"), ("element_size_bytes", 4)):
            if entry.get(key) != expected:
                raise SystemExit(f"index row {entry.get('sample_path')}: {key}={entry.get(key)!r}")
        if entry["sample_size_bytes"] != 4 * entry["value_count"]:
            raise SystemExit(f"index row {entry['sample_path']}: size/value_count mismatch")
        key = (f"{entry['system_id']:02d}", entry["month"].replace("-", "_"))
        if key in by_key:
            raise SystemExit(f"duplicate index entry {key}")
        by_key[key] = entry
    wanted = {(row["system_id"], row["month"]) for row in selection}
    if set(by_key) != wanted:
        raise SystemExit(f"index/selection mismatch: missing={sorted(wanted - set(by_key))} extra={sorted(set(by_key) - wanted)}")
    on_disk = {p.name for p in samples_dir.iterdir()} if samples_dir.is_dir() else set()
    expected_files = {Path(entry["sample_path"]).name for entry in index_rows}
    if on_disk != expected_files:
        raise SystemExit(f"sample directory differs from index: extra={sorted(on_disk - expected_files)} missing={sorted(expected_files - on_disk)}")

    tasks = []
    for row in selection:
        entry = by_key[(row["system_id"], row["month"])]
        tasks.append({
            "row": row,
            "span_path": str(downloads / "members" / row["system_id"] / f"{row['month']}_System_ID_{row['system_id']}.zipmember"),
            "sample_path": str(root / entry["sample_path"]),
        })
    workers = args.workers or min(len(tasks), os.cpu_count() or 1, 16)
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(check_month, tasks):
            entry = by_key[result["key"]]
            if entry["value_count"] != result["rows"] or entry["sha256"] != result["sha256"]:
                raise SystemExit(f"index row {entry['sample_path']}: value_count/sha256 disagree with re-derivation")
            if entry["interpolated_rows"] != result["interpolated_rows"]:
                raise SystemExit(f"index row {entry['sample_path']}: interpolated_rows disagree")
            if entry["min"] != result["min"] or entry["max"] != result["max"]:
                raise SystemExit(f"index row {entry['sample_path']}: min/max disagree with stored float32")
            results.append(result)
            print(f"verified system={result['key'][0]} month={result['key'][1]} rows={result['rows']} "
                  f"interp_share={result['share']:.4%} six_digit_share={result['six_share']:.3f} "
                  f"distinct={result['distinct']} range={result['min']:.4f}..{result['max']:.4f}", flush=True)
    hashes = [r["sha256"] for r in results]
    if len(set(hashes)) != len(hashes):
        raise SystemExit("two samples are byte-identical")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest must declare exactly one primary series")
    total_bytes = sum(entry["sample_size_bytes"] for entry in index_rows)
    if series[0]["sample_count"] != len(index_rows) or series[0]["total_size_bytes"] != total_bytes:
        raise SystemExit(f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} != realized {len(index_rows)}/{total_bytes}")
    print(f"verify_summary samples={len(results)} systems={len({r['key'][0] for r in results})} "
          f"values={sum(r['rows'] for r in results)} bytes={total_bytes} "
          f"max_interp_share={max(r['share'] for r in results):.4%}")


if __name__ == "__main__":
    main()
