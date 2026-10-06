#!/usr/bin/env python3
"""Split locally downloaded ASTAR blockfile scan rows into one raw uint8
144x144 precession electron diffraction pattern per scan point.

Inputs (all local, written by download.sh):
  downloads/<id>/<scan>.header.bin         first 4096 bytes of each .blo
  downloads/<id>/<scan>.rowNNN.bin         one scan row of NX frames each

Outputs:
  samples/<id>/sped_diffraction_pattern_u8/<scan>_rNNN_cNNN.bin  (20,736 bytes)
  index/<id>/samples.jsonl
  filtered/<id>/ingest_stats.json
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import struct
import sys
from pathlib import Path

DATASET_ID = "zenodo_astar_niti_sped_patterns_u8"
SERIES_ID = "sped_diffraction_pattern_u8"
DP_SZ = 144
NPIX = DP_SZ * DP_SZ
FRAME = 6 + NPIX
HEADER_BYTES = 4096
HEADER_FMT = "<6sHIIIHHHHHddIHId"
ROW_STRIDE = 16
MIN_DISTINCT = 8
MAX_DUPLICATE_FRACTION = 0.005

# scan, Zenodo record, file key, file size, header sha256, DP offset, NX, NY
SCANS = [
    ("Fig5", 15183487, "Fig5.blo", 453_653_506, "6f6b3522fc910a845996f0b09f7eb35fcf2ec872ed7eb16d08aae5fe66835997", 25966, 135, 162),
    ("Fig6", 15183487, "Fig6.blo", 583_380_228, "7be6c4e7b05e1cba663dbd7eb9dd46615fd59a32d69965c0ae62db40b208e086", 32220, 158, 178),
    ("Fig7", 15183487, "Fig7.blo", 635_258_471, "bb35bc211256eef89ef36d0d21cb3432f68b524ea0e01f24e6cfe8fad6fc2e67", 34721, 175, 175),
    ("Fig8", 15183487, "Fig8.blo", 622_045_180, "e3492609166990d19f419fc7a5686636eb3218f79776407360de9ca2b02f3673", 34084, 147, 204),
    ("FigS5", 15183487, "Fig S5.blo", 543_055_836, "efe138455c15a638945f518ece0fe7ba6fcce64e60f15f0251c62082226aae97", 30276, 154, 170),
    ("Fig9", 15183021, "Fig9_ASTAR_NiTi5_15ms_chlazeni50MPa_zrno5_CL145mm_0p6precese.blo", 463_485_688,
     "923248db0710b62695da2058eaf6d6bb064e7391c11a020a4e5cfbb2e9d83c40", 26440, 152, 147),
    ("Fig10", 15183021, "Fig10_ASTAR_NiTi5_15ms_300MPa_chlazeni_zrno5.blo", 963_309_016,
     "e5d37c17252b1e8eb7f1b6683d4936275e7615db96c32eeee7de41557b4c6085", 50536, 215, 216),
    ("Fig11", 15183021, "Fig11_ASTAR_NiTi5_15ms_chlazeni600MPa_zrno2_CL100mm_0p5precese_2_2.blo", 430_836_206,
     "6c58ceb0e759e6cb234045c7d45be966476ce945b71daa32c367f11e129b8b15", 24866, 134, 155),
]


def parse_header(path: Path, size: int, sha: str, dp_offset: int, nx: int, ny: int) -> dict:
    blob = path.read_bytes()
    if len(blob) != HEADER_BYTES:
        raise SystemExit(f"{path.name}: {len(blob)} bytes != {HEADER_BYTES}")
    digest = hashlib.sha256(blob).hexdigest()
    if digest != sha:
        raise SystemExit(f"{path.name}: sha256 {digest} != pinned {sha}")
    fields = struct.unpack_from(HEADER_FMT, blob, 0)
    (ident, magic, vbf_offset, got_dp_offset, flags, dp_sz, dp_rotation, got_nx, got_ny, scan_rotation,
     sx, sy, beam_energy, sdp, camera_length, acq_serial) = fields
    if (ident, magic, vbf_offset, got_dp_offset, dp_sz, got_nx, got_ny) != (b"IMGBLO", 258, HEADER_BYTES, dp_offset, DP_SZ, nx, ny):
        raise SystemExit(f"{path.name}: header tuple {(ident, magic, vbf_offset, got_dp_offset, dp_sz, got_nx, got_ny)} disagrees with pins")
    if vbf_offset + nx * ny != dp_offset or dp_offset + nx * ny * FRAME != size:
        raise SystemExit(f"{path.name}: VBF/DP offsets do not tile the pinned file size")
    note_start = struct.calcsize(HEADER_FMT) + 22 * 8
    note = blob[note_start:].strip(b"\x00").decode("latin-1")
    acquired = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=acq_serial)
    return {
        "nx": nx,
        "ny": ny,
        "dp_offset": dp_offset,
        "dp_size_px": dp_sz,
        "astar_flags": f"0x{flags:05x}",
        "dp_rotation": dp_rotation,
        "scan_rotation_deg": scan_rotation / 100.0,
        "step_x_nm": sx,
        "step_y_nm": sy,
        "beam_energy_v": beam_energy,
        "sdp_raw": sdp,
        "camera_length_mm": camera_length / 10.0,
        "acquired_local": acquired.isoformat(timespec="seconds"),
        "operator_note": note,
    }


def load_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if fields and not fields[0].startswith("#"):
                pins[fields[0]] = fields[-1]
    return pins


def percentile(hist: list[int], q: float) -> int:
    total = sum(hist)
    target = q * (total - 1)
    seen = 0
    for value, count in enumerate(hist):
        seen += count
        if seen > target:
            return value
    return 255


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    args = parser.parse_args(argv)
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
    pattern_hashes: dict[bytes, str] = {}
    duplicates: list[list[str]] = []
    scans_stats: dict[str, dict] = {}
    rows_info: list[dict] = []
    total_samples = 0
    min_distinct = 256
    index_tmp = index_path.with_suffix(".jsonl.part")
    with index_tmp.open("w", encoding="utf-8") as index:
        for scan, record_id, key, size, header_sha, dp_offset, nx, ny in SCANS:
            header = parse_header(downloads / f"{scan}.header.bin", size, header_sha, dp_offset, nx, ny)
            scan_hist = [0] * 256
            scan_samples = 0
            scan_distinct: list[int] = []
            scan_sat: list[int] = []
            selected = list(range(0, ny, ROW_STRIDE))
            for row in selected:
                row_file = downloads / f"{scan}.row{row:03d}.bin"
                data = row_file.read_bytes()
                if len(data) != nx * FRAME:
                    raise SystemExit(f"{row_file.name}: {len(data)} bytes != {nx} * {FRAME}")
                row_sha = hashlib.sha256(data).hexdigest()
                if pins and pins.get(row_file.name) != row_sha:
                    raise SystemExit(f"{row_file.name}: sha256 {row_sha} != pinned {pins.get(row_file.name)}")
                rows_info.append({"file": row_file.name, "bytes": len(data), "sha256": row_sha})
                for col in range(nx):
                    base = col * FRAME
                    marker, frame_index = struct.unpack_from("<HI", data, base)
                    expected_index = row * nx + col
                    if marker != 0x55AA or frame_index != expected_index:
                        raise SystemExit(f"{scan} r{row} c{col}: frame prefix 0x{marker:04x}/{frame_index} != 0x55aa/{expected_index}")
                    pattern = data[base + 6:base + FRAME]
                    counts = [pattern.count(bytes((v,))) for v in range(256)]
                    present = [v for v in range(256) if counts[v]]
                    distinct = len(present)
                    if distinct < 2:
                        raise SystemExit(f"{scan} r{row} c{col}: constant pattern")
                    if distinct < MIN_DISTINCT:
                        raise SystemExit(f"{scan} r{row} c{col}: only {distinct} distinct values")
                    min_distinct = min(min_distinct, distinct)
                    for v in present:
                        scan_hist[v] += counts[v]
                    digest = hashlib.sha256(pattern).digest()
                    rel = f"samples/{DATASET_ID}/{SERIES_ID}/{scan}_r{row:03d}_c{col:03d}.bin"
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
                        "sample_size_bytes": NPIX,
                        "value_count": NPIX,
                        "shape": [DP_SZ, DP_SZ],
                        "axes": ["detector_row", "detector_col"],
                        "scan": scan,
                        "scan_row": row,
                        "scan_col": col,
                        "frame_index": frame_index,
                        "source_record": record_id,
                        "source_file": key,
                        "source_byte_offset": dp_offset + expected_index * FRAME + 6,
                        "min": present[0],
                        "max": present[-1],
                        "distinct_values": distinct,
                        "count_255": counts[255],
                        "count_0": counts[0],
                        "pixel_sum": sum(v * counts[v] for v in present),
                        "sha256": digest.hex(),
                    }
                    index.write(json.dumps(record, separators=(",", ":")) + "\n")
                    scan_samples += 1
                    scan_distinct.append(distinct)
                    scan_sat.append(counts[255])
                    total_samples += 1
            for v in range(256):
                histogram[v] += scan_hist[v]
            scan_values = sum(scan_hist)
            scan_distinct.sort()
            scan_sat.sort()
            scans_stats[scan] = dict(
                header,
                source_record=record_id,
                source_file=key,
                file_size=size,
                selected_rows=selected,
                samples=scan_samples,
                value_mean=round(sum(v * c for v, c in enumerate(scan_hist)) / scan_values, 4),
                value_p01=percentile(scan_hist, 0.01),
                value_median=percentile(scan_hist, 0.5),
                value_p99=percentile(scan_hist, 0.99),
                value_p999=percentile(scan_hist, 0.999),
                saturated_255_fraction=round(scan_hist[255] / scan_values, 8),
                zero_fraction=round(scan_hist[0] / scan_values, 8),
                distinct_per_pattern_min=scan_distinct[0],
                distinct_per_pattern_median=scan_distinct[len(scan_distinct) // 2],
                count_255_per_pattern_median=scan_sat[len(scan_sat) // 2],
                count_255_per_pattern_max=scan_sat[-1],
                histogram=scan_hist,
            )
    if len(duplicates) > MAX_DUPLICATE_FRACTION * total_samples:
        raise SystemExit(f"{len(duplicates)} byte-identical duplicate patterns exceed {MAX_DUPLICATE_FRACTION:.1%}")
    os.replace(index_tmp, index_path)

    total_values = sum(histogram)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "row_stride": ROW_STRIDE,
        "samples": total_samples,
        "total_bytes": total_samples * NPIX,
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
        "scans": scans_stats,
        "rows": rows_info,
        "histogram": histogram,
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(
        f"build ok samples={total_samples} bytes={total_samples * NPIX} "
        f"range={stats['value_min']}..{stats['value_max']} mean={stats['mean_value']} "
        f"sat255={stats['saturated_255_fraction']} zero={stats['zero_fraction']} "
        f"duplicates={len(duplicates)} aggregate_sha256={stats['aggregate_sha256']}"
    )
    for scan, info in scans_stats.items():
        print(
            f"scan {scan}: grid={info['nx']}x{info['ny']} rows={len(info['selected_rows'])} samples={info['samples']} "
            f"CL={info['camera_length_mm']}mm step={info['step_x_nm']}nm mean={info['value_mean']} "
            f"median={info['value_median']} p99={info['value_p99']} sat255={info['saturated_255_fraction']} "
            f"zero={info['zero_fraction']} distinct_med={info['distinct_per_pattern_median']} note={info['operator_note']!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
