#!/usr/bin/env python3
"""Independently re-derive and check the Azure V2 VM CPU fleet-snapshot samples.

Separate code path from build_snapshots.py: raw zlib streaming (multi-member
aware), byte-level line splitting, struct packing. Every sample file must be
byte-identical to the re-derived little-endian float64 snapshot column. Also
checks the index, the stats file, the manifest totals, stray files, and the
same missing-value policy as the build (empty, non-numeric, non-finite or
out-of-range [0, 100] values are fatal; duplicate vmids in a snapshot are
fatal; constant samples are fatal). Like the build, the source files are read
as one row stream, so a snapshot straddling a file boundary is joined, and a
final run whose timestamp continues into the next (not downloaded) file is a
partial snapshot that must have been dropped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import struct
import tomllib
import zlib
from pathlib import Path

SERIES = ("vm_cpu_min_pct_f64", "vm_cpu_max_pct_f64", "vm_cpu_avg_pct_f64")
INDEX_KEYS = (
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
)


def die(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def gzip_lines(path: Path):
    """Yield data lines (bytes, CR stripped) from a possibly multi-member gzip."""
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    tail = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 22)
            if not chunk:
                break
            while chunk:
                data = decomp.decompress(chunk)
                if data:
                    parts = (tail + data).split(b"\n")
                    tail = parts.pop()
                    for line in parts:
                        yield line[:-1] if line.endswith(b"\r") else line
                if decomp.eof:
                    chunk = decomp.unused_data
                    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
                else:
                    chunk = b""
    rest = decomp.flush()
    if rest:
        tail += rest
    if tail:
        yield tail[:-1] if tail.endswith(b"\r") else tail


def head_first_ts(path: Path) -> int:
    raw = path.read_bytes()
    text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
    first = text.split(b"\n", 1)[0].rstrip(b"\r").split(b",")
    if len(first) != 5:
        die(f"{path.name}: malformed first row")
    return int(first[0])


def check_values(raw: bytes, label: str) -> tuple[float, float, int, int]:
    count = len(raw) // 8
    values = struct.unpack(f"<{count}d", raw)
    lo = min(values)
    hi = max(values)
    if not (math.isfinite(lo) and math.isfinite(hi)) or any(v != v for v in values):
        die(f"{label}: non-finite stored value")
    if lo < 0.0 or hi > 100.0:
        die(f"{label}: stored value outside [0, 100] ({lo}..{hi})")
    if not lo < hi:
        die(f"{label}: constant sample")
    return lo, hi, len(set(values)), values.count(0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--source", action="append", required=True, help="source file, in stream order")
    parser.add_argument("--first-ts", type=int, required=True)
    parser.add_argument("--snapshots", type=int, required=True)
    parser.add_argument("--next-head", required=True, help="PATH:FIRST_TS")
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--manifest", default="")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    samples_dir = Path(args.samples_dir).resolve()
    interval = args.interval

    # --- index -----------------------------------------------------------
    index: dict[tuple[str, int], dict] = {}
    seen_paths: set[str] = set()
    for number, line in enumerate(Path(args.index).read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            die(f"index line {number}: missing {missing}")
        if row["dataset_id"] != args.dataset_id or row["series_id"] not in SERIES:
            die(f"index line {number}: bad dataset/series")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 64, "little", 8):
            die(f"index line {number}: bad type fields")
        if row["sample_size_bytes"] != row["value_count"] * 8:
            die(f"index line {number}: size/value_count mismatch")
        if row["sample_path"] in seen_paths:
            die(f"index line {number}: duplicate sample_path")
        seen_paths.add(row["sample_path"])
        key = (row["series_id"], int(row["timestamp_s"]))
        if key in index:
            die(f"index line {number}: duplicate series/timestamp {key}")
        index[key] = row
    on_disk = {p.relative_to(data_root).as_posix() for p in samples_dir.rglob("*") if p.is_file()}
    if on_disk != seen_paths:
        die(f"sample files and index disagree: stray={sorted(on_disk - seen_paths)[:5]} missing={sorted(seen_paths - on_disk)[:5]}")

    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    stats_rows = {s["timestamp_s"]: s for s in stats["snapshots"]}

    # --- next-file head ----------------------------------------------------
    next_path, next_first = args.next_head.rsplit(":", 1)
    if head_first_ts(Path(next_path)) != int(next_first):
        die("next-file head does not start at the pinned timestamp")

    # --- re-derive every snapshot from one stream over all source files ----
    first_ts = args.first_ts
    expected_ts = [first_ts + interval * k for k in range(args.snapshots)]
    if sorted({ts for _, ts in index}) != expected_ts:
        die("indexed timestamps differ from the pinned contiguous range")

    verified = 0
    rows_seen: list[int] = []
    order = {"min_gt_avg": 0, "avg_gt_max": 0, "min_gt_max": 0}

    def finish(ts: int, by_file: dict[str, int], cols: list[list[float]], vmids: set[bytes]) -> None:
        nonlocal verified
        n = len(cols[0])
        if len(vmids) != n:
            die(f"t={ts}: duplicate vmid rows")
        srow = stats_rows.get(ts)
        if srow is None or srow["rows"] != n or srow["rows_by_file"] != by_file or srow["distinct_vmids"] != n:
            die(f"t={ts}: stats row disagrees (rows={n}, by_file={by_file})")
        for series_id, values in zip(SERIES, cols):
            row = index.get((series_id, ts))
            if row is None:
                die(f"{series_id} t={ts}: not indexed")
            if row["value_count"] != n or row["source_files"] != list(by_file):
                die(f"{series_id} t={ts}: index value_count/source_files mismatch")
            expected = struct.pack(f"<{n}d", *values)
            stored = (data_root / row["sample_path"]).read_bytes()
            if stored != expected:
                die(f"{series_id} t={ts}: sample bytes differ from re-derived source column")
            if hashlib.sha256(stored).hexdigest() != row["sha256"]:
                die(f"{series_id} t={ts}: sha256 mismatch")
            lo, hi, distinct, zeros = check_values(stored, f"{series_id} t={ts}")
            if (lo, hi, distinct, zeros) != (row["min_value"], row["max_value"], row["distinct_values"], row["zero_values"]):
                die(f"{series_id} t={ts}: index min/max/distinct/zero stats differ from stored doubles")
            verified += 1
        rows_seen.append(n)

    current = None
    cols: list[list[float]] = [[], [], []]
    vmids: set[bytes] = set()
    by_file: dict[str, int] = {}
    rows_read = 0
    for path_text in args.source:
        path = Path(path_text)
        name = path.name
        file_rows = 0
        for number, line in enumerate(gzip_lines(path), 1):
            fields = line.split(b",")
            if len(fields) != 5:
                die(f"{name}:{number}: malformed row {line[:100]!r}")
            ts = int(fields[0])
            if ts != current:
                if current is not None:
                    if ts != current + interval:
                        die(f"{name}:{number}: timestamp jump {current}->{ts}")
                    finish(current, by_file, cols, vmids)
                elif ts != first_ts:
                    die(f"{name}: stream starts at {ts}, expected {first_ts}")
                current = ts
                cols = [[], [], []]
                vmids = set()
                by_file = {}
            if not fields[1]:
                die(f"{name}:{number}: empty vmid")
            vmids.add(fields[1])
            triple = []
            for k in range(3):
                token = fields[2 + k]
                if not token:
                    die(f"{name}:{number}: empty value")
                value = float(token)
                if value != value or not 0.0 <= value <= 100.0:
                    die(f"{name}:{number}: value {token!r} non-finite or outside [0, 100]")
                cols[k].append(value)
                triple.append(value)
            lo, hi, avg = triple
            order["min_gt_avg"] += lo > avg
            order["avg_gt_max"] += avg > hi
            order["min_gt_max"] += lo > hi
            by_file[name] = by_file.get(name, 0) + 1
            file_rows += 1
        if file_rows == 0:
            die(f"{name}: no rows")
        rows_read += file_rows
        print(f"verified stream through file={name} rows={file_rows}", flush=True)

    # Trailing run: complete only if the next file starts one interval later;
    # a run whose timestamp continues into the next file is dropped.
    trailing = stats.get("dropped_trailing_partial_snapshot")
    if current == int(next_first):
        if len(vmids) != len(cols[0]):
            die(f"t={current}: duplicate vmid rows in trailing partial snapshot")
        if trailing != {"timestamp_s": current, "rows": len(cols[0]), "rows_by_file": by_file}:
            die(f"trailing partial snapshot disagrees with stats: {trailing}")
        dropped = len(cols[0])
    elif current is not None and current + interval == int(next_first):
        if trailing is not None:
            die("stats claim a dropped trailing snapshot but the stream ends on a boundary")
        finish(current, by_file, cols, vmids)
        dropped = 0
    else:
        die(f"stream ends at t={current}, not matching/abutting next file start {next_first}")

    if verified != len(index):
        die(f"verified {verified} samples but index has {len(index)}")
    if len(rows_seen) != args.snapshots:
        die(f"{len(rows_seen)} complete snapshots, expected {args.snapshots}")
    for key, value in order.items():
        if stats["counters"][key] != value:
            die(f"stats counter {key}={stats['counters'][key]} but re-derived {value}")
    counters = stats["counters"]
    if (counters["rows_read"], counters["rows_emitted"], counters["rows_dropped_trailing_partial"]) != (rows_read, sum(rows_seen), dropped):
        die("row accounting disagrees with stats")
    median_rows = statistics.median(rows_seen)
    if median_rows < 1000:
        die(f"median sample value count {median_rows} below 1000")

    # --- manifest totals -----------------------------------------------------
    if args.manifest:
        manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
        declared = {s["id"]: s for s in manifest.get("series", [])}
        if set(declared) != set(SERIES):
            die(f"manifest series {sorted(declared)} != {sorted(SERIES)}")
        for series_id in SERIES:
            rows = [r for k, r in index.items() if k[0] == series_id]
            total = sum(r["sample_size_bytes"] for r in rows)
            s = declared[series_id]
            if s.get("role") != "primary":
                die(f"{series_id}: manifest role must be primary")
            if s.get("sample_count") != len(rows) or s.get("total_size_bytes") != total:
                die(f"{series_id}: manifest sample_count/total_size_bytes {s.get('sample_count')}/{s.get('total_size_bytes')} != realized {len(rows)}/{total}")
    total_bytes = sum(r["sample_size_bytes"] for r in index.values())
    if total_bytes > 1_000_000_000:
        die(f"primary bytes {total_bytes} exceed 1e9")
    print(
        f"verify ok samples={verified} snapshots={len(rows_seen)} rows={sum(rows_seen)} "
        f"median_rows={median_rows} dropped_trailing_rows={dropped} primary_bytes={total_bytes} "
        f"order_violations={order}"
    )


if __name__ == "__main__":
    main()
