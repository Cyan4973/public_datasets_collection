#!/usr/bin/env python3
"""Build one uint8 reflectivity sample per /livox/lidar PointCloud2 frame.

Steps (local files only):
  1. check the downloaded zip (size, MD5, members, metadata.yaml: sqlite3 storage,
     2,772 /livox/lidar messages);
  2. extract the db3 member (CRC-checked by zipfile) to extracted/<id>/;
  3. query messages JOIN topics WHERE name='/livox/lidar' ORDER BY timestamp, id;
  4. parse every CDR PointCloud2 (fields array honoured, point_step 26,
     intensity FLOAT32 at offset 12) and write the intensity of every point,
     in native scan order, as one byte (every value must be an exact integer
     0..255; anything else is fatal);
  5. delete the extracted db3.

Outputs
  samples/<id>/<series>/<frame_index:04d>_<bag_timestamp_ns>.u8
  index/<id>/samples.jsonl
  filtered/<id>/build_stats.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import livox_bag as L  # noqa: E402

MAX_MODE_FRACTION = 0.80


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--keep-extracted", action="store_true")
    args = ap.parse_args()
    root = args.data_root.resolve()
    zip_path = root / "downloads" / L.DATASET_ID / L.ZIP_NAME
    extract_dir = root / "extracted" / L.DATASET_ID / "build"
    series_dir = root / "samples" / L.DATASET_ID / L.SERIES_ID
    index_dir = root / "index" / L.DATASET_ID
    filtered_dir = root / "filtered" / L.DATASET_ID
    for d in (series_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)

    if not zip_path.is_file():
        raise SystemExit(f"BUILD FAIL missing {zip_path}; run download.sh first")
    L.check_zip(zip_path, None, full_crc=False)
    md5 = md5_file(zip_path)
    if md5 != L.ZIP_MD5:
        raise SystemExit(f"BUILD FAIL zip md5 {md5} != {L.ZIP_MD5}")
    print(f"zip ok size={L.ZIP_SIZE} md5={md5}")

    extract_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(extract_dir).free
    if free < L.DB_SIZE + (512 << 20):
        raise SystemExit(f"BUILD FAIL need ~{L.DB_SIZE + (512 << 20)} free bytes for the db3 extract, have {free}")

    for stale in series_dir.glob("*"):
        stale.unlink()

    db_path = None
    try:
        db_path = L.extract_db(zip_path, extract_dir)
        print(f"extracted {db_path.name} ({db_path.stat().st_size} bytes, CRC ok)")
        con = L.open_db(db_path)
        index_rows = []
        stats = []
        total_hist = [0] * 256
        prev_ts = None
        for frame_index, (msg_id, bag_ts, data) in enumerate(L.iter_lidar_messages(con)):
            try:
                res = L.frame_reflectivity(bytes(data))
            except L.CdrError as exc:
                raise SystemExit(f"BUILD FAIL message id={msg_id} ts={bag_ts}: {exc}")
            if prev_ts is not None and bag_ts <= prev_ts:
                raise SystemExit(f"BUILD FAIL non-increasing timestamp at message id={msg_id}")
            prev_ts = bag_ts
            refl = res["reflectivity"]
            n = res["points"]
            counter = collections.Counter(refl)
            hist = [counter.get(v, 0) for v in range(256)]
            distinct = sum(1 for c in hist if c)
            mode_value = max(range(256), key=lambda v: hist[v])
            mode_fraction = hist[mode_value] / n
            if distinct < 2:
                raise SystemExit(f"BUILD FAIL message id={msg_id}: constant reflectivity")
            if mode_fraction > MAX_MODE_FRACTION:
                raise SystemExit(f"BUILD FAIL message id={msg_id}: value {mode_value} covers {mode_fraction:.3f} of points")
            name = f"{frame_index:04d}_{bag_ts}.u8"
            out = series_dir / name
            tmp = out.with_suffix(".u8.part")
            tmp.write_bytes(refl)
            os.replace(tmp, out)
            for v in range(256):
                total_hist[v] += hist[v]
            vmin = min(v for v in range(256) if hist[v])
            vmax = max(v for v in range(256) if hist[v])
            info = {
                "frame_index": frame_index,
                "message_id": msg_id,
                "bag_timestamp_ns": bag_ts,
                "header_stamp_ns": res["stamp_ns"],
                "points": n,
                "no_return_points": res["no_return_points"],
                "zero_fraction": round(hist[0] / n, 6),
                "no_return_fraction": round(res["no_return_points"] / n, 6),
                "retroreflective_fraction": round(sum(hist[151:]) / n, 6),
                "distinct_values": distinct,
                "mode_value": mode_value,
                "mode_fraction": round(mode_fraction, 6),
                "min": vmin,
                "max": vmax,
            }
            stats.append(info)
            index_rows.append({
                "dataset_id": L.DATASET_ID,
                "series_id": L.SERIES_ID,
                "sample_path": str(out.relative_to(root)),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": n,
                "value_count": n,
                "sample_shape": [n],
                "frame_index": frame_index,
                "message_id": msg_id,
                "bag_timestamp_ns": bag_ts,
                "header_stamp_ns": res["stamp_ns"],
                "no_return_points": res["no_return_points"],
                "sha256": hashlib.sha256(refl).hexdigest(),
                "min": vmin,
                "max": vmax,
                "zero_fraction": info["zero_fraction"],
                "distinct_values": distinct,
            })
            if frame_index % 200 == 0:
                print(f"frame={frame_index} id={msg_id} points={n} zero={info['zero_fraction']:.4f} "
                      f"no_return={info['no_return_fraction']:.4f} distinct={distinct} max={vmax}")
        con.close()
    finally:
        if db_path is not None and not args.keep_extracted:
            db_path.unlink(missing_ok=True)
        for p in extract_dir.glob("*.part"):
            p.unlink()
        if not args.keep_extracted:
            shutil.rmtree(extract_dir, ignore_errors=True)

    if len(index_rows) != L.LIDAR_MESSAGES:
        raise SystemExit(f"BUILD FAIL {len(index_rows)} lidar frames, expected {L.LIDAR_MESSAGES}")

    index_path = index_dir / "samples.jsonl"
    tmp = index_path.with_suffix(".jsonl.part")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, index_path)

    counts = sorted(r["value_count"] for r in index_rows)
    m = len(counts)
    median = counts[m // 2] if m % 2 else (counts[m // 2 - 1] + counts[m // 2]) / 2
    total = sum(counts)
    zf = sorted(s["zero_fraction"] for s in stats)
    nr = sorted(s["no_return_fraction"] for s in stats)
    width_hist: dict[int, int] = {}
    for c in counts:
        width_hist[c] = width_hist.get(c, 0) + 1
    no_return_total = sum(s["no_return_points"] for s in stats)
    summary = {
        "dataset_id": L.DATASET_ID,
        "series_id": L.SERIES_ID,
        "sample_count": m,
        "total_values": total,
        "total_size_bytes": total,
        "median_values": median,
        "min_values": counts[0],
        "max_values": counts[-1],
        "points_per_frame_histogram": {str(k): v for k, v in sorted(width_hist.items())},
        "overall_zero_fraction": round(total_hist[0] / total, 6),
        "overall_no_return_fraction": round(no_return_total / total, 6),
        "zero_fraction_min": zf[0],
        "zero_fraction_median": zf[m // 2],
        "zero_fraction_max": zf[-1],
        "no_return_fraction_min": nr[0],
        "no_return_fraction_median": nr[m // 2],
        "no_return_fraction_max": nr[-1],
        "max_mode_fraction": max(s["mode_fraction"] for s in stats),
        "overall_distinct_values": sum(1 for c in total_hist if c),
        "overall_max": max(v for v in range(256) if total_hist[v]),
        "overall_retroreflective_fraction_151_255": round(sum(total_hist[151:]) / total, 6),
        "histogram": total_hist,
        "samples": stats,
    }
    (filtered_dir / "build_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"samples={m} total_bytes={total} median_values={median} min={counts[0]} max={counts[-1]} "
          f"zero_fraction overall={summary['overall_zero_fraction']} no_return overall={summary['overall_no_return_fraction']} "
          f"max_mode_fraction={summary['max_mode_fraction']} distinct={summary['overall_distinct_values']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
