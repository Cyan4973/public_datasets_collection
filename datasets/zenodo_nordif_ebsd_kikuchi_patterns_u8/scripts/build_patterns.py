#!/usr/bin/env python3
"""Split locally downloaded NORDIF scan rows into one raw uint8 Kikuchi
pattern per scan point.

Inputs (all local, written by download.sh):
  downloads/<id>/{II,III}_Setting.txt
  downloads/<id>/{II,III}_EBSD.rowNNN.bin   (one scan row of C patterns each)

Outputs:
  samples/<id>/ebsd_kikuchi_pattern_u8/<map>_rNNN_cNNN.bin  (57,600 bytes)
  index/<id>/samples.jsonl
  filtered/<id>/ingest_stats.json
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

DATASET_ID = "zenodo_nordif_ebsd_kikuchi_patterns_u8"
SERIES_ID = "ebsd_kikuchi_pattern_u8"
PATTERN_SIDE = 240
PATTERN_BYTES = PATTERN_SIDE * PATTERN_SIDE
ROW_STRIDE = 8
MIN_DISTINCT = 16
MAX_DUPLICATE_FRACTION = 0.005
# map name, pinned grid (rows, cols), pinned upstream EBSD.dat size
MAPS = [("II", 59, 208, 706_867_200), ("III", 64, 323, 1_190_707_200)]


def parse_setting(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="latin-1").splitlines():
        parts = raw.rstrip("\r").split("\t")
        head = parts[0].strip()
        if head.startswith("[") and head.endswith("]"):
            current = sections.setdefault(head[1:-1], {})
        elif head and current is not None:
            current[head] = parts[1].strip() if len(parts) > 1 else ""
    return sections


def map_geometry(setting: Path, rows: int, cols: int, dat_bytes: int) -> dict:
    sections = parse_setting(setting)
    acq = sections.get("Acquisition settings", {})
    area = sections.get("Area", {})
    micro = sections.get("Microscope", {})
    if sections.get("EBSD detector", {}).get("Model") != "UF1100":
        raise SystemExit(f"{setting.name}: not a NORDIF UF1100 settings file")
    if acq.get("Resolution") != f"{PATTERN_SIDE}x{PATTERN_SIDE}":
        raise SystemExit(f"{setting.name}: acquisition resolution {acq.get('Resolution')!r}")
    n_rows, n_cols = (int(v) for v in area["Number of samples"].split("x"))
    step = float(area["Step size"])
    if (n_rows, n_cols) != (rows, cols):
        raise SystemExit(f"{setting.name}: grid {n_rows}x{n_cols} != pinned {rows}x{cols}")
    if round(float(area["Height"].split()[0]) / step) != rows or round(float(area["Width"].split()[0]) / step) != cols:
        raise SystemExit(f"{setting.name}: area height/width/step disagree with grid")
    if rows * cols * PATTERN_BYTES != dat_bytes:
        raise SystemExit(f"{setting.name}: grid does not tile the pinned EBSD.dat size")
    return {
        "rows": rows,
        "cols": cols,
        "step_um": step,
        "acquisition_gain": acq.get("Gain"),
        "acquisition_frame_rate_fps": acq.get("Frame rate"),
        "acquisition_exposure_us": acq.get("Exposure time"),
        "accelerating_voltage_kv": micro.get("Accelerating voltage"),
        "working_distance_mm": micro.get("Working distance"),
        "magnification": micro.get("Magnification"),
    }


def load_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if fields and not fields[0].startswith("#"):
                pins[fields[0]] = fields[-1]
    return pins


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    args = parser.parse_args()
    data_root: Path = args.data_root
    downloads = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    series_dir = samples_root / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"

    pins = load_pins(args.pins)
    if not pins:
        print(f"WARNING: no pinned row checksums at {args.pins}; row sha256 values are only reported", file=sys.stderr)

    if samples_root.exists():
        shutil.rmtree(samples_root)
    series_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    histogram = [0] * 256
    aggregate = hashlib.sha256()
    pattern_hashes: dict[str, str] = {}
    duplicates: list[list[str]] = []
    maps_stats: dict[str, dict] = {}
    rows_info: list[dict] = []
    total_samples = 0
    total_bytes = 0
    min_distinct = 256
    index_tmp = index_path.with_suffix(".jsonl.part")
    with index_tmp.open("w", encoding="utf-8") as index:
        for name, rows, cols, dat_bytes in MAPS:
            geometry = map_geometry(downloads / f"{name}_Setting.txt", rows, cols, dat_bytes)
            map_samples = 0
            map_sat = 0
            for row in range(0, rows, ROW_STRIDE):
                row_file = downloads / f"{name}_EBSD.row{row:03d}.bin"
                data = row_file.read_bytes()
                if len(data) != cols * PATTERN_BYTES:
                    raise SystemExit(f"{row_file.name}: {len(data)} bytes != {cols} * {PATTERN_BYTES}")
                row_sha = hashlib.sha256(data).hexdigest()
                if pins and pins.get(row_file.name) != row_sha:
                    raise SystemExit(f"{row_file.name}: sha256 {row_sha} != pinned {pins.get(row_file.name)}")
                rows_info.append({"file": row_file.name, "bytes": len(data), "sha256": row_sha})
                row_offset = row * cols * PATTERN_BYTES
                for col in range(cols):
                    pattern = data[col * PATTERN_BYTES:(col + 1) * PATTERN_BYTES]
                    tally = collections.Counter(pattern)
                    counts = [tally.get(v, 0) for v in range(256)]
                    present = [v for v in range(256) if counts[v]]
                    distinct = len(present)
                    if distinct < 2:
                        raise SystemExit(f"{name} row {row} col {col}: constant pattern")
                    if distinct < MIN_DISTINCT:
                        raise SystemExit(f"{name} row {row} col {col}: only {distinct} distinct values")
                    min_distinct = min(min_distinct, distinct)
                    for v in present:
                        histogram[v] += counts[v]
                    digest = hashlib.sha256(pattern).hexdigest()
                    rel = f"samples/{DATASET_ID}/{SERIES_ID}/{name}_r{row:03d}_c{col:03d}.bin"
                    if digest in pattern_hashes:
                        duplicates.append([pattern_hashes[digest], rel])
                    else:
                        pattern_hashes[digest] = rel
                    (data_root / rel).write_bytes(pattern)
                    aggregate.update(pattern)
                    record = {
                        "dataset_id": DATASET_ID,
                        "series_id": SERIES_ID,
                        "sample_path": rel,
                        "numeric_kind": "uint",
                        "bit_width": 8,
                        "endianness": "little",
                        "element_size_bytes": 1,
                        "sample_size_bytes": PATTERN_BYTES,
                        "value_count": PATTERN_BYTES,
                        "shape": [PATTERN_SIDE, PATTERN_SIDE],
                        "axes": ["detector_row", "detector_col"],
                        "scan_map": name,
                        "scan_row": row,
                        "scan_col": col,
                        "source_file": f"{name}_EBSD.dat",
                        "source_byte_offset": row_offset + col * PATTERN_BYTES,
                        "min": present[0],
                        "max": present[-1],
                        "distinct_values": distinct,
                        "count_255": counts[255],
                        "count_0": counts[0],
                        "sha256": digest,
                    }
                    index.write(json.dumps(record, separators=(",", ":")) + "\n")
                    map_samples += 1
                    map_sat += counts[255]
                    total_samples += 1
                    total_bytes += PATTERN_BYTES
            maps_stats[name] = dict(geometry, selected_rows=list(range(0, rows, ROW_STRIDE)), samples=map_samples,
                                    saturated_255_fraction=round(map_sat / (map_samples * PATTERN_BYTES), 8))
    if len(duplicates) > MAX_DUPLICATE_FRACTION * total_samples:
        raise SystemExit(f"{len(duplicates)} byte-identical duplicate patterns exceed {MAX_DUPLICATE_FRACTION:.1%}")
    os.replace(index_tmp, index_path)

    total_values = sum(histogram)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "row_stride": ROW_STRIDE,
        "samples": total_samples,
        "total_bytes": total_bytes,
        "value_min": next(v for v in range(256) if histogram[v]),
        "value_max": next(v for v in range(255, -1, -1) if histogram[v]),
        "distinct_values_overall": sum(1 for c in histogram if c),
        "min_distinct_values_per_pattern": min_distinct,
        "mean_value": round(sum(v * c for v, c in enumerate(histogram)) / total_values, 4),
        "saturated_255_fraction": round(histogram[255] / total_values, 8),
        "zero_fraction": round(histogram[0] / total_values, 8),
        "duplicate_patterns": len(duplicates),
        "duplicate_examples": duplicates[:10],
        "aggregate_sha256": aggregate.hexdigest(),
        "maps": maps_stats,
        "rows": rows_info,
        "histogram": histogram,
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(
        f"build ok samples={total_samples} bytes={total_bytes} "
        f"range={stats['value_min']}..{stats['value_max']} mean={stats['mean_value']} "
        f"sat255={stats['saturated_255_fraction']} zero={stats['zero_fraction']} "
        f"duplicates={len(duplicates)} aggregate_sha256={stats['aggregate_sha256']}"
    )
    for name, info in maps_stats.items():
        print(f"map {name}: grid={info['rows']}x{info['cols']} rows={info['selected_rows']} samples={info['samples']} "
              f"sat255={info['saturated_255_fraction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
