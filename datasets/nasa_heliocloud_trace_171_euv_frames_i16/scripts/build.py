#!/usr/bin/env python3
"""Build TRACE 171 A full-frame int16 samples from the local pinned FITS pool.

For every pinned file: re-check size, MD5 (= S3 ETag), SHA-256 (from download_plan.tsv),
the FITS header regime and pins; decode the 1024 x 1024 big-endian int16 image; measure
the data regime (tick lattice near zero, JPEG 8x8 cell-boundary ratios, degeneracy); keep
the frames that pass and write each one whole as little-endian int16. Local files only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_fits as T  # noqa: E402

DATASET_ID = "nasa_heliocloud_trace_171_euv_frames_i16"
SERIES_ID = "trace_171_full_frame_dn_i16"
MIN_KEPT = 20

METRIC_FIELDS = ["filename", "date_obs", "frm_nam", "sht_mdur", "min", "max", "distinct",
                 "dominant_value", "dominant_fraction", "zero_fraction", "lattice_eligible",
                 "lattice_holes", "lattice_worst_k", "lattice_worst_ratio", "n_spike_cells",
                 "ring_d", "n_below_low", "block_h", "block_v", "const_rows", "const_cols", "kept",
                 "reasons"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    a = ap.parse_args()
    root = a.data_dir
    fits_dir = root / "downloads" / DATASET_ID / "fits"
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_dir = root / "index" / DATASET_ID
    filt_dir = root / "filtered" / DATASET_ID
    for d in (out_dir, index_dir, filt_dir):
        d.mkdir(parents=True, exist_ok=True)

    pins = list(csv.DictReader(open(a.recipe_dir / "sources.tsv", newline=""), delimiter="\t"))
    plan_path = root / "downloads" / DATASET_ID / "download_plan.tsv"
    plan = {r["filename"]: r for r in csv.DictReader(open(plan_path, newline=""), delimiter="\t")}
    if set(plan) != {p["filename"] for p in pins}:
        raise SystemExit("download_plan.tsv does not match sources.tsv; re-run download.sh")

    metrics_rows, index_rows, kept_names = [], [], set()
    for i, pin in enumerate(pins, 1):
        name = pin["filename"]
        blob = (fits_dir / name).read_bytes()
        if len(blob) != int(pin["size_bytes"]):
            raise SystemExit(f"{name}: size mismatch")
        if hashlib.md5(blob).hexdigest() != pin["md5_etag"]:
            raise SystemExit(f"{name}: MD5 != pinned ETag")
        if hashlib.sha256(blob).hexdigest() != plan[name]["sha256"]:
            raise SystemExit(f"{name}: SHA-256 != download_plan.tsv")
        h, hist, off = T.parse_header(blob)
        problems = T.regime_problems(h, hist)
        if not T.key_matches_header(pin["key"], h):
            problems.append("key timestamp != DATE_OBS")
        if str(h.get("DATE_OBS")) != pin["date_obs"]:
            problems.append("DATE_OBS != pin")
        if problems:
            raise SystemExit(f"{name}: header regime problems {problems}")
        px = T.decode_pixels(blob, off)
        m = T.frame_metrics(px)
        reasons = T.data_problems(m, pin["frm_nam"])
        keep = not reasons
        metrics_rows.append({
            "filename": name, "date_obs": pin["date_obs"], "frm_nam": pin["frm_nam"],
            "sht_mdur": pin["sht_mdur"], **{k: m[k] for k in ("min", "max", "distinct", "dominant_value",
                                                              "const_rows", "const_cols", "lattice_eligible")},
            "dominant_fraction": f"{m['dominant_fraction']:.6f}", "zero_fraction": f"{m['zero_fraction']:.6f}",
            "lattice_holes": " ".join(map(str, m["lattice_holes"])),
            "lattice_worst_k": m["lattice_worst_k"],
            "lattice_worst_ratio": "" if m["lattice_worst_ratio"] is None else f"{m['lattice_worst_ratio']:.6f}",
            "n_spike_cells": m["n_spike_cells"],
            "ring_d": "" if m["ring_d"] is None else m["ring_d"],
            "n_below_low": m["n_below_low"],
            "block_h": f"{m['block_h']:.6f}", "block_v": f"{m['block_v']:.6f}",
            "kept": int(keep), "reasons": "; ".join(reasons)})
        if keep:
            stem = name[:-4]
            if sys.byteorder != "little":
                px.byteswap()
            payload = px.tobytes()
            rel = Path("samples") / DATASET_ID / SERIES_ID / f"{stem}.i16"
            target = root / rel
            tmp = target.with_suffix(".i16.part")
            tmp.write_bytes(payload)
            tmp.replace(target)
            kept_names.add(target.name)
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": str(rel),
                "numeric_kind": "int", "bit_width": 16, "endianness": "little",
                "element_size_bytes": 2, "sample_size_bytes": len(payload),
                "value_count": T.NPIX, "shape": [T.HEIGHT, T.WIDTH],
                "sha256": hashlib.sha256(payload).hexdigest(),
                "min": m["min"], "max": m["max"],
                "source_key": pin["key"], "source_sha256": plan[name]["sha256"],
                "date_obs": pin["date_obs"], "frm_nam": pin["frm_nam"],
                "obs_prog": pin["obs_prog"], "exposure_s": float(pin["sht_mdur"]),
                "xcen": float(pin["xcen"]), "ycen": float(pin["ycen"]),
                "block_h": round(m["block_h"], 6), "block_v": round(m["block_v"], 6),
                "lattice_tested_bins": m["lattice_eligible"],
                "lattice_worst_k": m["lattice_worst_k"],
                "lattice_worst_ratio": round(m["lattice_worst_ratio"], 6),
                "n_spike_cells": m["n_spike_cells"], "ring_d": m["ring_d"],
                "program_class": T.program_class(pin["frm_nam"]),
            })
        if i % 25 == 0:
            print(f"progress {i}/{len(pins)} kept={len(index_rows)}", flush=True)

    for stale in out_dir.glob("*"):
        if stale.name not in kept_names:
            print(f"removing stale sample {stale.name}")
            stale.unlink()
    with open(filt_dir / "pool_metrics.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, METRIC_FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(metrics_rows)
    with open(index_dir / "samples.jsonl", "w") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    reasons = {}
    for r in metrics_rows:
        for reason in filter(None, r["reasons"].split("; ")):
            key = reason.split("=")[0].split(":")[0].split(" ")[0]
            reasons[key] = reasons.get(key, 0) + 1
    first_reason = {}
    for r in metrics_rows:
        if r["reasons"]:
            first = r["reasons"].split("; ")[0]
            key = ("ringing" if first.startswith("ringing") else
                   "lattice" if first.startswith(("empty", "lattice")) else
                   "cell_edge" if first.startswith("block") else
                   "program" if first.startswith("FRM_NAM") else "degenerate")
            first_reason[key] = first_reason.get(key, 0) + 1
    stats = {
        "pool": len(pins), "kept": len(index_rows),
        "kept_bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "rejections_by_reason": reasons,
        "rejections_by_first_reason": first_reason,
        "kept_months": sorted({r["date_obs"][:7] for r in index_rows}),
        "kept_by_program": {k: sum(1 for r in index_rows if r["frm_nam"] == k)
                            for k in sorted({r["frm_nam"] for r in index_rows})},
        "kept_ring_d_range": [min((r["ring_d"] for r in index_rows if r["ring_d"] is not None), default=None),
                              max((r["ring_d"] for r in index_rows if r["ring_d"] is not None), default=None)],
        "kept_lattice_worst_ratio_min": min((r["lattice_worst_ratio"] for r in index_rows), default=None),
    }
    (filt_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))
    if len(index_rows) < MIN_KEPT:
        raise SystemExit(f"only {len(index_rows)} frames pass the data regime (< {MIN_KEPT})")


if __name__ == "__main__":
    main()
