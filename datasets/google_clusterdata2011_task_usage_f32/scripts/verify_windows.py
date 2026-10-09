#!/usr/bin/env python3
"""Independently re-derive and check the clusterdata-2011-2 task_usage window samples.

Separate code path from build_windows.py: raw zlib streaming (multi-member
aware), manual line splitting, integer-division windowing, struct '<f'
packing. Every sample file must be byte-identical to the re-derived
little-endian float32 column of its window. Also checks the index, the stats
file, the manifest totals, stray files, and the same missing-value policy as
the build: an empty field is dropped from that series only and counted per
sample; a non-numeric or non-finite value is fatal; constant samples are
fatal; start times must never decrease across the part stream; consecutive
windows must be exactly 300 s apart; the final window must be dropped iff the
next part's head starts inside it. Width-honesty guard: each sample's
f16_recoverable_fraction is recomputed from the stored bytes (share of values
that round-trip through IEEE binary16 at 4 significant digits), must equal
the index value, and must not exceed 0.90.
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

SERIES = (
    ("task_cycles_per_instruction_f32", 15),
    ("task_memory_accesses_per_instruction_f32", 16),
)
SERIES_IDS = tuple(s for s, _ in SERIES)
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
                    yield from parts
                if decomp.eof:
                    chunk = decomp.unused_data
                    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
                else:
                    chunk = b""
    tail += decomp.flush()
    if tail:
        yield tail


F16_LIMIT = 0.90


def f16_fraction(raw: bytes) -> float:
    n = len(raw) // 4
    singles = struct.unpack(f"<{n}f", raw)
    ok = 0
    for v in singles:
        if not abs(v) < 65504.0:
            continue
        (h,) = struct.unpack("<e", struct.pack("<e", v))
        ok += float("%.4g" % h) == float("%.4g" % v)
    return ok / n


def head_first_start(path: Path) -> int:
    text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(path.read_bytes())
    first = text.split(b"\n", 1)[0].split(b",")
    if len(first) != 20:
        die(f"{path.name}: malformed first row")
    return int(first[0])


def stored_stats(raw: bytes, label: str) -> tuple[float, float, int, int]:
    n = len(raw) // 4
    values = struct.unpack(f"<{n}f", raw)
    if any(not math.isfinite(v) for v in values):
        die(f"{label}: non-finite stored value")
    lo, hi = min(values), max(values)
    if not lo < hi:
        die(f"{label}: constant sample")
    return lo, hi, len(set(values)), sum(1 for v in values if v == 0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--first-window-s", type=int, required=True)
    parser.add_argument("--windows", type=int, required=True)
    parser.add_argument("--next-head", required=True)
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--manifest", default="")
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    samples_dir = Path(args.samples_dir).resolve()
    step_s = 300

    # --- index -------------------------------------------------------------
    index: dict[tuple[str, int], dict] = {}
    seen_paths: set[str] = set()
    for number, line in enumerate(Path(args.index).read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            die(f"index line {number}: missing {missing}")
        if row["dataset_id"] != args.dataset_id or row["series_id"] not in SERIES_IDS:
            die(f"index line {number}: bad dataset/series")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            die(f"index line {number}: bad type fields")
        if row["sample_size_bytes"] != row["value_count"] * 4:
            die(f"index line {number}: size/value_count mismatch")
        if row["sample_path"] in seen_paths:
            die(f"index line {number}: duplicate sample_path")
        seen_paths.add(row["sample_path"])
        key = (row["series_id"], int(row["window_start_s"]))
        if key in index:
            die(f"index line {number}: duplicate {key}")
        index[key] = row
    on_disk = {p.relative_to(data_root).as_posix() for p in samples_dir.rglob("*") if p.is_file()}
    if on_disk != seen_paths:
        die(f"sample files and index disagree: stray={sorted(on_disk - seen_paths)[:5]} missing={sorted(seen_paths - on_disk)[:5]}")
    expected_ws = [args.first_window_s + step_s * k for k in range(args.windows)]
    if sorted({ws for _, ws in index}) != expected_ws:
        die("indexed windows differ from the pinned contiguous range")

    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    stats_windows = {w["window_start_s"]: w for w in stats["windows"]}

    next_path, next_first = args.next_head.rsplit(":", 1)
    next_first = int(next_first)
    if head_first_start(Path(next_path)) != next_first:
        die("next-part head does not start at the pinned start time")
    next_ws = next_first // 1_000_000 // step_s * step_s

    verified = 0
    window_rows: list[int] = []
    negatives = 0

    def finish(ws: int, cols: list[list[float]], empties: list[int], nrows: int, lattice: int, by_file: dict[str, int]) -> None:
        nonlocal verified
        srow = stats_windows.get(ws)
        if srow is None or srow["rows"] != nrows or srow["lattice_aligned_rows"] != lattice or srow["rows_by_file"] != by_file:
            die(f"window {ws}: stats row disagrees (rows={nrows}, lattice={lattice}, by_file={by_file})")
        for (series_id, _), values, empty in zip(SERIES, cols, empties):
            row = index.get((series_id, ws))
            if row is None:
                die(f"{series_id} window {ws}: not indexed")
            if row["value_count"] != len(values) or row["empty_fields_dropped"] != empty or row["window_rows"] != nrows:
                die(f"{series_id} window {ws}: index value/empty/row counts disagree")
            if row["source_files"] != list(by_file) or srow["empty_fields"][series_id] != empty:
                die(f"{series_id} window {ws}: source_files or stats empty count disagree")
            expected = struct.pack(f"<{len(values)}f", *values)
            stored = (data_root / row["sample_path"]).read_bytes()
            if stored != expected:
                die(f"{series_id} window {ws}: sample bytes differ from re-derived column")
            if hashlib.sha256(stored).hexdigest() != row["sha256"]:
                die(f"{series_id} window {ws}: sha256 mismatch")
            frac = f16_fraction(stored)
            if frac != row.get("f16_recoverable_fraction"):
                die(f"{series_id} window {ws}: f16_recoverable_fraction {frac} != index {row.get('f16_recoverable_fraction')}")
            if frac > F16_LIMIT:
                die(f"{series_id} window {ws}: f16_recoverable_fraction {frac:.4f} > {F16_LIMIT}")
            got = stored_stats(stored, f"{series_id} window {ws}")
            if got != (row["min_value"], row["max_value"], row["distinct_values"], row["zero_values"]):
                die(f"{series_id} window {ws}: index min/max/distinct/zero differ from stored float32 values")
            verified += 1
        window_rows.append(nrows)

    cur_ws = None
    cols: list[list[float]] = [[] for _ in SERIES]
    empties = [0 for _ in SERIES]
    nrows = lattice = 0
    by_file: dict[str, int] = {}
    prev_start = -1
    rows_read = 0
    for path_text in args.source:
        path = Path(path_text)
        name = path.name
        file_rows = 0
        for number, line in enumerate(gzip_lines(path), 1):
            fields = line.split(b",")
            if len(fields) != 20:
                die(f"{name}:{number}: malformed row {line[:120]!r}")
            start = int(fields[0])
            int(fields[1])
            if start < prev_start:
                die(f"{name}:{number}: start time decreases")
            prev_start = start
            ws = start // 1_000_000 // step_s * step_s
            if ws != cur_ws:
                if cur_ws is None:
                    if start != args.first_window_s * 1_000_000:
                        die(f"stream starts at {start}, expected window start {args.first_window_s} s")
                else:
                    if ws != cur_ws + step_s:
                        die(f"{name}:{number}: window gap {cur_ws} -> {ws}")
                    finish(cur_ws, cols, empties, nrows, lattice, by_file)
                cur_ws = ws
                cols, empties, nrows, lattice, by_file = [[] for _ in SERIES], [0 for _ in SERIES], 0, 0, {}
            if start == ws * 1_000_000:
                lattice += 1
            for k, (_, col) in enumerate(SERIES):
                token = fields[col]
                if token == b"":
                    empties[k] += 1
                    continue
                value = float(token)
                if not math.isfinite(value):
                    die(f"{name}:{number}: non-finite value {token!r}")
                negatives += value < 0
                cols[k].append(value)
            nrows += 1
            by_file[name] = by_file.get(name, 0) + 1
            file_rows += 1
        if file_rows == 0:
            die(f"{name}: no rows")
        rows_read += file_rows
        print(f"verified stream through {name} rows={file_rows}", flush=True)

    trailing = stats.get("dropped_trailing_partial_window")
    if cur_ws == next_ws:
        if trailing != {"window_start_s": cur_ws, "rows": nrows, "rows_by_file": by_file}:
            die(f"trailing partial window disagrees with stats: {trailing}")
        dropped = nrows
    elif cur_ws is not None and cur_ws + step_s == next_ws:
        if trailing is not None:
            die("stats claim a dropped trailing window but the stream ends on a boundary")
        finish(cur_ws, cols, empties, nrows, lattice, by_file)
        dropped = 0
    else:
        die(f"stream ends in window {cur_ws}, not matching/abutting next part window {next_ws}")

    if verified != len(index):
        die(f"verified {verified} samples but index has {len(index)}")
    if len(window_rows) != args.windows:
        die(f"{len(window_rows)} complete windows, expected {args.windows}")
    c = stats["counters"]
    if (c["rows_read"], c["rows_emitted"], c["rows_dropped_trailing_partial"], c["negative_values"]) != (rows_read, sum(window_rows), dropped, negatives):
        die("row accounting / negative count disagrees with stats")
    for series_id in SERIES_IDS:
        counts = [r["value_count"] for k, r in index.items() if k[0] == series_id]
        if statistics.median(counts) < 1000:
            die(f"{series_id}: median value count below 1000")

    if args.manifest:
        manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
        declared = {s["id"]: s for s in manifest.get("series", [])}
        if set(declared) != set(SERIES_IDS):
            die(f"manifest series {sorted(declared)} != {sorted(SERIES_IDS)}")
        for series_id in SERIES_IDS:
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
        f"verify ok samples={verified} windows={len(window_rows)} rows={sum(window_rows)} "
        f"median_rows={statistics.median(window_rows)} dropped_trailing_rows={dropped} primary_bytes={total_bytes}"
    )


if __name__ == "__main__":
    main()
