#!/usr/bin/env python3
"""Decode the IMAGE extension of each locally downloaded SPHEREx prefix into raw LE float32."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spherex_fits as sf  # noqa: E402

DATASET_ID = "irsa_spherex_qr3_l2_spectral_image_f32"
SERIES_ID = "spherex_qr3_d1_l2_image_mjysr_f32"
EXPECTED_FILES = 30


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    a = ap.parse_args()
    data, recipe = Path(a.data_dir), Path(a.recipe_dir)
    dl = data / "downloads" / DATASET_ID
    out_dir = data / "samples" / DATASET_ID / SERIES_ID
    idx_dir = data / "index" / DATASET_ID
    filt_dir = data / "filtered" / DATASET_ID
    for d in (out_dir, idx_dir, filt_dir):
        d.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.f32"):
        old.unlink()

    with (recipe / "sources.tsv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    with (dl / "download_plan.tsv").open(encoding="utf-8", newline="") as fh:
        plan = {r["name"]: r for r in csv.DictReader(fh, delimiter="\t")}
    if len(rows) != EXPECTED_FILES or set(plan) != {r["name"] for r in rows}:
        raise SystemExit("FATAL sources.tsv / download_plan.tsv mismatch")

    index, stats_all, seen = [], [], {}
    for r in rows:
        name = r["name"]
        src = dl / "image_prefix" / (name[:-len(".fits")] + ".primary_image.fits")
        buf = src.read_bytes()
        if len(buf) != int(r["prefix_bytes"]):
            raise SystemExit(f"FATAL {name}: size {len(buf)} != {r['prefix_bytes']}")
        if hashlib.sha256(buf).hexdigest() != plan[name]["sha256"]:
            raise SystemExit(f"FATAL {name}: SHA-256 differs from download_plan.tsv")
        info = sf.walk_prefix(buf)
        bad = sf.check_regime(info, name)
        if bad or info["data_offset"] != int(r["data_offset"]):
            raise SystemExit(f"FATAL {name}: regime {bad} offset {info['data_offset']}")
        if sf.sha256_bytes(buf[:info["data_offset"]]) != r["header_sha256"]:
            raise SystemExit(f"FATAL {name}: header SHA-256 mismatch")
        arr = sf.decode_be_f32(buf[info["data_offset"]:info["prefix_bytes"]])
        st = sf.image_stats(arr)
        probs = sf.stats_problems(st)
        if probs:
            raise SystemExit(f"FATAL {name}: {probs}")
        payload = arr.tobytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen:
            raise SystemExit(f"FATAL {name}: duplicate of {seen[digest]}")
        seen[digest] = name
        stem = name[:-len(".fits")]
        out = out_dir / f"{stem}.f32"
        out.write_bytes(payload)
        h = info["image"]
        row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(data)),
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "sample_size_bytes": len(payload), "value_count": len(arr),
            "shape": [sf.NAXIS2, sf.NAXIS1], "axes": ["detector_row_y", "detector_column_x"],
            "source_file": name, "week_group": r["week_group"], "pipeline_run": r["pipeline_run"],
            "obsid": h["OBSID"], "expidn": h["EXPIDN"], "detector": h["DETECTOR"], "bunit": h["BUNIT"],
            "date_obs": h["DATE-OBS"], "xposure_s": h["XPOSURE"], "crval1_deg": h["CRVAL1"],
            "crval2_deg": h["CRVAL2"], "nan_count": st["nan_count"], "inf_count": st["inf_count"],
            "finite_min": st["finite_min"], "finite_max": st["finite_max"],
            "finite_mean": round(st["finite_mean"], 9), "distinct_bit_patterns": st["distinct_bit_patterns"],
            "sha256": digest,
        }
        index.append(row)
        stats_all.append({k: row[k] for k in ("source_file", "nan_count", "inf_count", "finite_min",
                                               "finite_max", "finite_mean", "distinct_bit_patterns")})
        print(f"sample {stem} nan={st['nan_count']} min={st['finite_min']:.4g} max={st['finite_max']:.4g} "
              f"mean={st['finite_mean']:.4f} distinct={st['distinct_bit_patterns']}")

    tmp = idx_dir / "samples.jsonl.part"
    with tmp.open("w", encoding="utf-8") as fh:
        for row in index:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    tmp.replace(idx_dir / "samples.jsonl")
    (filt_dir / "ingest_stats.json").write_text(json.dumps(stats_all, indent=1) + "\n")
    total = sum(r["sample_size_bytes"] for r in index)
    print(f"samples={len(index)} total_bytes={total} values={sum(r['value_count'] for r in index)}")


if __name__ == "__main__":
    main()
