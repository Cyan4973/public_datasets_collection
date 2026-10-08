#!/usr/bin/env python3
"""Build NCLT velodyne_sync x,y,z uint16 samples from the local tarball.

Selection: the velodyne_sync members listed by download.sh (members.tsv) are
sorted by their utime file name; every STRIDE-th one starting at rank 0 is
selected. Selected revolutions with fewer than MIN_HITS hits are skipped and
reported; nothing is substituted for them.

Conversion: each selected member is N packed 8-byte little-endian hit records
(uint16 x, uint16 y, uint16 z, uint8 intensity, uint8 laser_id). Bytes 0..5 of
every record (x, y, z) are copied unchanged into an N x 3 point-major
little-endian uint16 array; intensity and laser_id are dropped. One sample file
per revolution. The tarball is streamed (gzip + tar) and never extracted.
"""
from __future__ import annotations

import argparse
import gzip
import collections
import hashlib
import json
import math
import os
import re
import sys
import tarfile
from array import array
from pathlib import Path

HIT_RECORD_BYTES = 8
MAX_LASER_ID = 31
MAX_CODE = 40000


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def load_sync_listing(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line]
    sync = []
    for row in rows:
        if row["kind"] != "sync":
            continue
        sync.append({
            "name": row["name"],
            "utime": int(row["utime"]),
            "size_bytes": int(row["size_bytes"]),
            "hit_count": int(row["hit_count"]),
            "sha256": row["sha256"],
        })
    if not sync:
        fail(f"no velodyne_sync rows in {path}")
    sync.sort(key=lambda row: row["utime"])
    for previous, current in zip(sync, sync[1:]):
        if previous["utime"] >= current["utime"]:
            fail(f"duplicate utime in listing: {current['utime']}")
    for rank, row in enumerate(sync):
        row["rank"] = rank
    return sync


def xyz_from_hits(body: bytes) -> bytes:
    """Copy bytes 0..5 of every 8-byte hit record into a packed 6-byte triplet."""
    n = len(body) // HIT_RECORD_BYTES
    out = bytearray(6 * n)
    for k in range(6):
        out[k::6] = body[k::8]
    return bytes(out)


