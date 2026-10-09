#!/usr/bin/env python3
"""Build Boreas Velodyne Alpha Prime per-point intensity uint8 samples.

For every pinned sweep (sources.tsv) the source `.bin` (N x 6 little-endian
float32: x, y, z, intensity, laser_number, time) is validated with the shared
policy in boreas_lidar.decode_sweep (size multiple of 24, all fields finite,
intensity integral in 0..255, laser_number integral in 0..127; any violation
is fatal, nothing is clamped) and field 3 (intensity) is written as one byte
per point in native point order: one N-byte uint8 sample per sweep.

Outputs
  samples/<id>/<series>/<sequence>__<timestamp_us>.u8
  index/<id>/samples.jsonl
  filtered/<id>/build_stats.json   (per-sample zero fraction, distinct values, ...)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boreas_lidar  # noqa: E402

DATASET_ID = "boreas_velodyne_alpha_prime_intensity_u8"
SERIES_ID = "boreas_alpha_prime_sweep_intensity_u8"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for d in (series_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*"):
        stale.unlink()

    rows = boreas_lidar.load_sources(args.sources)
    index_rows = []
    stats = []
    total_hist = [0] * 256
    for row in rows:
        src = boreas_lidar.local_path(download_dir, row)
        problem = boreas_lidar.check_one(src, row, semantic=False)
        if problem:
            raise SystemExit(f"BUILD FAIL {row['key']}: {problem}")
        raw = src.read_bytes()
        try:
            res = boreas_lidar.decode_sweep(raw, row["key"])
        except ValueError as exc:
            raise SystemExit(f"BUILD FAIL {exc}")
        data = res["intensity"]
        hist = res["hist"]
        n = res["point_count"]
        if n != row["point_count"]:
            raise SystemExit(f"BUILD FAIL {row['key']}: point count {n} != pinned {row['point_count']}")
        distinct = sum(1 for c in hist if c)
        mode_value = max(range(256), key=lambda v: hist[v])
        if distinct < 2:
            raise SystemExit(f"BUILD FAIL {row['key']}: constant intensity")
        name = f"{row['sequence']}__{row['timestamp_us']}.u8"
        out = series_dir / name
        tmp = out.with_suffix(".u8.part")
        tmp.write_bytes(data)
        os.replace(tmp, out)
        for v in range(256):
            total_hist[v] += hist[v]
        vmin = min(v for v in range(256) if hist[v])
        vmax = max(v for v in range(256) if hist[v])
        info = {
            "sequence": row["sequence"],
            "timestamp_us": row["timestamp_us"],
            "point_count": n,
            "zero_fraction": round(hist[0] / n, 6),
            "retroreflective_fraction": round(sum(hist[101:]) / n, 6),
            "distinct_values": distinct,
            "mode_value": mode_value,
            "mode_fraction": round(hist[mode_value] / n, 6),
            "min": vmin,
            "max": vmax,
            "distinct_rings": res["distinct_rings"],
            "time_offset_min_s": round(res["time_min"], 6),
            "time_offset_max_s": round(res["time_max"], 6),
        }
        stats.append(info)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(data),
            "value_count": len(data),
            "sample_shape": [len(data)],
            "sequence": row["sequence"],
            "timestamp_us": row["timestamp_us"],
            "source_key": row["key"],
            "source_md5": row["md5"],
            "source_size_bytes": row["size_bytes"],
            "sha256": hashlib.sha256(data).hexdigest(),
            "min": vmin,
            "max": vmax,
            "zero_fraction": info["zero_fraction"],
            "distinct_values": distinct,
        })
        print(f"sample={name} points={n} zero_fraction={info['zero_fraction']:.4f} "
              f"distinct={distinct} max={vmax} rings={res['distinct_rings']}")

    index_path = index_dir / "samples.jsonl"
    tmp = index_path.with_suffix(".jsonl.part")
    with tmp.open("w", encoding="utf-8") as handle:
        for r in index_rows:
            handle.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, index_path)

    counts = sorted(r["value_count"] for r in index_rows)
    m = len(counts)
    median = counts[m // 2] if m % 2 else (counts[m // 2 - 1] + counts[m // 2]) / 2
    total = sum(counts)
    zf = sorted(s["zero_fraction"] for s in stats)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": m,
        "sequence_count": len({s["sequence"] for s in stats}),
        "total_values": total,
        "total_size_bytes": total,
        "median_values": median,
        "min_values": counts[0],
        "max_values": counts[-1],
        "overall_zero_fraction": round(total_hist[0] / total, 6),
        "zero_fraction_min": zf[0],
        "zero_fraction_median": zf[m // 2],
        "zero_fraction_max": zf[-1],
        "overall_distinct_values": sum(1 for c in total_hist if c),
        "overall_retroreflective_fraction": round(sum(total_hist[101:]) / total, 6),
        "histogram": total_hist,
        "samples": stats,
    }
    (filtered_dir / "build_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"samples={m} total_bytes={total} median_values={median} "
          f"zero_fraction overall={summary['overall_zero_fraction']} "
          f"min={zf[0]} median={zf[m // 2]} max={zf[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
