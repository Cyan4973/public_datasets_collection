#!/usr/bin/env python3
"""Build 5-minute cluster-window samples from Google clusterdata-2011-2 task_usage.

Each task_usage row is one task's resource-usage measurement over a period
[start time, end time) (microseconds) inside one 300 s reporting window. The
500 part files are one row stream sorted by start time and cut by trace time,
so a part boundary falls inside a window. The pinned parts are read as one
stream in part order; rows are grouped by window = floor(start / 300 s).
This keeps the lattice-aligned full-period rows of the window followed by the
rows whose measurement period starts mid-window (tasks that started, or were
re-measured, inside it); both are measurements of the same window. A window
that straddles a part boundary is joined. The final window is dropped when
the head of the next (not downloaded) part starts inside it.

For every complete window this writes two raw little-endian float32
samples, values in source row order:
  field 16 cycles per instruction           -> task_cycles_per_instruction_f32
  field 17 memory accesses per instruction  -> task_memory_accesses_per_instruction_f32
An empty field is dropped from that series only (counted per sample, never
filled). IDs, timestamps, flags, CPU-rate and memory/disk columns are not
emitted (field 6 CPU rate is a widened half-precision code: 100% of its
values recover exactly from float16 at 4 significant digits).

Width-honesty guard: for each sample, f16_recoverable_fraction is the share
of stored float32 values v with abs(v) < 65504 and
float('%.4g' % h) == float('%.4g' % v), h = float16 round trip of v. The
build fails if any sample's fraction exceeds 0.90.
Pure standard library.
"""
from __future__ import annotations

import argparse
import array
import gzip
import hashlib
import json
import math
import shutil
import statistics
import struct
import sys
import zlib
from pathlib import Path

SERIES = (
    ("task_cycles_per_instruction_f32", 15, "cycles per instruction"),
    ("task_memory_accesses_per_instruction_f32", 16, "memory accesses per instruction"),
)
F32_MAX = 3.4028234663852886e38
F16_MAX_FRACTION = 0.90


def f16_recoverable_fraction(values) -> float:
    """Share of stored float32 values that survive a float16 round trip at 4 sig. digits."""
    pack_e = struct.Struct("<e")
    hits = 0
    for v in values:
        if abs(v) < 65504.0:
            h = pack_e.unpack(pack_e.pack(v))[0]
            if float("%.4g" % h) == float("%.4g" % v):
                hits += 1
    return hits / len(values)


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def first_start(path: Path) -> int:
    with path.open("rb") as handle:
        raw = handle.read(1 << 18)
    text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
    fields = text.split(b"\n", 1)[0].split(b",")
    if len(fields) != 20 or not fields[0].isdigit():
        fail(f"{path.name}: unexpected first row")
    return int(fields[0])


class Window:
    def __init__(self, start_us: int) -> None:
        self.start_us = start_us
        self.columns = [array.array("f") for _ in SERIES]
        self.empty = [0 for _ in SERIES]
        self.rows = 0
        self.lattice_rows = 0
        self.rows_by_file: dict[str, int] = {}