def quantiles(values: list[int]) -> dict[str, int]:
    if not values:
        return {}
    n = len(values)
    return {"min": values[0], "p01": values[n // 100], "p10": values[n // 10], "p50": values[n // 2],
            "p90": values[9 * n // 10], "p99": values[99 * n // 100], "max": values[-1]}


def scan_diagnostics(body: bytes) -> tuple[int, int, int]:
    """Informational revolution diagnostics for one sync file.

    Returns (max hits on any single laser_id, that busiest laser_id, number of
    azimuth wraps of the busiest laser in source hit order). The azimuth is
    atan2(y - 20000, x - 20000) about the body-frame origin; a wrap is a step of
    more than pi between consecutive hits of that laser. One revolution gives
    one wrap (zero if it starts at the +-180 degree seam); a file holding
    several revolutions gives several.
    """
    counts = collections.Counter(body[7::8])
    if not counts:
        return 0, -1, 0
    busiest = min(counts, key=lambda laser: (-counts[laser], laser))
    words = memoryview(body).cast("H")
    xs, ys, lasers = words[0::4], words[1::4], body[7::8]
    previous = None
    wraps = 0
    for position, laser in enumerate(lasers):
        if laser != busiest:
            continue
        azimuth = math.atan2(ys[position] - 20000, xs[position] - 20000)
        if previous is not None and abs(azimuth - previous) > math.pi:
            wraps += 1
        previous = azimuth
    return counts[busiest], busiest, wraps


def self_test() -> None:
    records = [(20000, 19000, 0, 255, 15), (1, 40000, 19999, 7, 0), (65535, 2, 3, 4, 31)]
    body = b"".join(
        x.to_bytes(2, "little") + y.to_bytes(2, "little") + z.to_bytes(2, "little") + bytes([i, l])
        for x, y, z, i, l in records
    )
    expected = b"".join(
        x.to_bytes(2, "little") + y.to_bytes(2, "little") + z.to_bytes(2, "little") for x, y, z, _, _ in records
    )
    assert xyz_from_hits(body) == expected
    assert xyz_from_hits(b"") == b""
    ring = b""
    for turn in range(3):  # three revolutions of laser 4, eight azimuth steps each
        for step in range(8):
            angle = -math.pi + (step + 0.5) * math.pi / 4
            x = round(20000 + 1000 * math.cos(angle))
            y = round(20000 + 1000 * math.sin(angle))
            ring += x.to_bytes(2, "little") + y.to_bytes(2, "little") + (19000).to_bytes(2, "little") + bytes([9, 4])
    ring += (20500).to_bytes(2, "little") * 3 + bytes([1, 7])
    assert scan_diagnostics(ring) == (24, 4, 2), scan_diagnostics(ring)
    assert scan_diagnostics(ring[: 8 * 8]) == (8, 4, 0)
    assert scan_diagnostics(b"") == (0, -1, 0)
    print("build self-test=ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--members", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--stride", type=int, required=True)
    parser.add_argument("--min-hits", type=int, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return 0
    if sys.byteorder != "little":
        fail("array('H') statistics assume a little-endian host")

    data_root = args.data_root.resolve()
    series_dir = data_root / "samples" / args.dataset_id / args.series_id
    index_path = data_root / "index" / args.dataset_id / "samples.jsonl"
    series_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.iterdir():
        if stale.is_file():
            stale.unlink()

    sync = load_sync_listing(args.members)
    selected = {row["name"]: row for row in sync[:: args.stride]}
    listed_names = {row["name"]: row for row in sync}
    pattern = re.compile(r"^.+/velodyne_sync/(\d{16})\.bin$")
    print(f"listing: sync_members={len(sync)} stride={args.stride} selected={len(selected)}")

    rows: list[dict] = []
    skipped: list[dict] = []
    seen_sync: set[str] = set()
    population: dict[str, tuple[int, int]] = {}
    with gzip.open(args.archive, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or not pattern.match(member.name):
                    continue  # velodyne_hits.bin and directories are skipped unread
                seen_sync.add(member.name)
                listed = listed_names.get(member.name)
                if listed is None or listed["size_bytes"] != member.size:
                    fail(f"{member.name} is not in members.tsv with size {member.size}")
                handle = tar.extractfile(member)
                body = handle.read() if handle else b""
                if len(body) != member.size or member.size % HIT_RECORD_BYTES:
                    fail(f"{member.name}: bad size {len(body)} / {member.size}")
                max_per_laser, busiest_laser, wraps = scan_diagnostics(body)
                population[member.name] = (max_per_laser, wraps)
                pick = selected.get(member.name)
                if pick is None:
                    continue
                if hashlib.sha256(body).hexdigest() != pick["sha256"]:
                    fail(f"{member.name}: SHA-256 differs from members.tsv")
                hits = member.size // HIT_RECORD_BYTES
                if hits < args.min_hits:
                    skipped.append({"name": member.name, "utime": pick["utime"], "rank": pick["rank"], "hit_count": hits})
                    continue
                lasers = body[7::8]
                laser_max = max(lasers)
                if laser_max > MAX_LASER_ID:
                    fail(f"{member.name}: laser_id {laser_max} > {MAX_LASER_ID}")
                xyz = xyz_from_hits(body)
                codes = array("H")
                codes.frombytes(xyz)
                axes = [codes[0::3], codes[1::3], codes[2::3]]
                axis_min = [min(axis) for axis in axes]
                axis_max = [max(axis) for axis in axes]
                if max(axis_max) > MAX_CODE:
                    fail(f"{member.name}: coordinate code {max(axis_max)} above documented maximum {MAX_CODE}")
                for name, lo, hi in zip("xyz", axis_min, axis_max):
                    if lo == hi:
                        fail(f"{member.name}: constant {name} axis")
                z_axis = axes[2]
                z_zero_lasers: dict[int, int] = {}
                if axis_min[2] == 0:
                    for position, value in enumerate(z_axis):
                        if value == 0:
                            laser = lasers[position]
                            z_zero_lasers[laser] = z_zero_lasers.get(laser, 0) + 1
                out_path = series_dir / f"{pick['utime']}.bin"
                tmp = out_path.with_suffix(".tmp")
                tmp.write_bytes(xyz)
                os.replace(tmp, out_path)
                rows.append({
                    "dataset_id": args.dataset_id,
                    "series_id": args.series_id,
                    "sample_path": str(out_path.relative_to(data_root)),
                    "numeric_kind": "uint",
                    "bit_width": 16,
                    "endianness": "little",
                    "element_size_bytes": 2,
                    "sample_size_bytes": len(xyz),
                    "value_count": 3 * hits,
                    "sample_shape": [hits, 3],
                    "sample_axes": ["hit", "xyz_component"],
                    "source_member": member.name,
                    "utime": pick["utime"],
                    "sync_rank": pick["rank"],
                    "hit_count": hits,
                    "min": min(axis_min),
                    "max": max(axis_max),
                    "axis_min": axis_min,
                    "axis_max": axis_max,
                    "z_code_zero_hits": sum(z_zero_lasers.values()),
                    "z_code_zero_laser_ids": sorted(z_zero_lasers),
                    "max_hits_per_laser": max_per_laser,
                    "busiest_laser_id": busiest_laser,
                    "busiest_laser_azimuth_wraps": wraps,
                    "source_sha256": pick["sha256"],
                    "sha256": hashlib.sha256(xyz).hexdigest(),
                })
        while gz.read(1 << 20):
            pass  # read to EOF so gzip verifies CRC32 and ISIZE

    if seen_sync != set(listed_names):
        fail(f"tar stream sync members differ from members.tsv: {len(seen_sync)} vs {len(listed_names)}")
    emitted = {row["source_member"] for row in rows} | {row["name"] for row in skipped}
    if emitted != set(selected):
        fail("not every selected revolution was processed")
    rows.sort(key=lambda row: row["utime"])
    skipped.sort(key=lambda item: item["utime"])
    tmp_index = index_path.with_suffix(".tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(tmp_index, index_path)

    aggregate = hashlib.sha256()
    for row in rows:
        aggregate.update((data_root / row["sample_path"]).read_bytes())
    value_counts = sorted(row["value_count"] for row in rows)
    n = len(value_counts)
    median = (value_counts[n // 2] if n % 2 else (value_counts[n // 2 - 1] + value_counts[n // 2]) / 2) if n else 0
    all_counts = sorted(row["hit_count"] for row in sync)
    stats = {
        "dataset_id": args.dataset_id,
        "series_id": args.series_id,
        "archive": args.archive.name,
        "sync_members_total": len(sync),
        "sync_utime_first": sync[0]["utime"],
        "sync_utime_last": sync[-1]["utime"],
        "sync_hit_count_min": all_counts[0],
        "sync_hit_count_median": all_counts[len(all_counts) // 2],
        "sync_hit_count_max": all_counts[-1],
        "sync_members_below_min_hits": sum(c < args.min_hits for c in all_counts),
        "stride": args.stride,
        "min_hits": args.min_hits,
        "selected": len(selected),
        "skipped_below_min_hits": skipped,
        "samples": len(rows),
        "hits": sum(row["hit_count"] for row in rows),
        "values": sum(row["value_count"] for row in rows),
        "bytes": sum(row["sample_size_bytes"] for row in rows),
        "median_values_per_sample": median,
        "min_values_per_sample": value_counts[0] if n else 0,
        "max_values_per_sample": value_counts[-1] if n else 0,
        "code_min": min(row["min"] for row in rows) if rows else None,
        "code_max": max(row["max"] for row in rows) if rows else None,
        "axis_code_min": [min(row["axis_min"][k] for row in rows) for k in range(3)] if rows else None,
        "axis_code_max": [max(row["axis_max"][k] for row in rows) for k in range(3)] if rows else None,
        "samples_with_z_code_zero": sum(1 for row in rows if row["z_code_zero_hits"]),
        "z_code_zero_hits": sum(row["z_code_zero_hits"] for row in rows),
        "z_code_zero_laser_ids": sorted({l for row in rows for l in row["z_code_zero_laser_ids"]}),
        "sync_members_by_busiest_laser_azimuth_wraps": dict(sorted(collections.Counter(
            str(w) for _, w in population.values()).items())),
        "sync_members_multi_revolution": sorted(
            listed_names[name]["utime"] for name, (_, w) in population.items() if w >= 2),
        "sync_max_hits_per_laser_quantiles": quantiles(sorted(m for m, _ in population.values())),
        "samples_by_busiest_laser_azimuth_wraps": dict(sorted(collections.Counter(
            str(row["busiest_laser_azimuth_wraps"]) for row in rows).items())),
        "samples_multi_revolution": [row["utime"] for row in rows if row["busiest_laser_azimuth_wraps"] >= 2],
        "sample_hit_count_quantiles": quantiles(sorted(row["hit_count"] for row in rows)),
        "aggregate_sha256_index_order": aggregate.hexdigest(),
    }
    tmp_stats = args.stats.with_suffix(".tmp")
    tmp_stats.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp_stats, args.stats)
    if not rows:
        fail("no samples emitted")
    print(
        f"build=ok samples={len(rows)} skipped={len(skipped)} hits={stats['hits']} values={stats['values']} "
        f"bytes={stats['bytes']} median_values={median} code_range={stats['code_min']}..{stats['code_max']} "
        f"z_code_zero_hits={stats['z_code_zero_hits']} in {stats['samples_with_z_code_zero']} samples "
        f"multi_revolution_samples={len(stats['samples_multi_revolution'])} "
        f"aggregate_sha256={stats['aggregate_sha256_index_order']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
