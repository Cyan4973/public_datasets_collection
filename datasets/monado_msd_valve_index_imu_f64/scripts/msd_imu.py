#!/usr/bin/env python3
"""Build float64 gyro/accel samples from validated Monado SLAM Valve Index IMU CSVs.

Input (local only): $DATA_ROOT/downloads/<id>/<seq>.imu0_data.csv, one per row
of sources.tsv, each byte-identical to the stored ZIP member
<seq>/mav0/imu0/data.csv (size and CRC-32 re-checked here).

Output per sequence:
  samples/<id>/msd_valve_index_gyro_w_rs_s_f64/<seq>.bin      rows x 3 float64 LE
  samples/<id>/msd_valve_index_accel_a_rs_s_f64/<seq>.bin     rows x 3 float64 LE
  samples/<id>/msd_valve_index_imu_timestamp_ns_i64/<seq>.bin rows int64 LE (auxiliary)
plus index/<id>/samples.jsonl and filtered/<id>/ingest_stats.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import struct
import sys
import zlib
from array import array
from pathlib import Path

DATASET_ID = "monado_msd_valve_index_imu_f64"
HEADER = [
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]",
    "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]",
    "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]",
    "a_RS_S_z [m s^-2]",
]
GYRO = "msd_valve_index_gyro_w_rs_s_f64"
ACCEL = "msd_valve_index_accel_a_rs_s_f64"
STAMP = "msd_valve_index_imu_timestamp_ns_i64"
EXPECTED_SEQUENCES = 30
# Realized at the pinned revision for the 30 in-scope sequences; a change means
# the source members or the parser changed.
EXPECTED_TOTAL_ROWS = 9_026_215
# Sequences whose published data.csv carries the Basalt IMU correction more
# than once (accel-x lattice step scaled by an extra 0.971802 or 0.971802^2);
# never part of this family.
EXCLUDED = frozenset(
    [f"MIC{n:02d}_{kind}" for n, kind in [
        (1, "camcalib1"), (2, "camcalib2"), (3, "camcalib3"), (4, "imucalib1"), (5, "imucalib2"),
        (6, "imucalib3"), (7, "camcalib4"), (8, "camcalib5"), (9, "imucalib4"), (10, "imucalib5"),
        (11, "camcalib6"), (12, "imucalib6"), (13, "camcalib7"), (14, "camcalib8"), (15, "imucalib7"),
        (16, "imucalib8")]]
    + ["MIO01_hand_puncher_1", "MIO02_hand_puncher_2", "MIO03_hand_shooter_easy"]
)
# Accel-x count lattice step for exactly one application of the published
# Basalt correction: the device accel count scale (~8 g / 32768) times
# (1 + calib_accel_bias[3]) = 1 - 0.028198018. Basalt's misalignment matrix is
# lower-triangular, so a_RS_S_x depends on the x count only and stays on a
# lattice. Two applications give 0.0022610797, three give 0.0021973218.
SINGLE_CORRECTION_ACCEL_X_STEP = 0.0023266877217
LATTICE_STEP_TOLERANCE = 1e-9
# Non-increasing timestamp steps are kept in source order and reported; more
# than this fraction of a sequence would indicate a structurally broken file.
MAX_NONINCREASING_FRACTION = 0.001
MIN_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000


def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_SEQUENCES or len({r["sequence"] for r in rows}) != EXPECTED_SEQUENCES:
        raise SystemExit(f"sources.tsv must list {EXPECTED_SEQUENCES} distinct sequences")
    listed_excluded = sorted({r["sequence"] for r in rows} & EXCLUDED)
    if listed_excluded:
        raise SystemExit(f"sources.tsv lists excluded multi-correction sequences: {listed_excluded}")
    return sorted(rows, key=lambda r: r["sequence"])


def crc32_file(path: Path) -> int:
    value = 0
    with path.open("rb") as handle:
        while block := handle.read(8 << 20):
            value = zlib.crc32(block, value)
    return value & 0xFFFFFFFF


def to_le(values: array) -> bytes:
    if sys.byteorder != "little":
        values = array(values.typecode, values)
        values.byteswap()
    return values.tobytes()


def parse_imu_csv(path: Path, label: str) -> dict:
    gyro = array("d")
    accel = array("d")
    stamps = array("q")
    shortest_repr = 0
    float32_exact = 0
    with path.open("rb") as raw:
        text = io.TextIOWrapper(raw, encoding="ascii", newline="")
        reader = csv.reader(text, strict=True)
        header = next(reader, None)
        if header != HEADER:
            raise SystemExit(f"{label}: unexpected header {header!r}")
        for line_number, fields in enumerate(reader, start=2):
            if len(fields) != 7:
                raise SystemExit(f"{label}:{line_number}: expected 7 fields, got {len(fields)}")
            stamp_text = fields[0]
            if not stamp_text.isdigit():
                raise SystemExit(f"{label}:{line_number}: malformed timestamp {stamp_text!r}")
            stamps.append(int(stamp_text))
            for column, text_value in enumerate(fields[1:]):
                try:
                    value = float(text_value)
                except ValueError:
                    raise SystemExit(f"{label}:{line_number}: malformed value {text_value!r}") from None
                if not math.isfinite(value):
                    raise SystemExit(f"{label}:{line_number}: non-finite value {text_value!r}")
                if repr(value) == text_value:
                    shortest_repr += 1
                if struct.unpack("<f", struct.pack("<f", value))[0] == value:
                    float32_exact += 1
                (gyro if column < 3 else accel).append(value)
    rows = len(stamps)
    if rows == 0:
        raise SystemExit(f"{label}: no data rows")
    deltas = [b - a for a, b in zip(stamps, stamps[1:])]
    duplicates = sum(1 for d in deltas if d == 0)
    backward = sum(1 for d in deltas if d < 0)
    if (duplicates + backward) > MAX_NONINCREASING_FRACTION * rows:
        raise SystemExit(f"{label}: {duplicates} duplicate and {backward} backward timestamp steps in {rows} rows")
    positive = [d for d in deltas if d > 0]
    return {
        "gyro": gyro,
        "accel": accel,
        "stamps": stamps,
        "rows": rows,
        "duplicate_timestamp_steps": duplicates,
        "backward_timestamp_steps": backward,
        "first_timestamp_ns": stamps[0],
        "last_timestamp_ns": stamps[-1],
        "duration_s": (stamps[-1] - stamps[0]) / 1e9,
        "median_step_ns": statistics.median(positive) if positive else 0,
        "shortest_repr_values": shortest_repr,
        "float32_exact_values": float32_exact,
    }


def accel_x_lattice_step(accel: array) -> float:
    """Median single-count spacing of the distinct a_RS_S_x values."""
    distinct = sorted(set(accel[0::3]))
    if len(distinct) < 3:
        raise SystemExit("too few distinct accel-x values for a lattice check")
    gaps = [b - a for a, b in zip(distinct, distinct[1:])]
    smallest = min(gaps)
    return statistics.median(g for g in gaps if g < 1.5 * smallest)


def column_ranges(values: array) -> list[tuple[float, float]]:
    return [(min(values[c::3]), max(values[c::3])) for c in range(3)]


def write_sample(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)
    return hashlib.sha256(payload).hexdigest()


def build(data_root: Path, sources_path: Path) -> None:
    sources = read_sources(sources_path)
    downloads = data_root / "downloads" / DATASET_ID
    sample_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    for series in (GYRO, ACCEL, STAMP):
        directory = sample_root / series
        if directory.is_dir():
            for stale in directory.glob("*.bin*"):
                stale.unlink()
    records: list[dict] = []
    per_sequence: list[dict] = []
    for source in sources:
        seq = source["sequence"]
        csv_path = downloads / f"{seq}.imu0_data.csv"
        if not csv_path.is_file():
            raise SystemExit(f"missing local member {csv_path}; run download.sh first")
        if csv_path.stat().st_size != int(source["uncompressed_size"]):
            raise SystemExit(f"{seq}: local member size differs from sources.tsv")
        if f"{crc32_file(csv_path):08x}" != source["crc32"]:
            raise SystemExit(f"{seq}: local member CRC-32 differs from sources.tsv")
        parsed = parse_imu_csv(csv_path, seq)
        rows = parsed["rows"]
        step = accel_x_lattice_step(parsed["accel"])
        if abs(step - SINGLE_CORRECTION_ACCEL_X_STEP) > LATTICE_STEP_TOLERANCE:
            raise SystemExit(
                f"{seq}: accel-x lattice step {step!r} != single-correction step {SINGLE_CORRECTION_ACCEL_X_STEP} "
                "(Basalt correction not applied exactly once)"
            )
        parsed["accel_x_lattice_step"] = step
        common = {
            "dataset_id": DATASET_ID,
            "endianness": "little",
            "element_size_bytes": 8,
            "bit_width": 64,
            "sequence": seq,
            "group": source["group"],
            "rows": rows,
            "source_member": source["member"],
            "source_part": source["part_path"],
            "source_crc32": source["crc32"],
            "first_timestamp_ns": parsed["first_timestamp_ns"],
            "last_timestamp_ns": parsed["last_timestamp_ns"],
            "duplicate_timestamp_steps": parsed["duplicate_timestamp_steps"],
            "backward_timestamp_steps": parsed["backward_timestamp_steps"],
            "accel_x_lattice_step": step,
        }
        for series, values, axes in (
            (GYRO, parsed["gyro"], ["w_RS_S_x", "w_RS_S_y", "w_RS_S_z"]),
            (ACCEL, parsed["accel"], ["a_RS_S_x", "a_RS_S_y", "a_RS_S_z"]),
        ):
            ranges = column_ranges(values)
            if any(lo == hi for lo, hi in ranges):
                raise SystemExit(f"{seq}/{series}: constant component column")
            payload = to_le(values)
            relative = Path("samples") / DATASET_ID / series / f"{seq}.bin"
            digest = write_sample(data_root / relative, payload)
            records.append(
                {
                    **common,
                    "series_id": series,
                    "sample_path": relative.as_posix(),
                    "numeric_kind": "float",
                    "sample_size_bytes": len(payload),
                    "value_count": len(values),
                    "shape": [rows, 3],
                    "axes": ["imu_sample", "component"],
                    "components": axes,
                    "min": min(lo for lo, _ in ranges),
                    "max": max(hi for _, hi in ranges),
                    "component_min": [lo for lo, _ in ranges],
                    "component_max": [hi for _, hi in ranges],
                    "sha256": digest,
                    "role": "primary",
                }
            )
        stamps = parsed["stamps"]
        payload = to_le(stamps)
        relative = Path("samples") / DATASET_ID / STAMP / f"{seq}.bin"
        digest = write_sample(data_root / relative, payload)
        records.append(
            {
                **common,
                "series_id": STAMP,
                "sample_path": relative.as_posix(),
                "numeric_kind": "int",
                "sample_size_bytes": len(payload),
                "value_count": len(stamps),
                "shape": [rows],
                "axes": ["imu_sample"],
                "min": min(stamps),
                "max": max(stamps),
                "sha256": digest,
                "role": "auxiliary",
            }
        )
        summary = {k: v for k, v in parsed.items() if k not in ("gyro", "accel", "stamps")}
        summary.update(sequence=seq, group=source["group"])
        per_sequence.append(summary)
        print(
            f"seq={seq} rows={rows} duration_s={parsed['duration_s']:.1f} median_step_ns={parsed['median_step_ns']} "
            f"dup_steps={parsed['duplicate_timestamp_steps']} back_steps={parsed['backward_timestamp_steps']} "
            f"shortest_repr={parsed['shortest_repr_values']}/{rows * 6} accel_x_step={step!r}",
            flush=True,
        )
    total_rows = sum(s["rows"] for s in per_sequence)
    if total_rows != EXPECTED_TOTAL_ROWS:
        raise SystemExit(f"total IMU rows {total_rows} != pinned {EXPECTED_TOTAL_ROWS}")
    primary = [r for r in records if r["role"] == "primary"]
    counts = sorted(r["value_count"] for r in primary)
    total_values = sum(counts)
    median = statistics.median(counts)
    if total_values < MIN_VALUES or median < MIN_MEDIAN_VALUES:
        raise SystemExit(f"primary floor not met: values={total_values} median={median}")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    totals = {}
    for series in (GYRO, ACCEL, STAMP):
        chosen = [r for r in records if r["series_id"] == series]
        totals[series] = {
            "samples": len(chosen),
            "values": sum(r["value_count"] for r in chosen),
            "bytes": sum(r["sample_size_bytes"] for r in chosen),
        }
    stats = {
        "dataset_id": DATASET_ID,
        "sequences": len(per_sequence),
        "rows": sum(s["rows"] for s in per_sequence),
        "primary_values": total_values,
        "primary_bytes": sum(r["sample_size_bytes"] for r in primary),
        "median_primary_sample_values": median,
        "min_primary_sample_values": counts[0],
        "max_primary_sample_values": counts[-1],
        "shortest_repr_values": sum(s["shortest_repr_values"] for s in per_sequence),
        "float32_exact_values": sum(s["float32_exact_values"] for s in per_sequence),
        "duplicate_timestamp_steps": sum(s["duplicate_timestamp_steps"] for s in per_sequence),
        "backward_timestamp_steps": sum(s["backward_timestamp_steps"] for s in per_sequence),
        "series": totals,
        "single_correction_accel_x_step": SINGLE_CORRECTION_ACCEL_X_STEP,
        "accel_x_lattice_step_range": [
            min(s["accel_x_lattice_step"] for s in per_sequence),
            max(s["accel_x_lattice_step"] for s in per_sequence),
        ],
        "excluded_sequences": sorted(EXCLUDED),
        "per_sequence": per_sequence,
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "per_sequence"}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    args = parser.parse_args()
    build(args.data_root.resolve(), args.sources)


if __name__ == "__main__":
    main()
