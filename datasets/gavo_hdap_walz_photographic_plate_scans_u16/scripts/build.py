#!/usr/bin/env python3
"""Build little-endian uint16 plate-scan samples from the pinned HDAP Walz lunar FITS files.

Local files only. One sample per plate: the complete primary-HDU image, row-major
(NAXIS2 rows of NAXIS1 columns, FITS order: column fastest), uint16 = int16 + BZERO(32768).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitsplate  # noqa: E402

DATASET_ID = "gavo_hdap_walz_photographic_plate_scans_u16"
SERIES_ID = "walz_lunar_plate_scan_dn_u16"
XOR_HIGH = bytes(b ^ 0x80 for b in range(256))
MIN_DISTINCT = 256
MAX_DOMINANT_FRACTION = 0.9  # lunar plates keep large clipped clear-glass areas (value 1422)
EXPECTED_SEASONS = {"S1", "S2", "S3", "S4", "S5", "S6"}


def be_int16_bzero_to_le_uint16(raw: bytes) -> bytes:
    """Big-endian int16 + 32768 -> little-endian uint16 (XOR of the sign bit, byte swap)."""
    if len(raw) % 2:
        raise ValueError("odd byte count")
    out = bytearray(len(raw))
    out[0::2] = raw[1::2]
    out[1::2] = raw[0::2].translate(XOR_HIGH)
    return bytes(out)


def value_stats(sample: bytes) -> dict:
    counts = collections.Counter(memoryview(sample).cast("H")) if sys.byteorder == "little" else None
    if counts is None:
        raise SystemExit("big-endian hosts are not supported")
    n = len(sample) // 2
    dominant_value, dominant_count = counts.most_common(1)[0]
    total = sum(value * count for value, count in counts.items())
    return {
        "min": min(counts),
        "max": max(counts),
        "distinct_values": len(counts),
        "dominant_value": dominant_value,
        "dominant_fraction": round(dominant_count / n, 6),
        "count_0": counts.get(0, 0),
        "count_65535": counts.get(65535, 0),
        "floor_1422_fraction": round(counts.get(1422, 0) / n, 6),
        "mean": round(total / n, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True, type=Path)
    ap.add_argument("--data-root", required=True, type=Path)
    args = ap.parse_args()
    root = args.data_root
    pins = fitsplate.read_sources(args.recipe / "sources.tsv")
    plan_path = root / "downloads" / DATASET_ID / "download_plan.tsv"
    plan = {row["plate_id"]: row for row in fitsplate.read_sources(plan_path)}
    if set(plan) != {p["plate_id"] for p in pins}:
        raise SystemExit("download_plan.tsv does not cover exactly the pinned plates; rerun download.sh")
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"
    for d in (out_dir, index_path.parent, stats_path.parent):
        d.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*"):
        stale.unlink()

    rows = []
    seen = {}
    for pin in pins:
        plate = pin["plate_id"]
        src = root / "downloads" / DATASET_ID / "fits" / f"{plate}.fits"
        blob = src.read_bytes()
        if len(blob) != int(pin["size_bytes"]):
            raise SystemExit(f"{plate}: size {len(blob)} != pinned {pin['size_bytes']}")
        sha = hashlib.sha256(blob).hexdigest()
        if sha != plan[plate]["sha256"]:
            raise SystemExit(f"{plate}: sha256 {sha} != download plan {plan[plate]['sha256']}")
        cards, header_bytes = fitsplate.parse_primary_header(blob)
        facts = fitsplate.check_regime(cards, header_bytes, len(blob), pin)
        if fitsplate.header_sha256(blob, header_bytes) != pin["header_sha256"]:
            raise SystemExit(f"{plate}: header sha256 differs from pin")
        start = header_bytes
        end = start + facts["data_bytes"]
        padding = blob[end:]
        padding_nonzero = sum(1 for b in padding if b)
        sample = be_int16_bzero_to_le_uint16(blob[start:end])
        del blob
        stats = value_stats(sample)
        if stats["distinct_values"] < MIN_DISTINCT:
            raise SystemExit(f"{plate}: only {stats['distinct_values']} distinct values")
        if stats["dominant_fraction"] > MAX_DOMINANT_FRACTION:
            raise SystemExit(f"{plate}: dominant value {stats['dominant_value']} covers {stats['dominant_fraction']}")
        sample_sha = hashlib.sha256(sample).hexdigest()
        if sample_sha in seen:
            raise SystemExit(f"{plate}: duplicate image of {seen[sample_sha]}")
        seen[sample_sha] = plate
        dest = out_dir / f"{plate}.u16"
        tmp = dest.with_suffix(".u16.tmp")
        tmp.write_bytes(sample)
        os.replace(tmp, dest)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(dest.relative_to(root)),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(sample),
            "value_count": len(sample) // 2,
            "shape": [facts["naxis2"], facts["naxis1"]],
            "axes": ["scan_row", "scan_column"],
            "plate_id": plate,
            "object": pin["object"],
            "fits_date_obs": facts["date_obs"],
            "start_time": pin["start_time"],
            "season": pin["season"],
            "source_url": pin["url"],
            "source_size_bytes": int(pin["size_bytes"]),
            "source_sha256": sha,
            "header_sha256": pin["header_sha256"],
            "padding_nonzero_bytes": padding_nonzero,
            "sample_sha256": sample_sha,
            **stats,
        }
        rows.append(row)
        print(
            f"{plate} {facts['naxis1']}x{facts['naxis2']} {facts['date_obs']} min={stats['min']} max={stats['max']} "
            f"distinct={stats['distinct_values']} dominant={stats['dominant_value']}@{stats['dominant_fraction']} "
            f"zeros={stats['count_0']} sat={stats['count_65535']} mean={stats['mean']} pad_nonzero={padding_nonzero}"
        )

    seasons = {r["season"] for r in rows}
    if seasons != EXPECTED_SEASONS:
        raise SystemExit(f"season coverage {sorted(seasons)} != {sorted(EXPECTED_SEASONS)}")
    tmp_index = index_path.with_suffix(".jsonl.tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(tmp_index, index_path)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "total_size_bytes": sum(r["sample_size_bytes"] for r in rows),
        "total_values": sum(r["value_count"] for r in rows),
        "source_bytes": sum(r["source_size_bytes"] for r in rows),
        "seasons": {s: sum(1 for r in rows if r["season"] == s) for s in sorted(seasons)},
        "max_dominant_fraction": max(r["dominant_fraction"] for r in rows),
        "floor_1422_fraction_overall": round(sum(r["floor_1422_fraction"] * r["value_count"] for r in rows) / sum(r["value_count"] for r in rows), 6),
        "median_value_count": sorted(r["value_count"] for r in rows)[len(rows) // 2],
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
