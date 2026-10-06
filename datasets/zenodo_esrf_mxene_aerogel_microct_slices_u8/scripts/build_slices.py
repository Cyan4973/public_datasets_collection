#!/usr/bin/env python3
"""Emit one raw uint8 1381x1381 sample per range-fetched reconstructed axial
slice of the ESRF ID15 MXene aerogel micro-CT volumes (local files only).

Inputs (written by download.sh):
  downloads/<id>/descriptors/NNpercent.txt
  downloads/<id>/slices/sNN_zZZZZ.bin     (one axial slice, 1,907,161 bytes)
Outputs:
  samples/<id>/mxene_aerogel_microct_slice_u8/strainNNpct_zZZZZ.bin
  index/<id>/samples.jsonl
  filtered/<id>/ingest_stats.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_metadata import load_volumes  # noqa: E402
from check_slice import SIDE, SLICE_BYTES, load_pins, slice_problems  # noqa: E402

DATASET_ID = "zenodo_esrf_mxene_aerogel_microct_slices_u8"
SERIES_ID = "mxene_aerogel_microct_slice_u8"
SLICES_PER_VOLUME = 20
MARGIN_PCT = 5


def plan(z_slices: int) -> list[int]:
    margin = (z_slices * MARGIN_PCT + 99) // 100
    lo, hi = margin, z_slices - 1 - margin
    den = SLICES_PER_VOLUME - 1
    return [lo + (k * (hi - lo) + den // 2) // den for k in range(SLICES_PER_VOLUME)]


def descriptor_lattice(path: Path) -> tuple[int, int, int]:
    text = path.read_text(encoding="ascii")
    match = re.search(r"(\d+)\s*x\s*(\d+)\s*x\s*(\d+)", text)
    if not match:
        raise SystemExit(f"{path.name}: no lattice in descriptor")
    return tuple(int(v) for v in match.groups())  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--volumes", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    args = parser.parse_args()
    root: Path = args.data_root
    downloads = root / "downloads" / DATASET_ID
    samples_root = root / "samples" / DATASET_ID
    series_dir = samples_root / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"

    volumes = load_volumes(args.volumes)
    pins = load_pins(str(args.pins))
    if not pins:
        print(f"WARNING: no pinned slice checksums at {args.pins}; sha256 values are only reported", file=sys.stderr)

    if samples_root.exists():
        shutil.rmtree(samples_root)
    series_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    histogram = [0] * 256
    seen: dict[str, str] = {}
    listing = hashlib.sha256()
    per_volume = []
    total_samples = total_bytes = 0
    index_tmp = index_path.with_suffix(".jsonl.part")
    with index_tmp.open("w", encoding="utf-8") as index:
        for vol in volumes:
            nx, ny, nz = descriptor_lattice(downloads / "descriptors" / vol["txt_key"])
            if (nx, ny) != (SIDE, SIDE) or nz != vol["z_slices"] or nx * ny * nz != vol["raw_bytes"]:
                raise SystemExit(f"{vol['txt_key']}: lattice {nx}x{ny}x{nz} disagrees with volumes.tsv")
            zs = plan(nz)
            means = []
            for z in zs:
                src_name = f"s{vol['strain']}_z{z:04d}.bin"
                data = (downloads / "slices" / src_name).read_bytes()
                if len(data) != SLICE_BYTES:
                    raise SystemExit(f"{src_name}: {len(data)} bytes != {SLICE_BYTES}")
                digest = hashlib.sha256(data).hexdigest()
                if pins and pins.get(src_name) != digest:
                    raise SystemExit(f"{src_name}: sha256 {digest} != pinned {pins.get(src_name)}")
                problems, stats = slice_problems(data)
                if problems:
                    raise SystemExit(f"{src_name}: degenerate slice: {'; '.join(problems)}")
                if digest in seen:
                    raise SystemExit(f"{src_name}: duplicate of {seen[digest]}")
                seen[digest] = src_name
                for value, count in enumerate(stats["counts"]):
                    histogram[value] += count
                name = f"strain{vol['strain']}pct_z{z:04d}.bin"
                rel = f"samples/{DATASET_ID}/{SERIES_ID}/{name}"
                (root / rel).write_bytes(data)
                listing.update(f"{name}\t{digest}\n".encode())
                means.append(stats["mean"])
                row = {
                    "dataset_id": DATASET_ID,
                    "series_id": SERIES_ID,
                    "sample_path": rel,
                    "numeric_kind": "uint",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "sample_size_bytes": SLICE_BYTES,
                    "value_count": SLICE_BYTES,
                    "shape": [SIDE, SIDE],
                    "axes": ["voxel_y", "voxel_x"],
                    "strain_pct": int(vol["strain"]),
                    "z_index": z,
                    "z_slices": nz,
                    "source_record": vol["record"],
                    "source_file": vol["raw_key"],
                    "source_byte_offset": z * SLICE_BYTES,
                    "min": stats["min"],
                    "max": stats["max"],
                    "mean": round(stats["mean"], 4),
                    "distinct_values": stats["distinct"],
                    "zeros": stats["zeros"],
                    "saturated_255": stats["saturated"],
                    "sha256": digest,
                }
                index.write(json.dumps(row, separators=(",", ":")) + "\n")
                total_samples += 1
                total_bytes += SLICE_BYTES
            per_volume.append({
                "strain_pct": int(vol["strain"]),
                "record": vol["record"],
                "file": vol["raw_key"],
                "z_slices": nz,
                "kept_z": zs,
                "mean_grey_min": round(min(means), 3),
                "mean_grey_max": round(max(means), 3),
            })
    os.replace(index_tmp, index_path)

    n = sum(histogram)
    stats_out = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "slices_per_volume": SLICES_PER_VOLUME,
        "margin_pct": MARGIN_PCT,
        "samples": total_samples,
        "total_bytes": total_bytes,
        "value_min": next(v for v in range(256) if histogram[v]),
        "value_max": next(v for v in range(255, -1, -1) if histogram[v]),
        "mean_value": round(sum(v * c for v, c in enumerate(histogram)) / n, 4),
        "zero_fraction": round(histogram[0] / n, 8),
        "saturated_255_fraction": round(histogram[255] / n, 8),
        "listing_sha256": listing.hexdigest(),
        "volumes": per_volume,
        "histogram": histogram,
    }
    stats_path.write_text(json.dumps(stats_out, indent=1) + "\n", encoding="utf-8")
    print(f"build ok samples={total_samples} bytes={total_bytes} range={stats_out['value_min']}..{stats_out['value_max']} "
          f"mean={stats_out['mean_value']} zero={stats_out['zero_fraction']} sat255={stats_out['saturated_255_fraction']} "
          f"listing_sha256={stats_out['listing_sha256']}")
    for vol in per_volume:
        print(f"strain {vol['strain_pct']:02d}% Z={vol['z_slices']} kept={len(vol['kept_z'])} "
              f"slice-mean range {vol['mean_grey_min']}..{vol['mean_grey_max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
