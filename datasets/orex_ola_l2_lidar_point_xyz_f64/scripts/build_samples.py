#!/usr/bin/env python3
"""Build OLA L2 lidar-return xyz float64 samples from locally downloaded products.

One sample per pinned scil2id product (sources.tsv order): the x, y, z
IEEE754LSBDouble fields (bytes 115..138 of each 186-byte record) of every
record whose label-documented flag_status means "valid return" (0, 1, 100,
101), copied bit-exactly in source record order into an N x 3 row-major
little-endian float64 array.

Missing-value policy (shared with verify_samples.py): records flagged "no
return" (2, 102) or "missing sample" (3, 103) are dropped, because their xyz is
computed from a negative sentinel range (-1128.922153 mm) and lies near the
spacecraft rather than on Bennu. Any undocumented flag value, a valid-flag
record with non-finite xyz or with a laser/scan mode other than High Energy
Linear, a product with fewer than 90% valid records, or more than 1% of kept
points outside 150..350 m from Bennu's centre is fatal. Kept points are never
clipped, reordered, or imputed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from array import array
from pathlib import Path

sys.dont_write_bytecode = True  # keep the recipe directory free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ola_l2  # noqa: E402

DATASET_ID = "orex_ola_l2_lidar_point_xyz_f64"
SERIES_ID = "ola_l2_return_xyz_f64"
INVENTORY = "collection_inventory_ola_data_calibrated_v2.csv"


def load_payload_pins(path: Path) -> dict[str, tuple[int, str]]:
    pins: dict[str, tuple[int, str]] = {}
    if not path.is_file():
        return pins
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        product, size, digest = line.split("\t")
        pins[product] = (int(size), digest)
    return pins


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--payload-sha256", type=Path, required=True)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "build_stats.json"

    rows = ola_l2.load_sources(args.sources)
    if not rows or len({row["product"] for row in rows}) != len(rows):
        raise SystemExit("sources.tsv is empty or lists a product twice")
    inventory = download_dir / INVENTORY
    if not inventory.is_file():
        raise SystemExit(f"missing {inventory}; run download.sh")
    ola_l2.cmd_check_inventory(argparse.Namespace(sources=args.sources, inventory=inventory))
    pins = load_payload_pins(args.payload_sha256)
    if pins and set(pins) != {row["product"] for row in rows}:
        raise SystemExit("payload_sha256.tsv does not cover exactly the pinned products")

    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.iterdir():
        if stale.is_file():
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    index_rows = []
    per_file = []
    total_values = total_bytes = total_records = 0
    for row in rows:
        product = row["product"]
        label_path = download_dir / row["phase"] / f"{product}.xml"
        dat_path = download_dir / row["phase"] / f"{product}.dat"
        raw_label = label_path.read_bytes()
        if len(raw_label) != row["label_bytes"] or hashlib.sha256(raw_label).hexdigest() != row["label_sha256"]:
            raise SystemExit(f"{label_path}: label differs from sources.tsv")
        label = ola_l2.parse_label(label_path, product)
        if (label["records"], label["file_size"], label["lidvid"]) != (row["records"], row["dat_bytes"], row["lidvid"]):
            raise SystemExit(f"{label_path}: records/file_size/lidvid differ from sources.tsv")
        if dat_path.stat().st_size != row["dat_bytes"]:
            raise SystemExit(f"{dat_path}: size differs from sources.tsv")
        dat_sha256 = ola_l2.sha256_file(dat_path)
        if pins and pins[product] != (row["dat_bytes"], dat_sha256):
            raise SystemExit(f"{dat_path}: SHA-256 differs from payload_sha256.tsv")

        kept = bytearray()
        stats = ola_l2.scan_table(label, dat_path, kept.extend)
        points = stats["kept_points"]
        if len(kept) != 24 * points or points < 1000:
            raise SystemExit(f"{product}: unexpected kept payload ({points} points)")
        values = array("d")
        if values.itemsize != 8:
            raise SystemExit("platform double is not 64-bit")
        values.frombytes(bytes(kept))
        if sys.byteorder != "little":
            values.byteswap()
        for axis in range(3):
            column = values[axis::3]
            if min(column) == max(column):
                raise SystemExit(f"{product}: constant xyz axis {axis}")
        stored_min, stored_max = min(values), max(values)
        sample_bytes = bytes(kept)  # source fields are already little-endian IEEE-754 doubles
        sample_name = f"{product}_xyz.f64"
        sample_path = series_dir / sample_name
        tmp_path = sample_path.with_suffix(".f64.part")
        tmp_path.write_bytes(sample_bytes)
        os.replace(tmp_path, sample_path)

        value_count = 3 * points
        total_values += value_count
        total_bytes += len(sample_bytes)
        total_records += stats["records"]
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": sample_path.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(sample_bytes),
                "value_count": value_count,
                "sample_shape": [points, 3],
                "sample_axes": ["lidar_return", "xyz_component"],
                "point_count": points,
                "phase": row["phase"],
                "product": product,
                "lidvid": row["lidvid"],
                "start_utc": row["start_utc"],
                "stop_utc": row["stop_utc"],
                "source_records": stats["records"],
                "dropped_no_return": stats["dropped_no_return"],
                "dropped_missing_sample": stats["dropped_missing_sample"],
                "flag_counts": stats["flag_counts"],
                "out_of_band_points": stats["out_of_band_points"],
                "radius_m_min": stats["radius_m_min"],
                "radius_m_max": stats["radius_m_max"],
                "min": stored_min,
                "max": stored_max,
                "source_dat_sha256": dat_sha256,
                "sha256": hashlib.sha256(sample_bytes).hexdigest(),
            }
        )
        per_file.append({"product": product, "phase": row["phase"], "dat_bytes": row["dat_bytes"], "dat_sha256": dat_sha256, **stats})
        print(
            f"sample={sample_name} records={stats['records']} kept={points} "
            f"no_return={stats['dropped_no_return']} missing={stats['dropped_missing_sample']} "
            f"radius_m=[{stats['radius_m_min']:.2f},{stats['radius_m_max']:.2f}] out_of_band={stats['out_of_band_points']}"
        )

    tmp_index = index_path.with_suffix(".jsonl.part")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    os.replace(tmp_index, index_path)
    counts = sorted(item["value_count"] for item in index_rows)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    stats_doc = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "source_records": total_records,
        "points": total_values // 3,
        "values": total_values,
        "bytes": total_bytes,
        "median_sample_values": median,
        "dropped_no_return": sum(item["dropped_no_return"] for item in per_file),
        "dropped_missing_sample": sum(item["dropped_missing_sample"] for item in per_file),
        "out_of_band_points": sum(item["out_of_band_points"] for item in per_file),
        "products": per_file,
    }
    stats_path.write_text(json.dumps(stats_doc, indent=1) + "\n", encoding="utf-8")
    print(
        f"build_summary samples={len(index_rows)} records={total_records} points={total_values // 3} "
        f"values={total_values} bytes={total_bytes} median_values={median} "
        f"dropped_no_return={stats_doc['dropped_no_return']} dropped_missing={stats_doc['dropped_missing_sample']} "
        f"out_of_band={stats_doc['out_of_band_points']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
