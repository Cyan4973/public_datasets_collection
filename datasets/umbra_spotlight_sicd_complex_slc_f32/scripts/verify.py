#!/usr/bin/env python3
"""Independent verification for umbra_spotlight_sicd_complex_slc_f32.

Deliberately does not import sicd.py or recipe.py.  It re-parses each local
NITF with its own fixed-offset reader and regex SICD XML extraction,
re-derives every sample with slice-assignment byte reversal (instead of
array.byteswap), byte-compares, recomputes all index statistics from the
stored sample, and checks manifest totals, the missing-value policy and
non-degeneracy.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import re
import sys

DATASET_ID = "umbra_spotlight_sicd_complex_slc_f32"
SERIES_ID = "umbra_sicd_complex_iq_f32"
MAX_ZERO_INSIDE_VALID = 0.05
MIN_NONZERO_PIXEL_FRACTION = 0.30
MIN_DISTINCT = 100_000
ROWS_PER_STEP = 128


def fail(msg):
    print(f"VERIFY FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def read_sources(path):
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n").split("\t") for ln in f if ln.strip()]
    hdr = lines[0]
    return [dict(zip(hdr, ln)) for ln in lines[1:]]


def manifest_series_totals(path):
    txt = open(path, encoding="utf-8").read()
    blocks = txt.split("[[series]]")[1:]
    for blk in blocks:
        if re.search(r'^id\s*=\s*"' + SERIES_ID + '"', blk, re.M):
            sc = int(re.search(r"^sample_count\s*=\s*(\d+)", blk, re.M).group(1))
            tb = int(re.search(r"^total_size_bytes\s*=\s*(\d+)", blk, re.M).group(1))
            return sc, tb
    fail("series not found in manifest")


def nitf_layout(f):
    """Return (image_data_offset, image_len, des_data_offset, des_len, nrows, ncols)."""
    f.seek(0)
    h = f.read(4096)
    if h[:9] != b"NITF02.10":
        fail("not NITF 2.1")
    fl = int(h[342:354])
    hl = int(h[354:360])
    p = 360
    numi = int(h[p:p + 3]); p += 3
    if numi != 1:
        fail(f"NUMI {numi}")
    lish = int(h[p:p + 6]); li = int(h[p + 6:p + 16]); p += 16
    nums = int(h[p:p + 3]); p += 3
    gl = 0
    for _ in range(nums):
        gl += int(h[p:p + 4]) + int(h[p + 4:p + 10]); p += 10
    p += 3  # NUMX
    numt = int(h[p:p + 3]); p += 3
    tl = 0
    for _ in range(numt):
        tl += int(h[p:p + 4]) + int(h[p + 4:p + 9]); p += 9
    numdes = int(h[p:p + 3]); p += 3
    if numdes != 1:
        fail(f"NUMDES {numdes}")
    ldsh = int(h[p:p + 4]); ld = int(h[p + 4:p + 13]); p += 13
    img_off = hl + lish
    des_off = hl + lish + li + gl + tl + ldsh
    # Image subheader: NROWS/NCOLS sit right after ISORCE at fixed offset 333.
    ish = h[hl:hl + lish]
    if ish[:2] != b"IM":
        fail("image subheader tag")
    nrows = int(ish[333:341]); ncols = int(ish[341:349])
    pvtype = ish[349:352].decode().strip()
    abpp = int(ish[368:370])
    return fl, img_off, li, des_off, ld, nrows, ncols, pvtype, abpp


def xml_fields(xml):
    def one(tag):
        m = re.search(r"<" + tag + r">([^<]*)</" + tag + ">", xml)
        if not m:
            fail(f"XML lacks {tag}")
        return m.group(1).strip()
    imgdata = re.search(r"<ImageData>(.*?)</ImageData>", xml, re.S).group(1)
    nr = int(re.search(r"<NumRows>(\d+)</NumRows>", imgdata).group(1))
    nc = int(re.search(r"<NumCols>(\d+)</NumCols>", imgdata).group(1))
    vd = re.search(r"<ValidData[^>]*>(.*?)</ValidData>", imgdata, re.S).group(1)
    verts = [(int(i), int(r), int(c)) for i, r, c in re.findall(
        r'<Vertex index="(\d+)"><Row>(-?\d+)</Row><Col>(-?\d+)</Col></Vertex>', vd)]
    verts.sort()
    return {
        "pixel_type": one("PixelType"), "rows": nr, "cols": nc,
        "mode": one("ModeType"), "algo": one("ImageFormAlgo"),
        "app": one("Application"), "collector": one("CollectorName"),
        "poly": [(r, c) for _, r, c in verts],
    }


def inside_bounds(poly, r):
    """Independent row/polygon intersection: integer column bounds of the
    polygon at row r (ceil of left crossing, floor of right crossing)."""
    xs = []
    n = len(poly)
    for k in range(n):
        (ra, ca), (rb, cb) = poly[k], poly[(k + 1) % n]
        if ra == rb:
            if r == ra:
                xs += [ca, cb]
        elif min(ra, rb) <= r <= max(ra, rb):
            xs.append(ca + (cb - ca) * (r - ra) / (rb - ra))
    if not xs:
        return None
    return math.ceil(min(xs)), math.floor(max(xs))


def residue_check(sample, nrows, ncols, poly):
    """Independent recomputation of the index residue/coherence diagnostic:
    every 7th row (from 0) x every 5th col (from 0); P = I^2 + Q^2;
    M = upper median of interior P; residue = P < 1e-3 * M; coherence over
    the central 256 x 256 block, rows r..r+1."""
    import struct
    fmt = "<%df" % (2 * ncols)

    def get(g, r):
        g.seek(8 * ncols * r)
        return struct.unpack(fmt, g.read(8 * ncols))

    inner, outer = [], []
    with open(sample, "rb") as g:
        for r in range(0, nrows, 7):
            v = get(g, r)
            b = inside_bounds(poly, r)
            lo, hi = (max(0, b[0]), min(ncols - 1, b[1])) if b else (ncols, -1)
            for c in range(0, ncols, 5):
                pw = v[2 * c] * v[2 * c] + v[2 * c + 1] * v[2 * c + 1]
                if lo <= c <= hi:
                    inner.append(pw)
                else:
                    outer.append(pw)
        inner_sorted = sorted(inner)
        m = inner_sorted[len(inner_sorted) // 2]
        thr = 1e-3 * m
        below_in = sum(1 for x in inner if x < thr)
        below_out = sum(1 for x in outer if x < thr)
        below = sorted([x for x in inner if x < thr] + [x for x in outer if x < thr])
        acc = 0j
        den = 0.0
        r0, c0 = nrows // 2 - 128, ncols // 2 - 128
        for r in range(r0, r0 + 256):
            v1, v2 = get(g, r), get(g, r + 1)
            for c in range(c0, c0 + 256):
                z1 = complex(v1[2 * c], v1[2 * c + 1])
                z2 = complex(v2[2 * c], v2[2 * c + 1])
                acc += z1 * z2.conjugate()
                den += 0.5 * (abs(z1) ** 2 + abs(z2) ** 2)
    return {
        "residue_fraction": (below_in + below_out) / (len(inner) + len(outer)),
        "residue_outside_valid_fraction": below_out / len(outer) if outer else 0.0,
        "residue_inside_valid_fraction": below_in / len(inner),
        "residue_median_db": 10 * math.log10(below[len(below) // 2] / m) if below else None,
        "row_adjacent_coherence": abs(acc) / den,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--data-root", required=True)
    a = ap.parse_args()
    if sys.byteorder != "little":
        fail("little-endian host required")
    sources = read_sources(os.path.join(a.recipe_dir, "sources.tsv"))
    m_count, m_bytes = manifest_series_totals(os.path.join(a.recipe_dir, "manifest.toml"))
    idx_path = os.path.join(a.data_root, "index", DATASET_ID, "samples.jsonl")
    index = [json.loads(ln) for ln in open(idx_path, encoding="utf-8") if ln.strip()]
    if len(index) != len(sources):
        fail(f"index rows {len(index)} != sources {len(sources)}")
    sample_dir = os.path.join(a.data_root, "samples", DATASET_ID, SERIES_ID)
    on_disk = sorted(os.listdir(sample_dir))
    if on_disk != sorted(s["core"] + ".f32" for s in sources):
        fail(f"unexpected sample files: {on_disk}")
    total = 0
    req = ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
           "element_size_bytes", "sample_size_bytes", "value_count")
    for src, row in zip(sources, index):
        for k in req:
            if k not in row:
                fail(f"index row lacks {k}")
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{src['core']}.f32"
        if row["sample_path"] != rel or row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
            fail(f"index identity mismatch for {src['core']}")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            fail("dtype fields")
        nitf = os.path.join(a.data_root, "downloads", DATASET_ID, src["core"] + "_SICD.nitf")
        sample = os.path.join(a.data_root, rel)
        with open(nitf, "rb") as f:
            fl, img_off, li, des_off, ld, nrows, ncols, pvtype, abpp = nitf_layout(f)
            if fl != os.path.getsize(nitf) or fl != int(src["size"]):
                fail(f"{src['core']}: FL/size mismatch")
            f.seek(des_off)
            x = xml_fields(f.read(ld).decode("utf-8"))
            if x["pixel_type"] != "RE32F_IM32F" or x["mode"] != "SPOTLIGHT" or x["algo"] != "PFA":
                fail(f"{src['core']}: regime {x['pixel_type']} {x['mode']} {x['algo']}")
            if not re.search(r"processor 0\.6\.\d", x["app"]):
                fail(f"{src['core']}: processor {x['app']}")
            if pvtype != "R" or abpp != 32:
                fail(f"{src['core']}: PVTYPE/ABPP {pvtype} {abpp}")
            if (x["rows"], x["cols"]) != (nrows, ncols) or li != nrows * ncols * 8:
                fail(f"{src['core']}: geometry {x['rows']}x{x['cols']} vs NITF {nrows}x{ncols}, LI {li}")
            if (nrows, ncols) != (int(src["rows"]), int(src["cols"])):
                fail(f"{src['core']}: geometry vs sources.tsv")
            ssize = os.path.getsize(sample)
            if ssize != li or row["sample_size_bytes"] != ssize or row["value_count"] != nrows * ncols * 2:
                fail(f"{src['core']}: sample size/value_count")
            if row.get("shape") != [nrows, ncols, 2]:
                fail(f"{src['core']}: shape")
            f.seek(img_off)
            sha = hashlib.sha256()
            vmin, vmax = math.inf, -math.inf
            zero_in = zero_all = n_in = 0
            distinct = set()
            r0 = 0
            with open(sample, "rb") as g:
                while r0 < nrows:
                    n = min(ROWS_PER_STEP, nrows - r0)
                    be = f.read(n * ncols * 8)
                    le = g.read(n * ncols * 8)
                    want = bytearray(len(be))
                    want[0::4] = be[3::4]
                    want[1::4] = be[2::4]
                    want[2::4] = be[1::4]
                    want[3::4] = be[0::4]
                    if want != le:
                        fail(f"{src['core']}: byte mismatch in rows {r0}..{r0 + n - 1}")
                    sha.update(le)
                    v = array.array("f")
                    v.frombytes(le)
                    s = sum(v)
                    if not math.isfinite(s):
                        fail(f"{src['core']}: non-finite values near row {r0}")
                    vmin = min(vmin, min(v)); vmax = max(vmax, max(v))
                    if len(distinct) < MIN_DISTINCT:
                        distinct.update(v)
                    for k in range(n):
                        rowb = le[k * ncols * 8:(k + 1) * ncols * 8]
                        q = array.array("Q"); q.frombytes(rowb)
                        zero_all += q.count(0)
                        b = inside_bounds(x["poly"], r0 + k)
                        if b:
                            lo, hi = max(0, b[0]), min(ncols - 1, b[1])
                            if hi >= lo:
                                zero_in += q[lo:hi + 1].count(0)
                                n_in += hi - lo + 1
                    r0 += n
        npix = nrows * ncols
        zf = zero_all / npix
        zin = zero_in / n_in if n_in else 1.0
        if not vmin < vmax:
            fail(f"{src['core']}: constant sample")
        if len(distinct) < min(MIN_DISTINCT, nrows * ncols // 5):
            fail(f"{src['core']}: only {len(distinct)} distinct values in probe rows")
        if 1 - zf < MIN_NONZERO_PIXEL_FRACTION:
            fail(f"{src['core']}: zero-dominated ({zf:.3f})")
        if zin > MAX_ZERO_INSIDE_VALID:
            fail(f"{src['core']}: {zin:.4f} zero pixels inside ValidData")
        if sha.hexdigest() != row["sha256"]:
            fail(f"{src['core']}: sha256 vs index")
        if row["min"] != vmin or row["max"] != vmax:
            fail(f"{src['core']}: min/max vs index ({row['min']},{row['max']}) != ({vmin},{vmax})")
        if abs(row["zero_pixel_fraction"] - zf) > 1e-6 or abs(row["zero_inside_valid_fraction"] - zin) > 1e-6:
            fail(f"{src['core']}: zero fractions vs index")
        rc = residue_check(sample, nrows, ncols, x["poly"])
        for k in ("residue_fraction", "residue_outside_valid_fraction", "residue_inside_valid_fraction"):
            if abs(row[k] - rc[k]) > 1e-6:
                fail(f"{src['core']}: {k} index={row[k]} recomputed={rc[k]}")
        if (row["residue_median_db"] is None) != (rc["residue_median_db"] is None) or (
                rc["residue_median_db"] is not None and abs(row["residue_median_db"] - rc["residue_median_db"]) > 0.01):
            fail(f"{src['core']}: residue_median_db index={row['residue_median_db']} recomputed={rc['residue_median_db']}")
        if abs(row["row_adjacent_coherence"] - rc["row_adjacent_coherence"]) > 1e-5:
            fail(f"{src['core']}: row_adjacent_coherence index={row['row_adjacent_coherence']} recomputed={rc['row_adjacent_coherence']}")
        if rc["residue_inside_valid_fraction"] > 0.01:
            fail(f"{src['core']}: {rc['residue_inside_valid_fraction']:.4f} of sampled interior pixels below "
                 "1e-3 x interior median power (hidden fill inside ValidData?)")
        total += ssize
        print(f"residue {src['core']} all={rc['residue_fraction']:.4f} outside={rc['residue_outside_valid_fraction']:.4f} "
              f"inside={rc['residue_inside_valid_fraction']:.5f} median_db={rc['residue_median_db']:.2f} "
              f"row_coh={rc['row_adjacent_coherence']:.3f}")
        print(f"ok {src['core']} {nrows}x{ncols} bytes={ssize} min={vmin:.6g} max={vmax:.6g} "
              f"zero_px={zf:.4f} zero_in_valid={zin:.5f} distinct_probe={len(distinct)}")
    if len(index) != m_count or total != m_bytes:
        fail(f"manifest totals sample_count={m_count} total_size_bytes={m_bytes} vs realized {len(index)} {total}")
    if total > 1_000_000_000:
        fail("primary output exceeds 1e9 bytes")
    print(f"verified samples={len(index)} total_size_bytes={total}")


if __name__ == "__main__":
    main()
