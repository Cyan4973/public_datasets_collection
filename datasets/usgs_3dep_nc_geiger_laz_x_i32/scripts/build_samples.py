#!/usr/bin/env python3
"""Build per-tile little-endian int32 X samples from the downloaded LAZ tiles.

Each pinned tile is decoded chunk by chunk with the repository's pure-stdlib
LASzip decoder (tools/laz/laszip.py, iter_chunks). The sample is the X field
(first little-endian int32 of every 30-byte LAS 1.4 point format 6 record) of
every point record in file order, copied byte for byte (no scaling, no float
conversion). One sample file per tile.

Missing-value policy (shared with verify_samples.py): LAS records have no
missing X. Every record is kept, whatever its classification, withheld or
overlap flag. The decoded record count must equal the header point count, and
every stored X must lie within the header X bounds converted to ticks
(round(bound / 0.01), +-1 tick); any violation is fatal.
"""
from __future__ import annotations

import argparse
import array
import csv
import datetime
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "laz"))
import laszip  # noqa: E402

DATASET_ID = "usgs_3dep_nc_geiger_laz_x_i32"
SERIES_ID = "nc_geiger_anson_2016_x_i32"
RECORD = 30


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        row["pc_count"] = int(row["pc_count"])
        row["size_bytes"] = int(row["size_bytes"])
    return rows