class Builder:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.interval = args.interval_us
        self.data_root = Path(args.data_root).resolve()
        self.samples_dir = Path(args.samples_dir).resolve()
        self.index_rows: list[dict] = []
        self.windows: list[dict] = []
        self.counters = {
            "rows_read": 0,
            "rows_emitted": 0,
            "rows_dropped_trailing_partial": 0,
            "end_not_after_start": 0,
            "end_beyond_window": 0,
            "negative_values": 0,
        }

    def flush(self, win: Window) -> None:
        ws = win.start_us // 1_000_000
        window_index = len(self.windows)
        sources = list(win.rows_by_file)
        for (series_id, _, _), values, empty in zip(SERIES, win.columns, win.empty):
            if len(values) + empty != win.rows:
                fail(f"window {ws}: {series_id} value accounting mismatch")
            if len(values) == 0:
                fail(f"window {ws}: {series_id} has no values")
            stored = array.array("f", values)
            if sys.byteorder != "little":
                stored.byteswap()
            payload = stored.tobytes()
            out = self.samples_dir / series_id / f"w{ws:06d}.f32"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            lo = min(values)  # array('f') items are the stored float32 values
            hi = max(values)
            if not lo < hi:
                fail(f"{series_id} window {ws}: constant sample ({lo})")
            f16_frac = f16_recoverable_fraction(values)
            if f16_frac > F16_MAX_FRACTION:
                fail(f"{series_id} window {ws}: f16_recoverable_fraction {f16_frac:.4f} > {F16_MAX_FRACTION} (widened half-precision source)")
            self.index_rows.append(
                {
                    "dataset_id": self.args.dataset_id,
                    "series_id": series_id,
                    "sample_path": out.relative_to(self.data_root).as_posix(),
                    "numeric_kind": "float",
                    "bit_width": 32,
                    "endianness": "little",
                    "element_size_bytes": 4,
                    "sample_size_bytes": len(payload),
                    "value_count": len(values),
                    "window_start_s": ws,
                    "window_index": window_index,
                    "window_rows": win.rows,
                    "empty_fields_dropped": empty,
                    "f16_recoverable_fraction": f16_frac,
                    "source_files": sources,
                    "min_value": lo,
                    "max_value": hi,
                    "distinct_values": len(set(values)),
                    "zero_values": values.count(0.0),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        self.windows.append(
            {
                "window_index": window_index,
                "window_start_s": ws,
                "rows": win.rows,
                "lattice_aligned_rows": win.lattice_rows,
                "mid_window_rows": win.rows - win.lattice_rows,
                "rows_by_file": dict(win.rows_by_file),
                "empty_fields": {s[0]: e for s, e in zip(SERIES, win.empty)},
            }
        )
        self.counters["rows_emitted"] += win.rows

    def run(self) -> None:
        args = self.args
        paths = [Path(p) for p in args.source]
        next_path, next_first = args.next_head.rsplit(":", 1)
        next_first = int(next_first)
        if first_start(Path(next_path)) != next_first:
            fail(f"next-part head does not start at {next_first}")
        next_window = next_first // self.interval * self.interval
        first_window_us = args.first_window_s * 1_000_000
        if first_window_us % self.interval:
            fail("first window is not on the 300 s lattice")
        if self.samples_dir.exists():
            shutil.rmtree(self.samples_dir)
        self.samples_dir.mkdir(parents=True)

        win: Window | None = None
        prev_start = -1
        files = []
        for path in paths:
            name = path.name
            file_rows = 0
            file_first = None
            with gzip.open(path, "rb") as handle:
                for line_number, line in enumerate(handle, 1):
                    row = line.rstrip(b"\n").split(b",")
                    if len(row) != 20:
                        fail(f"{name}:{line_number}: expected 20 fields, got {len(row)}")
                    try:
                        start = int(row[0])
                        end = int(row[1])
                    except ValueError:
                        fail(f"{name}:{line_number}: bad start/end {row[0]!r},{row[1]!r}")
                    if file_first is None:
                        file_first = start
                    if start < prev_start:
                        fail(f"{name}:{line_number}: start time decreases {prev_start} -> {start}")
                    prev_start = start
                    w = start - start % self.interval
                    if win is None or w != win.start_us:
                        if win is None:
                            if start != first_window_us:
                                fail(f"stream starts at {start}, expected {first_window_us}")
                        else:
                            if w != win.start_us + self.interval:
                                fail(f"{name}:{line_number}: window gap {win.start_us} -> {w}")
                            self.flush(win)
                        win = Window(w)
                    if end <= start:
                        self.counters["end_not_after_start"] += 1
                    if end > w + self.interval:
                        self.counters["end_beyond_window"] += 1
                    if start == w:
                        win.lattice_rows += 1
                    for k, (series_id, col, label) in enumerate(SERIES):
                        token = row[col]
                        if not token:
                            win.empty[k] += 1
                            continue
                        try:
                            value = float(token)
                        except ValueError:
                            fail(f"{name}:{line_number}: non-numeric {label} {token!r}")
                        if not math.isfinite(value) or abs(value) > F32_MAX:
                            fail(f"{name}:{line_number}: {label} {token!r} not finite in float32")
                        if value < 0:
                            self.counters["negative_values"] += 1
                        win.columns[k].append(value)
                    win.rows += 1
                    win.rows_by_file[name] = win.rows_by_file.get(name, 0) + 1
                    file_rows += 1
            if file_rows == 0 or win is None:
                fail(f"{name}: no data rows")
            self.counters["rows_read"] += file_rows
            files.append({"source_file": name, "rows": file_rows, "first_start_us": file_first, "last_start_us": prev_start})
            print(f"file={name} rows={file_rows} start_us={file_first}..{prev_start}", flush=True)

        if prev_start > next_first:
            fail(f"stream ends at start {prev_start}, after next part start {next_first}")
        trailing = None
        if win.start_us == next_window:
            trailing = {"window_start_s": win.start_us // 1_000_000, "rows": win.rows, "rows_by_file": dict(win.rows_by_file)}
            self.counters["rows_dropped_trailing_partial"] = win.rows
        elif win.start_us + self.interval == next_window:
            self.flush(win)
        else:
            fail(f"stream ends in window {win.start_us}, neither equal to nor abutting next part window {next_window}")

        if len(self.windows) != args.windows:
            fail(f"{len(self.windows)} complete windows, expected {args.windows}")
        expected = [args.first_window_s + (self.interval // 1_000_000) * k for k in range(args.windows)]
        if [w["window_start_s"] for w in self.windows] != expected:
            fail("complete window starts are not the pinned contiguous range")
        c = self.counters
        if c["rows_emitted"] + c["rows_dropped_trailing_partial"] != c["rows_read"]:
            fail("row accounting mismatch")

        primary_bytes = sum(r["sample_size_bytes"] for r in self.index_rows)
        order = [s[0] for s in SERIES]
        per_series = {}
        for series_id in order:
            rows = [r for r in self.index_rows if r["series_id"] == series_id]
            counts = [r["value_count"] for r in rows]
            if statistics.median(counts) < args.min_median_values:
                fail(f"{series_id}: median sample value count below {args.min_median_values}")
            per_series[series_id] = {
                "sample_count": len(rows),
                "total_size_bytes": sum(r["sample_size_bytes"] for r in rows),
                "value_count": sum(counts),
                "median_value_count": statistics.median(counts),
                "empty_fields_dropped": sum(r["empty_fields_dropped"] for r in rows),
                "min_value": min(r["min_value"] for r in rows),
                "max_value": max(r["max_value"] for r in rows),
                "zero_values": sum(r["zero_values"] for r in rows),
                "max_zero_fraction": max(r["zero_values"] / r["value_count"] for r in rows),
                "min_distinct_values_per_sample": min(r["distinct_values"] for r in rows),
                "f16_recoverable_fraction_min": min(r["f16_recoverable_fraction"] for r in rows),
                "f16_recoverable_fraction_max": max(r["f16_recoverable_fraction"] for r in rows),
            }
        if primary_bytes > args.max_primary_bytes:
            fail(f"primary bytes {primary_bytes} exceed {args.max_primary_bytes}")

        self.index_rows.sort(key=lambda r: (order.index(r["series_id"]), r["window_start_s"]))
        index_path = Path(args.index)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = index_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as out:
            for row in self.index_rows:
                out.write(json.dumps(row, sort_keys=True) + "\n")
        tmp.replace(index_path)

        rows_per_window = [w["rows"] for w in self.windows]
        straddling = [w for w in self.windows if len(w["rows_by_file"]) > 1]
        stats = {
            "dataset_id": args.dataset_id,
            "files": files,
            "next_part_first_start_us": next_first,
            "interval_us": self.interval,
            "window_rule": "window = floor(start_time / 300 s); lattice-aligned and mid-window rows both kept",
            "window_count": len(self.windows),
            "straddling_windows": straddling,
            "dropped_trailing_partial_window": trailing,
            "rows_per_window": {"min": min(rows_per_window), "median": statistics.median(rows_per_window), "max": max(rows_per_window)},
            "counters": c,
            "primary_bytes": primary_bytes,
            "series": per_series,
            "windows": self.windows,
        }
        stats_path = Path(args.stats)
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"windows={len(self.windows)} rows_per_window min/median/max={min(rows_per_window)}/"
            f"{statistics.median(rows_per_window)}/{max(rows_per_window)} samples={len(self.index_rows)} primary_bytes={primary_bytes}"
        )
        for w in straddling:
            print(f"straddling window {w['window_start_s']} rows_by_file={w['rows_by_file']}")
        print(f"dropped trailing partial window: {trailing}")
        for series_id, info in per_series.items():
            print(f"series={series_id} " + " ".join(f"{k}={v}" for k, v in info.items()))
        print("counters " + " ".join(f"{k}={v}" for k, v in c.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--source", action="append", required=True, help="part file, in stream order")
    parser.add_argument("--first-window-s", type=int, required=True, help="start (s) of the first window; the stream must start exactly there")
    parser.add_argument("--windows", type=int, required=True, help="expected number of complete windows")
    parser.add_argument("--next-head", required=True, help="PATH:FIRST_START_US of the next part's head range")
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--interval-us", type=int, default=300_000_000)
    parser.add_argument("--min-median-values", type=int, default=1000)
    parser.add_argument("--max-primary-bytes", type=int, default=1_000_000_000)
    Builder(parser.parse_args()).run()


if __name__ == "__main__":
    main()
