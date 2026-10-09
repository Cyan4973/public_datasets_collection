#!/usr/bin/env python3
"""Independent verification for physionet_wearable_exam_stress_e4_acc_i8.

Re-hashes every source against SHA256SUMS.txt, re-decodes each ACC.csv with a
csv-module tokenizer and per-field checks (not the build's block regex),
compares sample bytes, every index field, the ingest stats and the manifest
totals, applies the same fatal-row and degenerate-sample policy as the build,
and rejects stray sample files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import struct
import sys
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True  # keep the recipe directory free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e4acc_pins as pins  # noqa: E402
import e4acc_synth as synth  # noqa: E402

FIELD = re.compile(r"-?[0-9]{1,3}")
MIN_FRAMES = 57_600  # 30 min at 32 Hz
MIN_DISTINCT_PER_AXIS = 16
MAX_MOST_COMMON_FRACTION = 0.9
PACK = struct.Struct("<bbb")


class Reject(ValueError):
    pass


def decode(data: bytes) -> tuple[str, bytes]:
    if b"\r" in data:
        raise Reject("carriage return")
    if data.endswith(b"\n\n"):
        raise Reject("blank trailing line")
    text = data.decode("ascii")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 3:
        raise Reject("no data rows")
    reader = csv.reader(io.StringIO("\n".join(lines)), strict=True, quoting=csv.QUOTE_NONE)
    header_start = next(reader)
    header_rate = next(reader)
    start = [field.strip() for field in header_start]
    if len(start) != 3 or start.count(start[0]) != 3 or not re.fullmatch(r"\d+\.\d+", start[0]):
        raise Reject(f"start row {header_start}")
    if len(header_rate) != 3 or any(float(field) != 32.0 for field in header_rate):
        raise Reject(f"rate row {header_rate}")
    out = bytearray()
    count = 0
    for row in reader:
        count += 1
        if len(row) != 3:
            raise Reject(f"data row {count} has {len(row)} fields")
        for field in row:
            if not FIELD.fullmatch(field):
                raise Reject(f"data row {count} field {field!r}")
        x, y, z = int(row[0]), int(row[1]), int(row[2])
        if not (-128 <= x <= 127 and -128 <= y <= 127 and -128 <= z <= 127):
            raise Reject(f"data row {count} out of int8 range")
        out += PACK.pack(x, y, z)
    if count != len(lines) - 2:
        raise Reject("row count disagrees with line count (blank or quoted lines)")
    return start[0], bytes(out)


def describe(raw: bytes) -> dict:
    values = [b - 256 if b > 127 else b for b in raw]
    frames = len(values) // 3
    axis_stats = {}
    for axis, name in enumerate("xyz"):
        column = values[axis::3]
        axis_stats[name] = {"min": min(column), "max": max(column), "distinct": len(set(column))}
    histogram = [0] * 256
    for b in raw:
        histogram[b] += 1
    top_count = max(histogram)
    top_byte = histogram.index(top_count)
    static = 0
    for frame in range(1, frames):
        i = 3 * frame
        if raw[i] == raw[i - 3] and raw[i + 1] == raw[i - 2] and raw[i + 2] == raw[i - 1]:
            static += 1
    return {
        "frame_count": frames,
        "axis_stats": axis_stats,
        "most_common_value": top_byte - 256 if top_byte > 127 else top_byte,
        "most_common_value_fraction": round(top_count / len(raw), 6),
        "static_frame_fraction": round(static / max(1, frames - 1), 6),
        "rail_value_count": histogram[0x80] + histogram[0x7F],
    }


def self_test() -> None:
    for trailing in (True, False):
        data, expected, start = synth.good(trailing_newline=trailing)
        got_start, got = decode(data)
        assert got == expected and got_start == start, "synthetic good input mis-decoded"
    for label, data in synth.bad():
        try:
            decode(data)
        except (Reject, ValueError, csv.Error, StopIteration):
            continue
        raise AssertionError(f"synthetic bad input accepted: {label}")
    print("self-test ok: verify decoder")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    errors: list[str] = []

    self_test()
    sums = {}
    sums_bytes = (args.download_dir / "SHA256SUMS.txt").read_bytes()
    if sha256(sums_bytes) != pins.SHA256SUMS_SHA256:
        raise SystemExit("SHA256SUMS.txt hash mismatch")
    for line in sums_bytes.decode("utf-8").splitlines():
        digest, path = line.split()
        sums[path] = digest
    acc_paths = sorted(p for p in sums if p.endswith("/ACC.csv"))
    if len(acc_paths) != 30:
        raise SystemExit(f"SHA256SUMS lists {len(acc_paths)} ACC.csv files, expected 30")

    index_rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index_rows) != 30:
        errors.append(f"index has {len(index_rows)} rows, expected 30")
    by_session = {row.get("session_id"): row for row in index_rows}

    exam_rank = {"midterm_1": 0, "midterm_2": 1, "Final": 2}
    ordered = sorted(acc_paths, key=lambda p: (int(p.split("/")[1][1:]), exam_rank[p.split("/")[2]]))
    expected_files = set()
    total_bytes = 0
    hashes = []
    for position, release_path in enumerate(ordered):
        _, subject_dir, exam, _ = release_path.split("/")
        session = f"{subject_dir}_{exam}"
        source = args.download_dir / "acc" / f"{session}_ACC.csv"
        data = source.read_bytes()
        if sha256(data) != sums[release_path]:
            errors.append(f"{session}: source hash differs from SHA256SUMS")
            continue
        try:
            start, raw = decode(data)
        except (Reject, ValueError, csv.Error) as exc:
            errors.append(f"{session}: decode rejected: {exc}")
            continue
        stats = describe(raw)
        if stats["frame_count"] < MIN_FRAMES:
            errors.append(f"{session}: only {stats['frame_count']} frames")
        for name, axis in stats["axis_stats"].items():
            if axis["distinct"] < MIN_DISTINCT_PER_AXIS:
                errors.append(f"{session}: axis {name} degenerate ({axis['distinct']} distinct)")
        if stats["most_common_value_fraction"] > MAX_MOST_COMMON_FRACTION:
            errors.append(f"{session}: dominated by one value")
        sample_rel = f"samples/{pins.DATASET_ID}/{pins.SERIES_ID}/{session}.bin"
        expected_files.add(f"{session}.bin")
        sample_path = args.data_root / sample_rel
        if not sample_path.is_file():
            errors.append(f"{session}: missing sample {sample_rel}")
            continue
        if sample_path.read_bytes() != raw:
            errors.append(f"{session}: sample bytes differ from independent decode")
        row = by_session.get(session)
        if row is None:
            errors.append(f"{session}: no index row")
            continue
        if index_rows.index(row) != position:
            errors.append(f"{session}: index order differs from canonical order")
        expected_row = {
            "dataset_id": pins.DATASET_ID,
            "series_id": pins.SERIES_ID,
            "sample_path": sample_rel,
            "numeric_kind": "int",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(raw),
            "value_count": len(raw),
            "session_id": session,
            "subject": subject_dir,
            "exam": exam,
            "source_path": release_path,
            "source_sha256": sums[release_path],
            "start_unix_time_date_shifted": start,
            "sample_rate_hz": 32,
            "layout": "interleaved_xyz_frames",
            "duration_s": round(stats["frame_count"] / 32, 3),
            "unit": "1/64 g",
            "sample_sha256": sha256(raw),
            **stats,
        }
        if row != expected_row:
            diff = sorted(k for k in set(row) | set(expected_row) if row.get(k) != expected_row.get(k))
            errors.append(f"{session}: index row fields differ: {diff}")
        total_bytes += len(raw)
        hashes.append(sha256(raw))
        print(f"{session}: ok frames={stats['frame_count']}")

    series_dir = args.samples_root / pins.SERIES_ID
    present = {p.name for p in series_dir.iterdir()} if series_dir.is_dir() else set()
    if present != expected_files:
        errors.append(f"sample directory mismatch: extra={sorted(present - expected_files)} missing={sorted(expected_files - present)}")
    other = sorted(p.name for p in args.samples_root.iterdir() if p.name != pins.SERIES_ID)
    if other:
        errors.append(f"unexpected entries under samples root: {other}")

    stats_doc = json.loads(args.stats.read_text(encoding="utf-8"))
    aggregate = hashlib.sha256("".join(hashes).encode("ascii")).hexdigest()
    if stats_doc.get("total_bytes") != total_bytes or stats_doc.get("aggregate_sample_sha256") != aggregate:
        errors.append("ingest stats totals or aggregate hash differ")
    if stats_doc.get("sample_count") != 30:
        errors.append("ingest stats sample_count != 30")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == pins.SERIES_ID]
    if len(series) != 1 or len(manifest.get("series", [])) != 1:
        errors.append("manifest must declare exactly one series, the ACC series")
    else:
        if series[0].get("sample_count") != len(hashes):
            errors.append(f"manifest sample_count {series[0].get('sample_count')} != {len(hashes)}")
        if series[0].get("total_size_bytes") != total_bytes:
            errors.append(f"manifest total_size_bytes {series[0].get('total_size_bytes')} != {total_bytes}")
    if total_bytes and (total_bytes < 100_000 or total_bytes > 1_000_000_000):
        errors.append(f"total bytes {total_bytes} outside floor/cap")

    if errors:
        for error in errors:
            print("ERROR", error)
        raise SystemExit(f"verify failed with {len(errors)} errors")
    print(f"verify ok: {len(hashes)} samples, {total_bytes} int8 values, aggregate {aggregate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
