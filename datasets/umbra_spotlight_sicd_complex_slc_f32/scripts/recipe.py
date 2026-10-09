#!/usr/bin/env python3
"""Validate downloaded Umbra SICD NITFs and build raw float32 LE I/Q samples.

Subcommands
  validate --sources S --download-dir D        (called by download.sh)
  build    --sources S --download-dir D --data-root R --dataset-id ID
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sicd  # noqa: E402

SERIES_ID = "umbra_sicd_complex_iq_f32"
CHUNK_ROWS = 256
INT_COLS = ("ordinal", "size", "part_size", "rows", "cols", "header_length",
            "image_subheader_length", "image_data_offset", "image_data_length",
            "des_data_offset", "des_data_length")
# Policy thresholds shared with verify.py (which re-states them independently).
MAX_ZERO_INSIDE_VALID = 0.05     # exactly-zero I/Q pixels inside the ValidData polygon
MIN_NONZERO_PIXEL_FRACTION = 0.30


def load_sources(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        hdr = f.readline().rstrip("\n").split("\t")
        for line in f:
            if not line.strip():
                continue
            r = dict(zip(hdr, line.rstrip("\n").split("\t")))
            for k in INT_COLS:
                r[k] = int(r[k])
            rows.append(r)
    if not rows:
        raise SystemExit("empty sources.tsv")
    return rows


def local_name(r):
    return r["core"] + "_SICD.nitf"


def multipart_etag(path, part_size):
    digests = []
    whole = hashlib.md5()
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(part_size or (8 << 20))
            if not b:
                break
            digests.append(hashlib.md5(b).digest())
            whole.update(b)
            sha.update(b)
    if part_size == 0:
        return whole.hexdigest(), sha.hexdigest()
    return hashlib.md5(b"".join(digests)).hexdigest() + f"-{len(digests)}", sha.hexdigest()


def check_structure(path, r):
    read = sicd.file_reader(path)
    try:
        info = sicd.inspect(read)
    finally:
        read.close()
    sicd.assert_regime(info, version_prefix="0.6.")
    s = info["sicd"]
    pinned = {
        "FL": (info["FL"], r["size"]), "HL": (info["HL"], r["header_length"]),
        "image_data_offset": (info["image_data_offset"], r["image_data_offset"]),
        "image_data_length": (info["image_data_length"], r["image_data_length"]),
        "des_data_offset": (info["des_data_offset"], r["des_data_offset"]),
        "des_data_length": (info["des_data_length"], r["des_data_length"]),
        "rows": (s["num_rows"], r["rows"]), "cols": (s["num_cols"], r["cols"]),
        "collector": (s["collector"], r["collector"]),
        "processor": (sicd.processor_version(s["application"]), r["processor"]),
    }
    bad = [f"{k}: file={a!r} pinned={b!r}" for k, (a, b) in pinned.items() if a != b]
    if bad:
        raise sicd.NitfError("pinned metadata mismatch: " + "; ".join(bad))
    return info


def iter_rows_le(path, info, chunk_rows=CHUNK_ROWS):
    """Yield (row0, nrows, array('f') little-endian native values) chunks."""
    if sys.byteorder != "little":
        raise SystemExit("this recipe assumes a little-endian host")
    rows, cols = info["sicd"]["num_rows"], info["sicd"]["num_cols"]
    row_bytes = cols * 8
    with open(path, "rb") as f:
        f.seek(info["image_data_offset"])
        r0 = 0
        while r0 < rows:
            n = min(chunk_rows, rows - r0)
            raw = f.read(n * row_bytes)
            if len(raw) != n * row_bytes:
                raise sicd.NitfError("short image read")
            a = array.array("f")
            a.frombytes(raw)
            a.byteswap()  # big-endian IEEE-754 -> host (little-endian)
            yield r0, n, a
            r0 += n


def pixel_stats(path, info, sink=None):
    """Stream the image; optionally write LE bytes to sink. Returns stats."""
    s = info["sicd"]
    rows, cols = s["num_rows"], s["num_cols"]
    spans = sicd.row_spans(s["valid_polygon"], rows)
    zero_in = zero_out = n_in = 0
    vmin, vmax = math.inf, -math.inf
    total = 0.0
    sha = hashlib.sha256()
    for r0, n, a in iter_rows_le(path, info):
        b = a.tobytes()
        if sink is not None:
            sink.write(b)
        sha.update(b)
        chunk_sum = math.fsum((sum(a[i:i + 65536]) for i in range(0, len(a), 65536)))
        if not math.isfinite(chunk_sum):
            raise sicd.NitfError(f"non-finite pixel values in rows {r0}..{r0 + n - 1}")
        total += chunk_sum
        vmin = min(vmin, min(a))
        vmax = max(vmax, max(a))
        q = array.array("Q")
        q.frombytes(b)  # one uint64 per complex pixel; 0 <=> I == Q == +0.0
        for k in range(n):
            row = q[k * cols:(k + 1) * cols]
            sp = spans[r0 + k]
            zeros = row.count(0)
            if sp is None:
                zero_out += zeros
                continue
            lo = max(0, math.ceil(sp[0]))
            hi = min(cols - 1, math.floor(sp[1]))
            if hi < lo:
                zero_out += zeros
                continue
            zi = row[lo:hi + 1].count(0)
            zero_in += zi
            zero_out += zeros - zi
            n_in += hi - lo + 1
    npix = rows * cols
    n_out = npix - n_in
    st = {
        "min": vmin, "max": vmax, "mean": total / (2 * npix),
        "pixels": npix, "valid_poly_pixels": n_in,
        "zero_pixel_fraction": (zero_in + zero_out) / npix,
        "zero_inside_valid_fraction": zero_in / n_in if n_in else 1.0,
        "zero_outside_valid_fraction": zero_out / n_out if n_out else 0.0,
        "sha256": sha.hexdigest(),
    }
    if not (vmin < vmax):
        raise sicd.NitfError("constant image")
    if 1.0 - st["zero_pixel_fraction"] < MIN_NONZERO_PIXEL_FRACTION:
        raise sicd.NitfError(f"zero-dominated image: {st['zero_pixel_fraction']:.3f} zero pixels")
    if st["zero_inside_valid_fraction"] > MAX_ZERO_INSIDE_VALID:
        raise sicd.NitfError(f"{st['zero_inside_valid_fraction']:.3f} of ValidData pixels are zero")
    return st


# Residue / coherence diagnostic (documentation only; never alters samples).
DIAG_ROW_STRIDE = 7
DIAG_COL_STRIDE = 5
RESIDUE_REL = 1e-3
COH_HALF = 128


def _upper_median(xs):
    s = sorted(xs)
    return s[len(s) // 2]


def diagnostics(sample_path, rows, cols, poly):
    """Strided residue statistics and central-block row-adjacent coherence,
    computed from the stored little-endian sample."""
    spans = sicd.row_spans(poly, rows)
    p_in, p_out = [], []
    with open(sample_path, "rb") as f:
        def read_row(r):
            f.seek(r * cols * 8)
            a = array.array("f")
            a.frombytes(f.read(cols * 8))
            return a
        for r in range(0, rows, DIAG_ROW_STRIDE):
            a = read_row(r)
            sp = spans[r]
            if sp is None:
                lo, hi = 1, 0
            else:
                lo, hi = max(0, math.ceil(sp[0])), min(cols - 1, math.floor(sp[1]))
            for c in range(0, cols, DIAG_COL_STRIDE):
                i, q = a[2 * c], a[2 * c + 1]
                p = i * i + q * q
                (p_in if lo <= c <= hi else p_out).append(p)
        m = _upper_median(p_in)
        thr = RESIDUE_REL * m
        res_in = [p for p in p_in if p < thr]
        res_out = [p for p in p_out if p < thr]
        nonres_out = [p for p in p_out if p >= thr]
        res = res_in + res_out
        num_re = num_im = den = 0.0
        r0, c0 = rows // 2 - COH_HALF, cols // 2 - COH_HALF
        prev = read_row(r0)
        for r in range(r0, r0 + 2 * COH_HALF):
            nxt = read_row(r + 1)
            for c in range(c0, c0 + 2 * COH_HALF):
                a1, b1, a2, b2 = prev[2 * c], prev[2 * c + 1], nxt[2 * c], nxt[2 * c + 1]
                num_re += a1 * a2 + b1 * b2      # z1 * conj(z2)
                num_im += b1 * a2 - a1 * b2
                den += 0.5 * (a1 * a1 + b1 * b1 + a2 * a2 + b2 * b2)
            prev = nxt
    n = len(p_in) + len(p_out)
    return {
        "diag_sampled_pixels": n,
        "diag_interior_median_power": m,
        "residue_fraction": round(len(res) / n, 6),
        "residue_outside_valid_fraction": round(len(res_out) / len(p_out), 6) if p_out else 0.0,
        "residue_inside_valid_fraction": round(len(res_in) / len(p_in), 6),
        "residue_median_db": round(10 * math.log10(_upper_median(res) / m), 3) if res else None,
        "outside_nonresidue_median_db": round(10 * math.log10(_upper_median(nonres_out) / m), 3) if nonres_out else None,
        "row_adjacent_coherence": round(math.hypot(num_re, num_im) / den, 6),
        "row_adjacent_phase_deg": round(math.degrees(math.atan2(num_im, num_re)), 3),
    }


def cmd_validate(a):
    rows = load_sources(a.sources)
    ok = 0
    for r in rows:
        path = os.path.join(a.download_dir, local_name(r))
        if not os.path.isfile(path):
            raise SystemExit(f"missing {path}")
        if os.path.getsize(path) != r["size"]:
            raise SystemExit(f"size mismatch {path}")
        etag, sha = multipart_etag(path, r["part_size"])
        if etag != r["etag"]:
            raise SystemExit(f"ETag mismatch {path}: {etag} != pinned {r['etag']} "
                             "(file kept for inspection; delete it to force a re-fetch)")
        try:
            info = check_structure(path, r)
            st = pixel_stats(path, info)
        except sicd.NitfError as e:
            raise SystemExit(f"semantic rejection {path}: {e}")
        print(f"valid ordinal={r['ordinal']} core={r['core']} bytes={r['size']} etag={etag} sha256={sha} "
              f"rows={r['rows']} cols={r['cols']} proc={r['processor']} "
              f"zero_px={st['zero_pixel_fraction']:.4f} zero_in_valid={st['zero_inside_valid_fraction']:.5f}")
        ok += 1
    print(f"validated={ok}/{len(rows)}")


def cmd_build(a):
    rows = load_sources(a.sources)
    ds = a.dataset_id
    out_dir = os.path.join(a.data_root, "samples", ds, SERIES_ID)
    idx_dir = os.path.join(a.data_root, "index", ds)
    filt_dir = os.path.join(a.data_root, "filtered", ds)
    for d in (out_dir, idx_dir, filt_dir):
        os.makedirs(d, exist_ok=True)
    expected = {r["core"] + ".f32" for r in rows}
    for name in os.listdir(out_dir):
        if name not in expected:
            os.remove(os.path.join(out_dir, name))
    index_rows = []
    total_bytes = 0
    for r in rows:
        path = os.path.join(a.download_dir, local_name(r))
        if not os.path.isfile(path) or os.path.getsize(path) != r["size"]:
            raise SystemExit(f"missing or wrong-size local file {path}; run download.sh")
        info = check_structure(path, r)
        out = os.path.join(out_dir, r["core"] + ".f32")
        with open(out + ".part", "wb") as sink:
            st = pixel_stats(path, info, sink)
        os.replace(out + ".part", out)
        size = os.path.getsize(out)
        if size != r["rows"] * r["cols"] * 8:
            raise SystemExit(f"output size mismatch {out}")
        total_bytes += size
        dg = diagnostics(out, r["rows"], r["cols"], info["sicd"]["valid_polygon"])
        if dg["residue_inside_valid_fraction"] > 0.01:
            raise SystemExit(f"{r['core']}: {dg['residue_inside_valid_fraction']:.4f} of sampled interior "
                             "pixels below the residue threshold (hidden fill?)")
        stored_min = array.array("f", [st["min"]])[0]
        stored_max = array.array("f", [st["max"]])[0]
        row = {
            "dataset_id": ds, "series_id": SERIES_ID,
            "sample_path": os.path.relpath(out, a.data_root),
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "sample_size_bytes": size,
            "value_count": r["rows"] * r["cols"] * 2,
            "shape": [r["rows"], r["cols"], 2], "axes": ["sicd_row_range", "sicd_col_azimuth", "iq"],
            "min": stored_min, "max": stored_max, "mean": st["mean"],
            "zero_pixel_fraction": round(st["zero_pixel_fraction"], 6),
            "zero_inside_valid_fraction": round(st["zero_inside_valid_fraction"], 6),
            "zero_outside_valid_fraction": round(st["zero_outside_valid_fraction"], 6),
            "valid_poly_fraction": round(st["valid_poly_pixels"] / st["pixels"], 6),
            "sha256": st["sha256"],
            "collect": r["core"], "site": r["site"], "collector": r["collector"],
            "processor": r["processor"], "polarization": r["polarization"],
            "scp_lat": float(r["scp_lat"]), "scp_lon": float(r["scp_lon"]),
            "row_ss_m": float(r["row_ss_m"]), "col_ss_m": float(r["col_ss_m"]),
            "row_irw_m": float(r["row_irw_m"]), "col_irw_m": float(r["col_irw_m"]),
            "grazing_deg": float(r["grazing_deg"]),
            "source_key": r["key"], "source_etag": r["etag"], "source_bytes": r["size"],
        }
        row.update(dg)
        index_rows.append(row)
        print(f"built {row['sample_path']} bytes={size} min={stored_min:.6g} max={stored_max:.6g} "
              f"zero_px={row['zero_pixel_fraction']:.4f} zero_in_valid={row['zero_inside_valid_fraction']:.5f} "
              f"zero_out_valid={row['zero_outside_valid_fraction']:.4f} "
              f"residue={dg['residue_fraction']:.4f} residue_out={dg['residue_outside_valid_fraction']:.4f} "
              f"residue_in={dg['residue_inside_valid_fraction']:.5f} residue_db={dg['residue_median_db']} "
              f"out_nonres_db={dg['outside_nonresidue_median_db']} coh={dg['row_adjacent_coherence']:.3f} "
              f"phase={dg['row_adjacent_phase_deg']:.1f}")
    with open(os.path.join(idx_dir, "samples.jsonl.part"), "w", encoding="utf-8") as f:
        for row in index_rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(os.path.join(idx_dir, "samples.jsonl.part"), os.path.join(idx_dir, "samples.jsonl"))
    with open(os.path.join(filt_dir, "build_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"samples": len(index_rows), "total_size_bytes": total_bytes,
                   "value_count": sum(x["value_count"] for x in index_rows)}, f, indent=1)
    print(f"samples={len(index_rows)} total_size_bytes={total_bytes}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--sources", required=True)
    v.add_argument("--download-dir", required=True)
    b = sub.add_parser("build")
    b.add_argument("--sources", required=True)
    b.add_argument("--download-dir", required=True)
    b.add_argument("--data-root", required=True)
    b.add_argument("--dataset-id", default="umbra_spotlight_sicd_complex_slc_f32")
    a = ap.parse_args()
    {"validate": cmd_validate, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    main()
