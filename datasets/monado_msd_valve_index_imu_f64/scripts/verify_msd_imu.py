#!/usr/bin/env python3
"""Independent verification of the Monado SLAM Valve Index IMU samples.

Re-derives every sample from the local CSV members with a separate parser
(binary line splitting, no csv module), compares the stored bytes exactly,
recomputes index metadata (sizes, counts, min/max from the stored doubles,
SHA-256, timestamp step counts), checks manifest totals against the realized
output, and rejects constant, non-finite or physically implausible series.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import struct
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "monado_msd_valve_index_imu_f64"
HEADER = (
    b"#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],"
    b"a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]"
)
GYRO = "msd_valve_index_gyro_w_rs_s_f64"
ACCEL = "msd_valve_index_accel_a_rs_s_f64"
STAMP = "msd_valve_index_imu_timestamp_ns_i64"
INDEX_KEYS = (
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
)
EXPECTED_SEQUENCES = 30
# Valve Index sequences whose published data.csv carries the Basalt correction
# more than once; they must not appear anywhere in this family's output.
EXCLUDED = {
    "MIC01_camcalib1", "MIC02_camcalib2", "MIC03_camcalib3", "MIC04_imucalib1", "MIC05_imucalib2",
    "MIC06_imucalib3", "MIC07_camcalib4", "MIC08_camcalib5", "MIC09_imucalib4", "MIC10_imucalib5",
    "MIC11_camcalib6", "MIC12_imucalib6", "MIC13_camcalib7", "MIC14_camcalib8", "MIC15_imucalib7",
    "MIC16_imucalib8", "MIO01_hand_puncher_1", "MIO02_hand_puncher_2", "MIO03_hand_shooter_easy",
}
# One application of the Basalt accel correction (scale factor 1 - 0.028198018)
# on the device accel count lattice; 2x/3x applications give 0.0022610797 /
# 0.0021973218.
SINGLE_STEP = 0.0023266877217
# Half the magnitude of one published gyro-x bias (0.0171 rad/s).
REST_OFFSET_LIMIT = 0.0085
STANDARD_GRAVITY = 9.80665


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def reparse(path: Path, label: str) -> tuple[bytes, bytes, bytes, int, int]:
    gyro = bytearray()
    accel = bytearray()
    stamps = bytearray()
    pack3 = struct.Struct("<3d").pack
    pack_q = struct.Struct("<q").pack
    rows = 0
    crc = 0
    with path.open("rb") as handle:
        first = handle.readline()
        crc = zlib.crc32(first, crc)
        if first.rstrip(b"\r\n") != HEADER:
            fail(f"{label}: header mismatch")
        for line in handle:
            crc = zlib.crc32(line, crc)
            if not line.endswith(b"\n"):
                fail(f"{label}: final line lacks a newline terminator")
            parts = line.rstrip(b"\r\n").split(b",")
            if len(parts) != 7:
                fail(f"{label}: row {rows + 2} has {len(parts)} fields")
            if not parts[0].isdigit():
                fail(f"{label}: row {rows + 2} timestamp {parts[0]!r}")
            try:
                values = [float(p) for p in parts[1:]]
            except ValueError:
                fail(f"{label}: row {rows + 2} has a malformed value")
            if not all(math.isfinite(v) for v in values):
                fail(f"{label}: row {rows + 2} has a non-finite value")
            stamps += pack_q(int(parts[0]))
            gyro += pack3(*values[:3])
            accel += pack3(*values[3:])
            rows += 1
    return bytes(gyro), bytes(accel), bytes(stamps), rows, crc & 0xFFFFFFFF


def lattice_step_check(label: str, accel_payload: bytes, rows: int, index_step: object) -> float:
    """Independent accel-x lattice check on the stored accelerometer bytes."""
    xs = sorted(struct.unpack_from("<d", accel_payload, 24 * i)[0] for i in range(rows))
    uniq = [xs[0]]
    for v in xs[1:]:
        if v != uniq[-1]:
            uniq.append(v)
    if len(uniq) < 3:
        fail(f"{label}: too few distinct accel-x values")
    gaps = [uniq[i + 1] - uniq[i] for i in range(len(uniq) - 1)]
    floor_gap = min(gaps)
    single = sorted(g for g in gaps if g < 1.5 * floor_gap)
    mid = len(single) // 2
    step = single[mid] if len(single) % 2 else (single[mid - 1] + single[mid]) / 2
    if abs(step - SINGLE_STEP) > 1e-9:
        fail(f"{label}: accel-x lattice step {step!r} is not the single-correction step {SINGLE_STEP}")
    if index_step != step:
        fail(f"{label}: index accel_x_lattice_step {index_step!r} != recomputed {step!r}")
    return step


def gyro_rest_offset_x(label: str, gyro_payload: bytes, rows: int) -> float:
    """Second, independent single-correction guard on the gyroscope.

    Median w_RS_S_x over the 5% lowest-norm rows (near rest). Each extra Basalt
    pass subtracts the published calib_gyro_bias again (bias x = -0.0171 rad/s),
    so over-corrected sequences sit at ~+0.017 (2 passes) or ~+0.035 (3 passes)
    rad/s, whereas single-pass sequences stay within a few mrad/s of zero.
    """
    values = struct.unpack(f"<{rows * 3}d", gyro_payload)
    order = sorted(range(rows), key=lambda i: values[3 * i] ** 2 + values[3 * i + 1] ** 2 + values[3 * i + 2] ** 2)
    calm = order[: max(50, rows // 20)]
    offset = statistics.median(values[3 * i] for i in calm)
    if abs(offset) >= REST_OFFSET_LIMIT:
        fail(f"{label}: gyro-x rest offset {offset:+.4f} rad/s suggests the bias correction was not applied exactly once")
    return offset


def check_vector_sample(label: str, payload: bytes, row: dict, rows: int) -> dict:
    count = len(payload) // 8
    if count != rows * 3 or len(payload) % 24:
        fail(f"{label}: stored value count {count} != rows*3 {rows * 3}")
    values = struct.unpack(f"<{count}d", payload)
    if not all(math.isfinite(v) for v in values):
        fail(f"{label}: non-finite stored value")
    columns = [values[c::3] for c in range(3)]
    mins = [min(c) for c in columns]
    maxs = [max(c) for c in columns]
    if any(lo == hi for lo, hi in zip(mins, maxs)):
        fail(f"{label}: constant component")
    if len(set(values[: min(count, 30000)])) < 100:
        fail(f"{label}: degenerate (fewer than 100 distinct values in the first 10,000 rows)")
    if row.get("min") != min(mins) or row.get("max") != max(maxs):
        fail(f"{label}: index min/max differ from stored doubles")
    if row.get("component_min") != mins or row.get("component_max") != maxs:
        fail(f"{label}: index component ranges differ from stored doubles")
    step = max(1, rows // 20000)
    norms = [math.sqrt(columns[0][i] ** 2 + columns[1][i] ** 2 + columns[2][i] ** 2) for i in range(0, rows, step)]
    return {"median_norm": statistics.median(norms), "max_abs": max(max(abs(v) for v in c) for c in columns)}


def verify(data_root: Path, recipe_dir: Path) -> None:
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    with (recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as handle:
        sources = {r["sequence"]: r for r in csv.DictReader(handle, delimiter="\t")}
    if len(sources) != EXPECTED_SEQUENCES:
        fail(f"sources.tsv lists {len(sources)} sequences")
    if set(sources) & EXCLUDED:
        fail(f"sources.tsv lists excluded sequences {sorted(set(sources) & EXCLUDED)}")
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    if not index_path.is_file():
        fail(f"missing {index_path}")
    rows_by_key: dict[tuple[str, str], dict] = {}
    for number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            fail(f"index line {number} missing {missing}")
        if row["dataset_id"] != DATASET_ID or row["endianness"] != "little" or row["bit_width"] != 64:
            fail(f"index line {number}: wrong dataset/endianness/width")
        if row["element_size_bytes"] != 8 or row["sample_size_bytes"] != row["value_count"] * 8:
            fail(f"index line {number}: size fields inconsistent")
        expected_kind = "int" if row["series_id"] == STAMP else "float"
        if row["numeric_kind"] != expected_kind:
            fail(f"index line {number}: numeric_kind {row['numeric_kind']}")
        expected_path = f"samples/{DATASET_ID}/{row['series_id']}/{row['sequence']}.bin"
        if row["sample_path"] != expected_path:
            fail(f"index line {number}: unexpected sample_path {row['sample_path']}")
        if row["sequence"] in EXCLUDED:
            fail(f"index line {number}: excluded sequence {row['sequence']}")
        key = (row["series_id"], row["sequence"])
        if key in rows_by_key:
            fail(f"duplicate index row {key}")
        rows_by_key[key] = row
    expected_keys = {(s, q) for s in (GYRO, ACCEL, STAMP) for q in sources}
    if set(rows_by_key) != expected_keys:
        fail(f"index rows do not cover every sequence x series: {sorted(set(rows_by_key) ^ expected_keys)[:5]}")
    for series in (GYRO, ACCEL, STAMP):
        directory = data_root / "samples" / DATASET_ID / series
        on_disk = {p.name for p in directory.iterdir()}
        stray_excluded = sorted(n for n in on_disk if n.split(".")[0] in EXCLUDED)
        if stray_excluded:
            fail(f"{series}: excluded sequences present in sample directory: {stray_excluded[:5]}")
        if on_disk != {f"{q}.bin" for q in sources}:
            fail(f"{series}: stray or missing sample files: {sorted(on_disk ^ {f'{q}.bin' for q in sources})[:5]}")

    totals = {s: [0, 0] for s in (GYRO, ACCEL, STAMP)}
    primary_counts: list[int] = []
    for seq in sorted(sources):
        source = sources[seq]
        csv_path = data_root / "downloads" / DATASET_ID / f"{seq}.imu0_data.csv"
        if not csv_path.is_file() or csv_path.stat().st_size != int(source["uncompressed_size"]):
            fail(f"{seq}: local member missing or wrong size")
        gyro, accel, stamps, rows, crc = reparse(csv_path, seq)
        if f"{crc:08x}" != source["crc32"]:
            fail(f"{seq}: CRC-32 of the local member differs from the pinned central-directory CRC")
        stamp_values = struct.unpack(f"<{rows}q", stamps)
        deltas = [b - a for a, b in zip(stamp_values, stamp_values[1:])]
        duplicates = sum(1 for d in deltas if d == 0)
        backward = sum(1 for d in deltas if d < 0)
        if duplicates + backward > 0.001 * rows:
            fail(f"{seq}: {duplicates} duplicate / {backward} backward timestamp steps")
        for series, derived in ((GYRO, gyro), (ACCEL, accel), (STAMP, stamps)):
            row = rows_by_key[(series, seq)]
            path = data_root / row["sample_path"]
            stored = path.read_bytes()
            if stored != derived:
                fail(f"{seq}/{series}: stored sample differs from the independent re-derivation")
            if len(stored) != row["sample_size_bytes"]:
                fail(f"{seq}/{series}: file size differs from index")
            if hashlib.sha256(stored).hexdigest() != row.get("sha256"):
                fail(f"{seq}/{series}: SHA-256 differs from index")
            if row.get("rows") != rows:
                fail(f"{seq}/{series}: index rows {row.get('rows')} != {rows}")
            if (row.get("duplicate_timestamp_steps"), row.get("backward_timestamp_steps")) != (duplicates, backward):
                fail(f"{seq}/{series}: timestamp step counts differ from index")
            totals[series][0] += 1
            totals[series][1] += len(stored)
        if rows_by_key[(STAMP, seq)].get("min") != min(stamp_values) or rows_by_key[(STAMP, seq)].get("max") != max(stamp_values):
            fail(f"{seq}: timestamp min/max differ")
        g = check_vector_sample(f"{seq}/gyro", gyro, rows_by_key[(GYRO, seq)], rows)
        a = check_vector_sample(f"{seq}/accel", accel, rows_by_key[(ACCEL, seq)], rows)
        step = lattice_step_check(seq, accel, rows, rows_by_key[(ACCEL, seq)].get("accel_x_lattice_step"))
        for series in (GYRO, STAMP):
            if rows_by_key[(series, seq)].get("accel_x_lattice_step") != step:
                fail(f"{seq}/{series}: index accel_x_lattice_step disagrees")
        rest_x = gyro_rest_offset_x(seq, gyro, rows)
        # Unit/column sanity: specific force norm sits near 1 g, angular rate is
        # small most of the time and bounded by the sensor range.
        if not (0.85 * STANDARD_GRAVITY <= a["median_norm"] <= 1.15 * STANDARD_GRAVITY):
            fail(f"{seq}: median accelerometer norm {a['median_norm']:.3f} m/s^2 is not near 1 g")
        if g["median_norm"] > 5.0 or g["max_abs"] > 40.0:
            fail(f"{seq}: implausible gyroscope magnitudes {g}")
        median_step = statistics.median(d for d in deltas if d > 0)
        if not (900_000 <= median_step <= 1_100_000):
            fail(f"{seq}: median timestamp step {median_step} ns is not ~1 ms")
        primary_counts += [rows * 3, rows * 3]
        print(
            f"ok seq={seq} rows={rows} median|a|={a['median_norm']:.3f} median|w|={g['median_norm']:.4f} "
            f"max|w|={g['max_abs']:.2f} dup_steps={duplicates} back_steps={backward} accel_x_step={step:.13f} gyro_rest_x={rest_x:+.4f}",
            flush=True,
        )

    declared = {s["id"]: s for s in manifest.get("series", [])}
    for series, (count, size) in totals.items():
        entry = declared.get(series)
        if entry is None:
            fail(f"manifest lacks series {series}")
        if entry.get("sample_count") != count or entry.get("total_size_bytes") != size:
            fail(
                f"manifest {series}: sample_count/total_size_bytes {entry.get('sample_count')}/{entry.get('total_size_bytes')} "
                f"!= realized {count}/{size}"
            )
        if entry.get("role") != ("auxiliary" if series == STAMP else "primary"):
            fail(f"manifest {series}: wrong role")
    total_values = sum(primary_counts)
    median = statistics.median(primary_counts)
    if total_values < 10_000 or median < 1_000:
        fail(f"primary floor not met: values={total_values} median={median}")
    primary_bytes = totals[GYRO][1] + totals[ACCEL][1]
    if primary_bytes > 1_000_000_000:
        fail(f"primary bytes {primary_bytes} exceed 1 GB")
    print(
        f"verify_ok sequences={len(sources)} primary_samples={len(primary_counts)} primary_values={total_values} "
        f"primary_bytes={primary_bytes} median_sample_values={median} auxiliary_bytes={totals[STAMP][1]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--recipe-dir", required=True, type=Path)
    args = parser.parse_args()
    verify(args.data_root.resolve(), args.recipe_dir)


if __name__ == "__main__":
    main()
