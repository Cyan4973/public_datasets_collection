#!/usr/bin/env python3
"""Convert the downloaded big-endian FLUX rows into little-endian float64 samples + index.

One sample per x1dints product: the whole FLUX column of the EXTRACT1D table, row-major
(integration, wavelength bin), shape [NAXIS2, nbins], NaN edge bins preserved.
"""
import argparse
import array
import csv
import hashlib
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x1dints  # noqa: E402

DATASET_ID = "mast_jwst_nirspec_g395h_tso_x1dints_flux_f64"
SERIES_ID = "nirspec_g395h_nrs1_x1dints_flux_jy_f64"


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    args = ap.parse_args()
    data = args.data_dir
    dl = os.path.join(data, "downloads", DATASET_ID)
    sources = read_tsv(os.path.join(args.recipe_dir, "sources.tsv"))
    plan = {r["filename"]: r for r in read_tsv(os.path.join(dl, "download_plan.tsv"))}
    out_dir = os.path.join(data, "samples", DATASET_ID, SERIES_ID)
    idx_dir = os.path.join(data, "index", DATASET_ID)
    filt_dir = os.path.join(data, "filtered", DATASET_ID)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(idx_dir, exist_ok=True)
    os.makedirs(filt_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, name))

    rows = []
    seen_digests = set()
    for src in sources:
        fn = src["filename"]
        stem = fn[:-len(".fits")]
        if fn not in plan:
            raise SystemExit(f"{fn}: missing from download_plan.tsv")
        with open(os.path.join(dl, "layouts", stem + ".json")) as fh:
            layout = json.load(fh)
        problems = x1dints.regime_problems(layout, fn, layout["remote"]["size"])
        if problems:
            raise SystemExit(f"{fn}: regime violated: {problems}")
        _, nbins, unit, _ = x1dints.flux_layout(layout)
        nrows = layout["extract1d"]["naxis2"]
        with open(os.path.join(dl, "flux", stem + ".flux.be"), "rb") as fh:
            raw = fh.read()
        if hashlib.sha256(raw).hexdigest() != plan[fn]["sha256"]:
            raise SystemExit(f"{fn}: FLUX payload sha256 differs from download_plan.tsv")
        if len(raw) != nrows * nbins * 8:
            raise SystemExit(f"{fn}: payload size {len(raw)} != {nrows} x {nbins} x 8")
        vals = array.array("d")
        vals.frombytes(raw)
        if sys.byteorder == "little":
            vals.byteswap()  # FITS is big-endian; samples are little-endian
        nan_count = 0
        fmin = math.inf
        fmax = -math.inf
        for r in range(nrows):
            row = vals[r * nbins:(r + 1) * nbins]
            finite = [v for v in row if math.isfinite(v)]
            if len(finite) != sum(1 for v in row if v == v):
                raise SystemExit(f"{fn}: row {r} has infinite values")
            if len(finite) < x1dints.MIN_ROW_FINITE_FRACTION * nbins or len(set(finite)) < 2:
                raise SystemExit(f"{fn}: row {r} violates the missing-value policy ({len(finite)}/{nbins} finite)")
            nan_count += nbins - len(finite)
            fmin = min(fmin, min(finite))
            fmax = max(fmax, max(finite))
        out = vals.tobytes() if sys.byteorder == "little" else _to_le(vals)
        digest = hashlib.sha256(out).hexdigest()
        if digest in seen_digests:
            raise SystemExit(f"{fn}: duplicate sample")
        seen_digests.add(digest)
        rel = os.path.join("samples", DATASET_ID, SERIES_ID, stem + ".f64")
        with open(os.path.join(data, rel), "wb") as fh:
            fh.write(out)
        p = layout["primary"]
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "float", "bit_width": 64, "endianness": "little",
            "element_size_bytes": 8, "sample_size_bytes": len(out), "value_count": nrows * nbins,
            "sample_shape": [nrows, nbins], "sample_axes": ["integration", "wavelength_bin"],
            "source_filename": fn, "program": p["PROGRAM"], "observation": p["OBSERVTN"],
            "visit": p["VISIT"], "target": src["target"], "date_obs": p["DATE-OBS"],
            "nints_exposure": p["NINTS"], "intstart": p["INTSTART"], "intend": p["INTEND"],
            "subarray": p["SUBARRAY"], "readpatt": p["READPATT"], "ngroups": p["NGROUPS"],
            "flux_unit": unit, "cal_ver": p["CAL_VER"], "crds_ctx": p["CRDS_CTX"],
            "sdp_ver": p["SDP_VER"], "etag": layout["remote"]["etag"],
            "product_status": layout["remote"]["status"], "nan_count": nan_count,
            "finite_min": fmin, "finite_max": fmax, "source_flux_sha256": plan[fn]["sha256"],
            "sample_sha256": digest,
        })
        print(f"sample {stem}: rows={nrows} nbins={nbins} nan={nan_count} min={fmin:.6g} max={fmax:.6g} cal_ver={p['CAL_VER']}")

    with open(os.path.join(idx_dir, "samples.jsonl.tmp"), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(os.path.join(idx_dir, "samples.jsonl.tmp"), os.path.join(idx_dir, "samples.jsonl"))
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    total_vals = sum(r["value_count"] for r in rows)
    nans = sum(r["nan_count"] for r in rows)
    stats = {
        "samples": len(rows), "total_size_bytes": total_bytes, "total_values": total_vals,
        "nan_values": nans, "nan_fraction": nans / total_vals,
        "programs": len({r["program"] for r in rows}), "targets": len({r["target"] for r in rows}),
        "cal_ver": sorted({r["cal_ver"] for r in rows}),
        "reprocessed_since_discovery": sum(1 for r in rows if r["product_status"] == "reprocessed"),
        "median_value_count": sorted(r["value_count"] for r in rows)[len(rows) // 2],
    }
    with open(os.path.join(filt_dir, "ingest_stats.json"), "w") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print("build summary " + json.dumps(stats, sort_keys=True))


def _to_le(vals):
    import struct
    return struct.pack(f"<{len(vals)}d", *vals)


if __name__ == "__main__":
    main()
