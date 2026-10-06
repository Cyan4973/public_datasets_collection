#!/usr/bin/env python3
"""Build fleet-snapshot samples from Azure Public Dataset V2 VM CPU readings.

Each source row is `timestamp,vmid,min_cpu,max_cpu,avg_cpu` (CRLF lines). The
195 files are one timestamp-sorted row stream cut into ~10M-row pieces, so a
file boundary can fall inside a snapshot. The pinned files are read as one
stream in file order; every run of rows sharing one timestamp is one 5-minute
fleet snapshot, even when it straddles a file boundary. The final run is
dropped when the next (not downloaded) file starts with the same timestamp,
because the remainder of that snapshot lives there.

For every complete snapshot this writes three raw little-endian float64
samples (min, max, avg CPU %), values in source row order. vmid (an encrypted
hash) is dropped. Pure standard library.
"""
from __future__ import annotations

import argparse
import array
import csv
import gzip
import hashlib
import json
import math
import shutil
import statistics
import sys
import zlib
from pathlib import Path

SERIES = (
    ("vm_cpu_min_pct_f64", 2, "min cpu"),
    ("vm_cpu_max_pct_f64", 3, "max cpu"),
    ("vm_cpu_avg_pct_f64", 4, "avg cpu"),
)


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def first_timestamp(path: Path) -> int:
    with path.open("rb") as handle:
        raw = handle.read(1 << 20)
    text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
    line = text.split(b"\n", 1)[0].rstrip(b"\r")
    fields = line.split(b",")
    if len(fields) != 5 or not fields[0].isdigit():
        fail(f"{path.name}: unexpected first row {line[:120]!r}")
    return int(fields[0])


class Snapshot:
    def __init__(self, ts: int) -> None:
        self.ts = ts
        self.columns = [array.array("d") for _ in SERIES]
        self.vmids: set[str] = set()
        self.rows = 0
        self.rows_by_file: dict[str, int] = {}


