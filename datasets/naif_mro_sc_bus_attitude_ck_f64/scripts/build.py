#!/usr/bin/env python3
"""Local build: pinned MRO CK type-3 segments -> little-endian float64 samples.

Uses only files under $DATA_DIR/downloads/<id>/ written by download.sh.
Per pinned segment it emits
  mro_sc_bus_quaternion_f64      primary   N x 4  [q0, q1, q2, q3]
  mro_sc_bus_angular_rate_f64    primary   N x 3  [av1, av2, av3] (rad/s)
  mro_sc_bus_sclk_epoch_ticks_f64 auxiliary N     encoded SCLK time tags
with the words copied bit-exactly from the source (big-endian -> little-endian
byte swap only; no renormalisation, re-signing or rounding).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ck_type3 as ck  # noqa: E402
from ck_download_check import load_sources, read_chain  # noqa: E402

DATASET_ID = "naif_mro_sc_bus_attitude_ck_f64"
QUAT = "mro_sc_bus_quaternion_f64"
RATE = "mro_sc_bus_angular_rate_f64"
EPOCH = "mro_sc_bus_sclk_epoch_ticks_f64"
ROLES = {QUAT: "primary", RATE: "primary", EPOCH: "auxiliary"}
MAX_PRIMARY_BYTES = 1_000_000_000
# Gyro-era safety net (the selection itself is by date, 2007-2017): the 44
# realized gyro-era segments have whole-segment median |delta av| of
# 7.9e-6..1.2e-5 rad/s on every axis; probes of star-tracker-only
# ("all-stellar", 2018+) kernels show 9e-8..1.3e-6. Reject anything below 2e-6.
MIN_RATE_STEP_MEDIAN = 2e-6


def median_abs_step(values: "ck.array.array", stride: int, axis: int) -> float:
    column = values[axis::stride]
    return statistics.median(abs(column[i + 1] - column[i]) for i in range(len(column) - 1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.data_dir).resolve()
    downloads = data_dir / "downloads" / DATASET_ID
    samples_root = data_dir / "samples" / DATASET_ID
    index_path = data_dir / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_dir / "filtered" / DATASET_ID / "segment_stats.json"

    rows = load_sources(args.sources)
    checksum_file = downloads / "checksums.sha256"
    if not checksum_file.is_file():
        raise SystemExit(f"missing {checksum_file}; run download.sh first")
    recorded = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        recorded[name.strip()] = digest

    for series in ROLES:
        target = samples_root / series
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    chains: dict[str, tuple[str, list[dict]]] = {}
    index_rows = []
    segment_stats = []
    for row in rows:
        name = row["file_name"]
        stem = name[:-3]
        ordinal = int(row["segment_ordinal"])
        if name not in chains:
            host = (downloads / "headers" / f"{stem}.host").read_text(encoding="utf-8").strip()
            header, records, summaries = read_chain(str(downloads / "headers" / f"{stem}.filerecord"), str(downloads / "headers" / f"{stem}.summaries"))
            if not records or records[-1]["next"] != 0 or records[-1]["record_number"] != header["bward"]:
                raise SystemExit(f"{name}: local summary chain incomplete")
            if len(summaries) != int(row["segment_count"]):
                raise SystemExit(f"{name}: local segment count {len(summaries)} != pinned {row['segment_count']}")
            chains[name] = (host, summaries)
        host, summaries = chains[name]
        summary = summaries[ordinal]
        ck.check_summary_identity(summary, f"{name} segment {ordinal}")
        pinned = (int(row[f"{host}_start_word"]), int(row[f"{host}_end_word"]), float(row["sclk_begin"]), float(row["sclk_end"]))
        local = (summary["start_word"], summary["end_word"], summary["sclk_begin"], summary["sclk_end"])
        if local != pinned:
            raise SystemExit(f"{name} segment {ordinal}: local descriptor {local} != pinned {pinned}")

        seg_name = f"{stem}__seg{ordinal:02d}.be"
        raw = (downloads / "segments" / seg_name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if recorded.get(f"segments/{seg_name}") != digest:
            raise SystemExit(f"{seg_name}: sha256 differs from the download record")
        pin = row["segment_sha256"].strip()
        if pin not in ("", "-") and pin != digest:
            raise SystemExit(f"{seg_name}: sha256 differs from the sources.tsv pin")
        if len(raw) != (summary["end_word"] - summary["start_word"] + 1) * 8:
            raise SystemExit(f"{seg_name}: size disagrees with the DAF descriptor")
        result = ck.split_type3(raw, ">", summary, label=f"{name} segment {ordinal}")
        if (result["n"], result["nints"]) != (int(row["n_records"]), int(row["nints"])):
            raise SystemExit(f"{seg_name}: trailer disagrees with pinned N/NINTS")

        n = result["n"]
        rates = ck.le_doubles(result["rate_le"])
        steps = [median_abs_step(rates, 3, axis) for axis in range(3)]
        if max(steps) < MIN_RATE_STEP_MEDIAN:
            raise SystemExit(f"{seg_name}: rate step medians {steps} look like star-tracker-only (all-stellar) data, not gyro-era telemetry")

        quats = ck.le_doubles(result["quaternion_le"])
        # Report-only: telemetry quaternions carry 8 fractional digits; a
        # renormalised or re-rounded copy would not.
        decimal8 = sum(1 for v in quats if float(f"{v:.8f}") == v) / len(quats)

        sample_file = f"{stem}_seg{ordinal:02d}.bin"
        payloads = {QUAT: (result["quaternion_le"], [n, 4]), RATE: (result["rate_le"], [n, 3]), EPOCH: (result["epoch_le"], [n])}
        seg_info = {
            "year": int(row["year"]),
            "file_name": name,
            "segment_ordinal": ordinal,
            "segment_count": int(row["segment_count"]),
            "host": host,
            "n_records": n,
            "nints": result["nints"],
            "sclk_begin": summary["sclk_begin"],
            "sclk_end": summary["sclk_end"],
            "first_epoch": result["first_epoch"],
            "last_epoch": result["last_epoch"],
            "segment_sha256": digest,
            "max_quaternion_norm_deviation": result["max_quaternion_norm_deviation"],
            "rate_step_median_abs": steps,
            "quaternion_8_decimal_exact_fraction": decimal8,
            "series": {},
        }
        for series, (payload, shape) in payloads.items():
            values = ck.le_doubles(payload)
            if any(not math.isfinite(v) for v in values):
                raise SystemExit(f"{seg_name}: non-finite value in {series}")
            lo, hi = min(values), max(values)
            if lo == hi:
                raise SystemExit(f"{seg_name}: constant {series} sample")
            path = samples_root / series / sample_file
            path.write_bytes(payload)
            index_rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series,
                    "role": ROLES[series],
                    "sample_path": path.relative_to(data_dir).as_posix(),
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": len(payload),
                    "value_count": len(values),
                    "shape": shape,
                    "min": lo,
                    "max": hi,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "source_file": name,
                    "segment_ordinal": ordinal,
                    "year": int(row["year"]),
                }
            )
            seg_info["series"][series] = {"value_count": len(values), "min": lo, "max": hi}
        segment_stats.append(seg_info)
        print(f"segment {name} #{ordinal}: N={n} NINTS={result['nints']} |q|-1<={result['max_quaternion_norm_deviation']:.1e} q_8dec={decimal8:.6f} rate_step_medians={['%.2e' % s for s in steps]}", flush=True)

    primary = [r for r in index_rows if r["role"] == "primary"]
    primary_values = sum(r["value_count"] for r in primary)
    primary_bytes = sum(r["sample_size_bytes"] for r in primary)
    median_values = statistics.median(r["value_count"] for r in primary)
    if primary_values < 10_000 and primary_bytes < 102_400:
        raise SystemExit("primary output below the aggregate floor")
    if median_values < 1_000:
        raise SystemExit("median primary sample below 1,000 values")
    if primary_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit("primary output exceeds 1 GB")

    index_rows.sort(key=lambda r: (r["series_id"], r["sample_path"]))
    with index_path.open("w", encoding="utf-8") as handle:
        for record in index_rows:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    per_series = {}
    for series in ROLES:
        chosen = [r for r in index_rows if r["series_id"] == series]
        per_series[series] = {
            "role": ROLES[series],
            "sample_count": len(chosen),
            "value_count": sum(r["value_count"] for r in chosen),
            "total_size_bytes": sum(r["sample_size_bytes"] for r in chosen),
        }
    stats = {
        "dataset_id": DATASET_ID,
        "segments": segment_stats,
        "series": per_series,
        "primary_sample_count": len(primary),
        "primary_value_count": primary_values,
        "primary_sample_bytes": primary_bytes,
        "median_primary_sample_values": median_values,
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for series, info in per_series.items():
        print(f"series {series} ({info['role']}): samples={info['sample_count']} values={info['value_count']} bytes={info['total_size_bytes']}")
    print(f"built primary samples={len(primary)} values={primary_values} bytes={primary_bytes} median_values={median_values}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ck.CKError as error:
        raise SystemExit(f"invalid CK payload: {error}") from error
