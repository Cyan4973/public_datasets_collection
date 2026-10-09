#!/usr/bin/env python3
"""Build step: decode each pinned Phase I LAZ tile and emit its scan angle rank.

usage: extract_scan_angle.py TILES_TSV DATA_ROOT REPO_ROOT [WORKERS]

For every tile in scripts/tiles.tsv (local file only):
  * read the header with tools/laz/laszip.py and assert LAS 1.2, PDRF 1 with
    the compression bit, record length 28, LASzip compressor 2, pinned count;
  * decode all points with laszip.iter_chunks (50,000-point chunks);
  * take byte 16 of every 28-byte PDRF-1 record (LAS 1.2 "Scan Angle Rank",
    a signed char in whole degrees, -90..+90) and write it unchanged, in file
    point order, as a raw int8 array <tile>.bin;
  * reject the tile (fatal) when the stream is degenerate: fewer than 5
    distinct values, one value holding more than half of the points, a
    max-min span under 10 degrees, or any value outside -90..+90.
Writes index/<id>/samples.jsonl and filtered/<id>/ingest_stats.json.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import os
import shutil
import sys
from multiprocessing import Pool
from pathlib import Path

DATASET_ID = "srsp_scotland_phase1_lidar_scan_angle_i8"
SERIES_ID = "srsp_phase1_scan_angle_rank_i8"
SCAN_ANGLE_OFFSET = 16
RECORD_LENGTH = 28
MIN_DISTINCT = 5
MAX_MODE_SHARE = 0.5
MIN_SPAN = 10

CTX: dict = {}


def init(repo_root: str, data_root: str) -> None:
    sys.path.insert(0, str(Path(repo_root) / "tools" / "laz"))
    import laszip  # noqa: E402
    CTX["laszip"] = laszip
    CTX["data_root"] = Path(data_root)


def signed(v: int) -> int:
    return v - 256 if v > 127 else v


def process(tile: dict) -> dict:
    laszip = CTX["laszip"]
    data_root = CTX["data_root"]
    name = Path(tile["key"]).name
    src = data_root / "downloads" / DATASET_ID / "laz" / name
    if not src.is_file():
        raise RuntimeError(f"missing local tile {src}")
    hdr = laszip.read_header(str(src))
    lz = hdr["laszip"] or {}
    if (hdr["version"], hdr["point_format"], hdr["compressed"], hdr["point_record_length"],
            lz.get("compressor")) != ("1.2", 1, True, RECORD_LENGTH, 2):
        raise RuntimeError(f"{name}: unexpected layout {hdr['version']} pf{hdr['point_format']} "
                           f"rl{hdr['point_record_length']} compressor {lz.get('compressor')}")
    if hdr["point_count"] != int(tile["point_count"]):
        raise RuntimeError(f"{name}: point count {hdr['point_count']} != pinned {tile['point_count']}")
    out = data_root / "samples" / DATASET_ID / SERIES_ID / (Path(name).stem + ".bin")
    tmp = out.with_suffix(".bin.tmp")
    hist: collections.Counter = collections.Counter()
    sha = hashlib.sha256()
    n = 0
    with tmp.open("wb") as dst:
        for _, count, records in laszip.iter_chunks(str(src), header=hdr):
            if len(records) != count * RECORD_LENGTH:
                raise RuntimeError(f"{name}: chunk record bytes {len(records)} != {count} x 28")
            angles = bytes(records[SCAN_ANGLE_OFFSET::RECORD_LENGTH])
            dst.write(angles)
            sha.update(angles)
            hist.update(angles)
            n += count
    if n != hdr["point_count"]:
        raise RuntimeError(f"{name}: decoded {n} points, header says {hdr['point_count']}")
    shist = {signed(k): v for k, v in hist.items()}
    lo, hi = min(shist), max(shist)
    mode_value, mode_count = max(shist.items(), key=lambda kv: kv[1])
    problems = []
    if len(shist) < MIN_DISTINCT:
        problems.append(f"only {len(shist)} distinct values")
    if mode_count / n > MAX_MODE_SHARE:
        problems.append(f"value {mode_value} holds {mode_count / n:.3f} of points")
    if hi - lo < MIN_SPAN:
        problems.append(f"span {lo}..{hi}")
    if lo < -90 or hi > 90:
        problems.append(f"out of LAS range {lo}..{hi}")
    if problems:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{name}: degenerate scan angle stream: {'; '.join(problems)}")
    tmp.rename(out)
    return {
        "name": name,
        "key": tile["key"],
        "out": str(out),
        "points": n,
        "sha256": sha.hexdigest(),
        "min": lo,
        "max": hi,
        "distinct": len(shist),
        "zero_fraction": round(shist.get(0, 0) / n, 6),
        "mode_value": mode_value,
        "mode_fraction": round(mode_count / n, 6),
        "histogram": {str(k): shist[k] for k in sorted(shist)},
        "source_bytes": src.stat().st_size,
        "generating_software": hdr["generating_software"],
    }


def main() -> None:
    tiles_tsv, data_root, repo_root = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else min(16, os.cpu_count() or 1)
    with tiles_tsv.open(newline="") as fh:
        tiles = list(csv.DictReader(fh, delimiter="\t"))
    samples_dir = data_root / "samples" / DATASET_ID
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    (samples_dir / SERIES_ID).mkdir(parents=True)
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    results = []
    with Pool(workers, initializer=init, initargs=(str(repo_root), str(data_root))) as pool:
        for r in pool.imap(process, tiles):
            results.append(r)
            print(f"tile {len(results)}/{len(tiles)} {r['name']} points={r['points']} "
                  f"range={r['min']}..{r['max']} distinct={r['distinct']} "
                  f"zero={r['zero_fraction']:.4f} mode={r['mode_value']}@{r['mode_fraction']:.3f}", flush=True)

    rows = []
    for r in results:
        out = Path(r["out"])
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": out.stat().st_size,
            "value_count": r["points"],
            "sample_rank": 1,
            "sample_shape": [r["points"]],
            "sample_axes": ["las_point_order"],
            "natural_record_kind": "srsp_phase1_1km_laz_tile_scan_angle_field",
            "source_key": r["key"],
            "source_format": "LAZ (LAS 1.2 point data record format 1, LASzip compressor 2)",
            "source_field": "Scan Angle Rank (PDRF 1 byte offset 16, signed char, degrees)",
            "sample_sha256": r["sha256"],
            "min": r["min"],
            "max": r["max"],
            "distinct_values": r["distinct"],
        })
    rows.sort(key=lambda x: x["sample_path"])
    with (index_dir / "samples.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    counts = sorted(r["points"] for r in results)
    total_hist: collections.Counter = collections.Counter()
    for r in results:
        total_hist.update({int(k): v for k, v in r["histogram"].items()})
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(results),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(counts),
        "median_value_count": counts[len(counts) // 2] if len(counts) % 2 else (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2,
        "min_value_count": counts[0],
        "max_value_count": counts[-1],
        "realized_min": min(total_hist),
        "realized_max": max(total_hist),
        "overall_zero_fraction": round(total_hist.get(0, 0) / sum(counts), 6),
        "overall_histogram": {str(k): total_hist[k] for k in sorted(total_hist)},
        "tiles": [{k: v for k, v in r.items() if k != "out"} for r in results],
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(f"built samples={len(results)} values={stats['primary_values']} "
          f"median={stats['median_value_count']} range={stats['realized_min']}..{stats['realized_max']} "
          f"zero_fraction={stats['overall_zero_fraction']}")


if __name__ == "__main__":
    main()