class Builder:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.data_root = Path(args.data_root).resolve()
        self.samples_dir = Path(args.samples_dir).resolve()
        self.interval = args.interval
        self.index_rows: list[dict] = []
        self.snapshots: list[dict] = []
        self.seen_ts: set[int] = set()
        self.counters = {
            "rows_read": 0,
            "rows_emitted": 0,
            "rows_dropped_trailing_partial": 0,
            "min_gt_avg": 0,
            "avg_gt_max": 0,
            "min_gt_max": 0,
            "duplicate_vmid_rows": 0,
            "vmid_len_not_64": 0,
        }

    def flush(self, snap: Snapshot) -> None:
        ts, rows = snap.ts, snap.rows
        if rows < 1:
            fail(f"empty snapshot t={ts}")
        if self.counters["duplicate_vmid_rows"]:
            fail(f"t={ts}: duplicate vmid rows inside a snapshot")
        snapshot_index = len(self.snapshots)
        sources = list(snap.rows_by_file)
        for (series_id, _, _), values in zip(SERIES, snap.columns):
            if len(values) != rows:
                fail(f"column length mismatch at t={ts}")
            stored = array.array("d", values)
            if sys.byteorder != "little":
                stored.byteswap()
            payload = stored.tobytes()
            out = self.samples_dir / series_id / f"t{ts:05d}.f64"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            # min/max from the stored doubles (identical to float(token)).
            lo = min(values)
            hi = max(values)
            if not lo < hi:
                fail(f"{series_id} t={ts}: constant snapshot ({lo})")
            self.index_rows.append(
                {
                    "dataset_id": self.args.dataset_id,
                    "series_id": series_id,
                    "sample_path": out.relative_to(self.data_root).as_posix(),
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": len(payload),
                    "value_count": rows,
                    "timestamp_s": ts,
                    "snapshot_index": snapshot_index,
                    "source_files": sources,
                    "min_value": lo,
                    "max_value": hi,
                    "distinct_values": len(set(values)),
                    "zero_values": values.count(0.0),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        self.snapshots.append(
            {
                "snapshot_index": snapshot_index,
                "timestamp_s": ts,
                "rows": rows,
                "rows_by_file": dict(snap.rows_by_file),
                "distinct_vmids": len(snap.vmids),
            }
        )
        self.counters["rows_emitted"] += rows

    def run(self) -> None:
        paths = [Path(p) for p in self.args.source]
        next_path, next_first = self.args.next_head.rsplit(":", 1)
        next_first = int(next_first)
        actual_next = first_timestamp(Path(next_path))
        if actual_next != next_first:
            fail(f"next-file head starts at {actual_next}, expected {next_first}")
        if self.samples_dir.exists():
            shutil.rmtree(self.samples_dir)
        self.samples_dir.mkdir(parents=True)

        snap: Snapshot | None = None
        files = []
        for path in paths:
            name = path.name
            file_rows = 0
            file_first = None
            with gzip.open(path, "rt", encoding="ascii", newline="") as handle:
                for line_number, row in enumerate(csv.reader(handle), 1):
                    if len(row) != 5:
                        fail(f"{name}:{line_number}: expected 5 fields, got {len(row)}: {row!r}")
                    ts_token, vmid = row[0], row[1]
                    if not ts_token.isdigit():
                        fail(f"{name}:{line_number}: bad timestamp {ts_token!r}")
                    ts = int(ts_token)
                    if file_first is None:
                        file_first = ts
                    if snap is None or ts != snap.ts:
                        if snap is None:
                            if ts != self.args.first_ts:
                                fail(f"{name}: stream starts at {ts}, expected {self.args.first_ts}")
                        else:
                            if ts != snap.ts + self.interval:
                                fail(f"{name}:{line_number}: timestamp jump {snap.ts} -> {ts}")
                            self.flush(snap)
                        if ts in self.seen_ts:
                            fail(f"{name}:{line_number}: timestamp {ts} reappears")
                        self.seen_ts.add(ts)
                        snap = Snapshot(ts)
                    if not vmid:
                        fail(f"{name}:{line_number}: empty vmid")
                    if len(vmid) != 64:
                        self.counters["vmid_len_not_64"] += 1
                    if vmid in snap.vmids:
                        self.counters["duplicate_vmid_rows"] += 1
                    snap.vmids.add(vmid)
                    values = []
                    for (_, column, label), target in zip(SERIES, snap.columns):
                        token = row[column]
                        if not token:
                            fail(f"{name}:{line_number}: empty {label}")
                        try:
                            value = float(token)
                        except ValueError:
                            fail(f"{name}:{line_number}: non-numeric {label} {token!r}")
                        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
                            fail(f"{name}:{line_number}: {label} {token!r} outside [0, 100] or non-finite")
                        target.append(value)
                        values.append(value)
                    lo, hi, avg = values
                    if lo > avg:
                        self.counters["min_gt_avg"] += 1
                    if avg > hi:
                        self.counters["avg_gt_max"] += 1
                    if lo > hi:
                        self.counters["min_gt_max"] += 1
                    snap.rows += 1
                    snap.rows_by_file[name] = snap.rows_by_file.get(name, 0) + 1
                    file_rows += 1
            if file_rows == 0 or snap is None:
                fail(f"{name}: no data rows")
            self.counters["rows_read"] += file_rows
            files.append(
                {
                    "source_file": name,
                    "rows": file_rows,
                    "first_timestamp_s": file_first,
                    "last_timestamp_s": snap.ts,
                }
            )
            print(f"file={name} rows={file_rows} t={file_first}..{snap.ts}", flush=True)

        # The final run is complete only if the next file starts one interval later.
        trailing = None
        if snap.ts == next_first:
            if self.counters["duplicate_vmid_rows"]:
                fail(f"t={snap.ts}: duplicate vmid rows inside the trailing partial snapshot")
            trailing = {"timestamp_s": snap.ts, "rows": snap.rows, "rows_by_file": dict(snap.rows_by_file)}
            self.counters["rows_dropped_trailing_partial"] = snap.rows
        elif snap.ts + self.interval == next_first:
            self.flush(snap)
        else:
            fail(f"stream ends at t={snap.ts}, which neither matches nor abuts next file start {next_first}")

        if len(self.snapshots) != self.args.snapshots:
            fail(f"{len(self.snapshots)} complete snapshots, expected {self.args.snapshots}")
        expected_ts = [self.args.first_ts + self.interval * k for k in range(self.args.snapshots)]
        if [s["timestamp_s"] for s in self.snapshots] != expected_ts:
            fail("complete snapshot timestamps are not the pinned contiguous range")
        if self.counters["rows_emitted"] + self.counters["rows_dropped_trailing_partial"] != self.counters["rows_read"]:
            fail("row accounting mismatch")

        rows_per_snapshot = [s["rows"] for s in self.snapshots]
        median_rows = statistics.median(rows_per_snapshot)
        primary_bytes = sum(r["sample_size_bytes"] for r in self.index_rows)
        if median_rows < self.args.min_median_values:
            fail(f"median snapshot rows {median_rows} below {self.args.min_median_values}")
        if primary_bytes > self.args.max_primary_bytes:
            fail(f"primary bytes {primary_bytes} exceed {self.args.max_primary_bytes}")

        order = [s[0] for s in SERIES]
        self.index_rows.sort(key=lambda r: (order.index(r["series_id"]), r["timestamp_s"]))
        index_path = Path(self.args.index)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = index_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as out:
            for row in self.index_rows:
                out.write(json.dumps(row, sort_keys=True) + "\n")
        tmp.replace(index_path)

        per_series = {}
        for series_id in order:
            rows = [r for r in self.index_rows if r["series_id"] == series_id]
            per_series[series_id] = {
                "sample_count": len(rows),
                "total_size_bytes": sum(r["sample_size_bytes"] for r in rows),
                "value_count": sum(r["value_count"] for r in rows),
                "min_value": min(r["min_value"] for r in rows),
                "max_value": max(r["max_value"] for r in rows),
                "zero_values": sum(r["zero_values"] for r in rows),
                "min_distinct_values_per_sample": min(r["distinct_values"] for r in rows),
            }
        straddling = [s for s in self.snapshots if len(s["rows_by_file"]) > 1]
        stats = {
            "dataset_id": self.args.dataset_id,
            "files": files,
            "next_file_first_timestamp_s": next_first,
            "interval_s": self.interval,
            "snapshot_count": len(self.snapshots),
            "straddling_snapshots": straddling,
            "dropped_trailing_partial_snapshot": trailing,
            "rows_per_snapshot": {
                "min": min(rows_per_snapshot),
                "median": median_rows,
                "max": max(rows_per_snapshot),
            },
            "counters": self.counters,
            "primary_bytes": primary_bytes,
            "series": per_series,
            "snapshots": self.snapshots,
        }
        stats_path = Path(self.args.stats)
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"snapshots={len(self.snapshots)} rows_per_snapshot min/median/max="
            f"{min(rows_per_snapshot)}/{median_rows}/{max(rows_per_snapshot)} "
            f"samples={len(self.index_rows)} primary_bytes={primary_bytes}"
        )
        for s in straddling:
            print(f"straddling snapshot t={s['timestamp_s']} rows_by_file={s['rows_by_file']}")
        print(f"dropped trailing partial snapshot: {trailing}")
        for series_id, info in per_series.items():
            print(f"series={series_id} " + " ".join(f"{k}={v}" for k, v in info.items()))
        print("counters " + " ".join(f"{k}={v}" for k, v in self.counters.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--source", action="append", required=True, help="source file, in stream order")
    parser.add_argument("--first-ts", type=int, required=True, help="timestamp of the first row of the stream")
    parser.add_argument("--snapshots", type=int, required=True, help="expected number of complete snapshots")
    parser.add_argument("--next-head", required=True, help="PATH:FIRST_TS of the head range of the following file")
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--min-median-values", type=int, default=1000)
    parser.add_argument("--max-primary-bytes", type=int, default=1_000_000_000)
    Builder(parser.parse_args()).run()


if __name__ == "__main__":
    main()