def build_tile(job: tuple) -> dict:
    row, laz_path, out_path = job
    started = time.time()
    hdr = laszip.read_header(str(laz_path))
    if hdr["point_format"] != 6 or hdr["point_record_length"] != RECORD or hdr["scale"][0] != 0.01 or hdr["offset"][0] != 0.0:
        raise SystemExit(f"{laz_path.name}: unexpected header {hdr['point_format']} {hdr['point_record_length']} {hdr['scale']} {hdr['offset']}")
    if not hdr["global_encoding"] & 1:
        raise SystemExit(f"{laz_path.name}: global_encoding {hdr['global_encoding']} lacks the adjusted-standard GPS time bit")
    expected = hdr["point_count"]
    if expected != row["pc_count"]:
        raise SystemExit(f"{laz_path.name}: header count {expected} != pinned {row['pc_count']}")
    lo_tick = round(hdr["min"][0] / 0.01) - 1
    hi_tick = round(hdr["max"][0] / 0.01) + 1
    out = bytearray(4 * expected)
    pos = 0
    channels = 0
    chunks = 0
    gps_min = float("inf")
    gps_max = float("-inf")
    for _index, n, recs in laszip.iter_chunks(str(laz_path)):
        span = recs[:RECORD * n]
        if len(span) != RECORD * n or pos + 4 * n > len(out):
            raise SystemExit(f"{laz_path.name}: chunk size mismatch")
        for lane in range(4):
            out[pos + lane:pos + 4 * n:4] = span[lane::RECORD]
        # Scanner channel bits (flags byte 15, bits 4-5) for the stats file.
        if not channels and any(b & 0x30 for b in span[15::RECORD]):
            channels = 1
        # GPS time (float64 at bytes 22-29): byte-lane copy, recorded in build_stats.json only.
        gps_raw = bytearray(8 * n)
        for lane in range(8):
            gps_raw[lane::8] = span[22 + lane::RECORD]
        gps = array.array("d")
        gps.frombytes(bytes(gps_raw))
        if sys.byteorder != "little":
            gps.byteswap()
        gps_min = min(gps_min, min(gps))
        gps_max = max(gps_max, max(gps))
        pos += 4 * n
        chunks += 1
    if pos != len(out):
        raise SystemExit(f"{laz_path.name}: decoded {pos // 4} points, header says {expected}")
    values = array.array("i")
    values.frombytes(bytes(out))
    if sys.byteorder != "little":
        values.byteswap()
    vmin, vmax = min(values), max(values)
    if vmin < lo_tick or vmax > hi_tick:
        raise SystemExit(f"{laz_path.name}: X ticks {vmin}..{vmax} outside header bounds {lo_tick}..{hi_tick}")
    if vmin == vmax:
        raise SystemExit(f"{laz_path.name}: constant X")
    tmp = out_path.with_suffix(".tmp")
    tmp.write_bytes(out)
    os.replace(tmp, out_path)
    return {
        "tile_id": row["tile_id"],
        "file_name": row["file_name"],
        "point_count": expected,
        "chunks": chunks,
        "min": vmin,
        "max": vmax,
        "header_min_tick": lo_tick + 1,
        "header_max_tick": hi_tick - 1,
        "nonzero_scanner_channel": bool(channels),
        "gps_time_min": gps_min,
        "gps_time_max": gps_max,
        "sha256": hashlib.sha256(out).hexdigest(),
        "seconds": round(time.time() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()
    data_root = Path(args.data_root)
    rows = load_sources(Path(args.sources))
    download_dir = data_root / "downloads" / DATASET_ID / "laz"
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for path in (sample_dir, index_dir, filtered_dir):
        path.mkdir(parents=True, exist_ok=True)
    for stale in sample_dir.glob("*"):
        stale.unlink()
    jobs = []
    for row in rows:
        stem = row["file_name"][:-len(".laz")]
        jobs.append((row, download_dir / row["file_name"], sample_dir / f"{stem}.x_i32le.bin"))
    workers = args.workers or min(len(jobs), max(1, (os.cpu_count() or 2) - 1))
    print(f"decoding tiles={len(jobs)} workers={workers}", flush=True)
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for job, result in zip(jobs, pool.map(build_tile, jobs)):
            results[job[0]["tile_id"]] = result
            print(f"tile={result['tile_id']} points={result['point_count']} x={result['min']}..{result['max']} seconds={result['seconds']}", flush=True)
    index_rows = []
    total_values = 0
    for (row, _laz, out_path) in jobs:
        res = results[row["tile_id"]]
        size = out_path.stat().st_size
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out_path.relative_to(data_root)),
            "numeric_kind": "int",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": res["point_count"],
            "sample_shape": [res["point_count"]],
            "tile_id": row["tile_id"],
            "source_file": row["file_name"],
            "source_url": row["url"],
            "min": res["min"],
            "max": res["max"],
            "unit": "0.01 US survey foot (NAD83(2011) North Carolina State Plane easting, offset 0)",
            "sha256": res["sha256"],
        })
        total_values += res["point_count"]
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    stats = {
        "samples": len(index_rows),
        "values": total_values,
        "bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "tiles": [results[r["tile_id"]] for r in rows],
    }
    # Point GPS time is adjusted standard GPS time (header global_encoding bit 0):
    # calendar time = GPS epoch 1980-01-06T00:00:00 + gps_time + 1e9 s (GPS time scale, no leap seconds).
    gps_lo = min(t["gps_time_min"] for t in stats["tiles"])
    gps_hi = max(t["gps_time_max"] for t in stats["tiles"])
    epoch = datetime.datetime(1980, 1, 6)
    stats["gps_time_window"] = {
        "adjusted_standard_min": gps_lo,
        "adjusted_standard_max": gps_hi,
        "gps_calendar_min": (epoch + datetime.timedelta(seconds=gps_lo + 1e9)).isoformat(timespec="seconds"),
        "gps_calendar_max": (epoch + datetime.timedelta(seconds=gps_hi + 1e9)).isoformat(timespec="seconds"),
    }
    (filtered_dir / "build_stats.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    counts = sorted(r["value_count"] for r in index_rows)
    print(f"samples={stats['samples']} values={stats['values']} bytes={stats['bytes']} "
          f"min_values={counts[0]} max_values={counts[-1]} "
          f"nonzero_channel_tiles={sum(1 for t in stats['tiles'] if t['nonzero_scanner_channel'])}")
    window = stats["gps_time_window"]
    print(f"gps_time_window adjusted_standard={window['adjusted_standard_min']}..{window['adjusted_standard_max']} "
          f"gps_calendar={window['gps_calendar_min']}..{window['gps_calendar_max']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
