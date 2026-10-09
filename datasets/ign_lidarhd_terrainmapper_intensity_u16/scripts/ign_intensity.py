#!/usr/bin/env python3
"""IGN LiDAR HD block 21LHD2GO (Leica TerrainMapper:90560) COPC tiles -> uint16 intensity.

Subcommands
  check   validate one downloaded tile (LAS/COPC header + VLR/EVLR layout and
          the pinned header point count); used by download.sh
  build   decode every pinned tile with the repository decoder
          tools/laz/laszip.py (unmodified) and write the per-point Intensity
          field (POINT14 record offset 12, '<H') of every point, in stored
          COPC octree-node order, as one raw little-endian uint16 sample per tile
  verify  independently re-decode every tile, re-extract Intensity with a
          different code path (struct.iter_unpack instead of byte slicing),
          and byte-compare against the samples, the index and the manifest

Pure standard library. No values are dropped, imputed or rescaled.
"""
import argparse
import array
import collections
import hashlib
import json
import math
import multiprocessing
import os
import struct
import sys
import time

DATASET_ID = "ign_lidarhd_terrainmapper_intensity_u16"
SERIES_ID = "ign_lidarhd_intensity_u16"
RLEN = 30
INTENSITY_OFFSET = 12
EXPECTED_TILES = 12
# Regime guard: the TerrainMapper stream spans roughly 300..8000 with thousands
# of distinct levels. A RIEGL/other-sensor tile (e.g. intensities 1..16) or a
# degenerate tile fails these floors instead of slipping into the family.
MIN_DISTINCT = 1000
MIN_MAX_VALUE = 1000
MAX_TOP_VALUE_SHARE = 0.05
XYZ = struct.Struct("<iii18x")
LAZ_DIR = None


def _laszip():
    if LAZ_DIR not in sys.path:
        sys.path.insert(0, LAZ_DIR)
    import laszip  # repository decoder, tools/laz/laszip.py
    return laszip


def _init(laz_dir):
    global LAZ_DIR
    LAZ_DIR = laz_dir


def read_sources(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    head = lines[0].split("\t")
    rows = [dict(zip(head, line.split("\t"))) for line in lines[1:] if line.strip()]
    for r in rows:
        r["size_bytes"] = int(r["size_bytes"])
        r["header_point_count"] = int(r["header_point_count"])
        r["sample_name"] = r["tile"].replace(".copc.laz", ".bin")
    if len(rows) != EXPECTED_TILES or len({r["tile"] for r in rows}) != EXPECTED_TILES:
        raise SystemExit(f"sources.tsv must list {EXPECTED_TILES} distinct tiles, got {len(rows)}")
    return rows


def validate_header(path, pinned_count):
    """Structural checks shared by check/build/verify. Returns the header dict."""
    laszip = _laszip()
    hdr = laszip.read_header(path)  # parses VLRs and the EVLR directory too
    problems = []
    if hdr["version"] != "1.4":
        problems.append(f"LAS version {hdr['version']}")
    if hdr["point_format"] != 6 or not hdr["compressed"] or hdr["point_record_length"] != RLEN:
        problems.append(f"layout pf{hdr['point_format']} compressed={hdr['compressed']} rl{hdr['point_record_length']}")
    if hdr["point_count"] != pinned_count:
        problems.append(f"point count {hdr['point_count']} != pinned {pinned_count}")
    lz = hdr["laszip"] or {}
    items = [(i["name"], i["size"], i["version"]) for i in lz.get("items", [])]
    if lz.get("compressor") != 3 or items != [("POINT14", 30, 3)]:
        problems.append(f"LASzip compressor {lz.get('compressor')} items {items}")
    vlr_ids = [(v["user_id"], v["record_id"]) for v in hdr["vlrs"]]
    if ("copc", 1) not in vlr_ids:
        problems.append(f"no COPC info VLR (VLRs {vlr_ids})")
    proj = [v for v in hdr["vlrs"] if v["user_id"] == "LASF_Projection" and v["record_id"] == 2112]
    if not proj or b"Lambert-93" not in proj[0]["data"]:
        problems.append("missing Lambert-93 WKT VLR")
    evlr_ids = [(v["user_id"], v["record_id"]) for v in hdr["evlrs"]]
    if ("copc", 1000) not in evlr_ids:
        problems.append(f"no COPC hierarchy EVLR (EVLRs {evlr_ids})")
    if hdr["evlrs"] and hdr["end_of_evlrs"] > hdr["file_size"]:
        problems.append(f"EVLRs end at {hdr['end_of_evlrs']} past the file end {hdr['file_size']} (truncated)")
    if problems:
        raise RuntimeError(f"{os.path.basename(path)}: " + "; ".join(problems))
    return hdr


def cmd_check(a):
    global LAZ_DIR
    LAZ_DIR = a.laz_dir
    hdr = validate_header(a.path, a.points)
    print(f"header ok {os.path.basename(a.path)} points={hdr['point_count']} "
          f"vlrs={[v['user_id'] for v in hdr['vlrs']]} evlrs={[(v['user_id'], v['record_id']) for v in hdr['evlrs']]}")


def entropy(hist, n):
    return -sum(c / n * math.log2(c / n) for c in hist.values())


def intensity_stats(values):
    hist = collections.Counter(values)
    n = len(values)
    top_value, top_count = hist.most_common(1)[0]
    q = sorted(values)
    return {
        "points": n,
        "min_value": q[0],
        "max_value": q[-1],
        "distinct_values": len(hist),
        "zero_count": hist.get(0, 0),
        "zero_fraction": hist.get(0, 0) / n,
        "saturated_65535_count": hist.get(65535, 0),
        "saturated_65535_fraction": hist.get(65535, 0) / n,
        "at_max_value_count": hist[q[-1]],
        "top_value": top_value,
        "top_value_share": top_count / n,
        "order0_entropy_bits": round(entropy(hist, n), 4),
        "percentiles": {str(p): q[min(n - 1, int(n * p))] for p in (0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999)},
    }


def regime_problems(st):
    out = []
    if st["distinct_values"] < MIN_DISTINCT:
        out.append(f"only {st['distinct_values']} distinct intensities")
    if st["max_value"] < MIN_MAX_VALUE:
        out.append(f"max intensity {st['max_value']} < {MIN_MAX_VALUE} (other-sensor regime?)")
    if st["top_value_share"] > MAX_TOP_VALUE_SHARE:
        out.append(f"value {st['top_value']} covers {st['top_value_share']:.3f} of points")
    return out


def build_tile(job):
    laszip = _laszip()
    path, out_path, pinned = job
    t0 = time.time()
    hdr = validate_header(path, pinned)
    buf = bytearray()
    returns = collections.Counter()
    sources = collections.Counter()
    classes = collections.Counter()
    lo = [2**31] * 3
    hi = [-2**31] * 3
    chunks = 0
    for _i, n, recs in laszip.iter_chunks(path, header=hdr):
        chunks += 1
        if len(recs) != n * RLEN:
            raise RuntimeError(f"{path}: chunk {_i} has {len(recs)} bytes for {n} points")
        part = bytearray(2 * n)
        part[0::2] = recs[INTENSITY_OFFSET::RLEN]
        part[1::2] = recs[INTENSITY_OFFSET + 1::RLEN]
        buf += part
        returns.update(b & 0x0F for b in recs[14::RLEN])
        classes.update(recs[16::RLEN])
        sources.update(struct.unpack_from("<H", recs, o)[0] for o in range(20, len(recs), RLEN * 64))
        xs, ys, zs = zip(*XYZ.iter_unpack(recs))
        lo = [min(lo[0], min(xs)), min(lo[1], min(ys)), min(lo[2], min(zs))]
        hi = [max(hi[0], max(xs)), max(hi[1], max(ys)), max(hi[2], max(zs))]
    count = len(buf) // 2
    if count != hdr["point_count"]:
        raise RuntimeError(f"{path}: decoded {count} points, header says {hdr['point_count']}")
    by_return = [returns.get(r, 0) for r in range(1, 16)]
    if by_return != list(hdr["points_by_return_64"]):
        raise RuntimeError(f"{path}: decoded points-by-return {by_return} != header {hdr['points_by_return_64']}")
    for axis in range(3):
        s, o = hdr["scale"][axis], hdr["offset"][axis]
        dmin, dmax = lo[axis] * s + o, hi[axis] * s + o
        if dmin < hdr["min"][axis] - s / 2 or dmax > hdr["max"][axis] + s / 2:
            raise RuntimeError(f"{path}: axis {axis} decoded {dmin}..{dmax} outside header "
                               f"{hdr['min'][axis]}..{hdr['max'][axis]}")
    values = array.array("H")
    values.frombytes(bytes(buf))
    if sys.byteorder != "little":
        values.byteswap()
    st = intensity_stats(values)
    probs = regime_problems(st)
    if probs:
        raise RuntimeError(f"{path}: " + "; ".join(probs))
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf)
    os.replace(tmp, out_path)
    st.update({
        "chunks": chunks,
        "sha256": hashlib.sha256(buf).hexdigest(),
        "points_by_return": by_return,
        "class_histogram": {str(k): classes[k] for k in sorted(classes)},
        "point_source_ids_sampled_every_64th": {str(k): sources[k] for k in sorted(sources)},
        "header_bounds_min": list(hdr["min"]),
        "header_bounds_max": list(hdr["max"]),
        "seconds": round(time.time() - t0, 1),
    })
    return st


def paths(root):
    return {
        "dl": os.path.join(root, "downloads", DATASET_ID, "tiles"),
        "samples": os.path.join(root, "samples", DATASET_ID, SERIES_ID),
        "index": os.path.join(root, "index", DATASET_ID, "samples.jsonl"),
        "stats": os.path.join(root, "filtered", DATASET_ID, "ingest_stats.json"),
    }


def cmd_build(a):
    rows = read_sources(a.sources)
    p = paths(a.data_root)
    for d in (p["samples"], os.path.dirname(p["index"]), os.path.dirname(p["stats"])):
        os.makedirs(d, exist_ok=True)
    expected = {r["sample_name"] for r in rows}
    for name in os.listdir(p["samples"]):
        if name not in expected:
            os.remove(os.path.join(p["samples"], name))  # stale output of an earlier build
    jobs = []
    for r in rows:
        src = os.path.join(p["dl"], r["tile"])
        if not os.path.isfile(src) or os.path.getsize(src) != r["size_bytes"]:
            raise SystemExit(f"missing or incomplete download: {src} (run download.sh)")
        jobs.append((src, os.path.join(p["samples"], r["sample_name"]), r["header_point_count"]))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2))
    print(f"decoding tiles={len(jobs)} jobs={n_jobs}", flush=True)
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        results = []
        for r, st in zip(rows, pool.imap(build_tile, jobs)):
            print(f"tile {r['tile']} points={st['points']} chunks={st['chunks']} range={st['min_value']}..{st['max_value']} "
                  f"distinct={st['distinct_values']} zero={st['zero_count']} sat65535={st['saturated_65535_count']} "
                  f"H0={st['order0_entropy_bits']} {st['seconds']}s", flush=True)
            results.append(st)
    lines = []
    fam = collections.Counter()
    total_zero = total_sat = total_pts = 0
    for r, st in zip(rows, results):
        rel = os.path.relpath(os.path.join(p["samples"], r["sample_name"]), a.data_root)
        lines.append(json.dumps({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": 2 * st["points"],
            "value_count": st["points"],
            "source_tile": r["tile"],
            "source_url": r["url"],
            "tile_nw_km": r["coordonnees_nw"],
            "acquisition_dates": [r["date_debut_acquisition"], r["date_fin_acquisition"]],
            "point_order": "COPC stored order (octree-node chunks)",
            "min_value": st["min_value"],
            "max_value": st["max_value"],
            "distinct_values": st["distinct_values"],
            "sha256": st["sha256"],
        }, sort_keys=True))
        total_zero += st["zero_count"]
        total_sat += st["saturated_65535_count"]
        total_pts += st["points"]
    tmp = p["index"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, p["index"])
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "tiles": len(rows),
        "points": total_pts,
        "bytes": 2 * total_pts,
        "zero_fraction": total_zero / total_pts,
        "saturated_65535_fraction": total_sat / total_pts,
        "min_value": min(st["min_value"] for st in results),
        "max_value": max(st["max_value"] for st in results),
        "per_tile": {r["tile"]: st for r, st in zip(rows, results)},
    }
    with open(p["stats"], "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"samples={len(rows)} points={total_pts} bytes={2 * total_pts} "
          f"zero_fraction={summary['zero_fraction']:.6g} sat65535_fraction={summary['saturated_65535_fraction']:.6g} "
          f"range={summary['min_value']}..{summary['max_value']}")


def verify_tile(job):
    laszip = _laszip()
    path, sample_path, pinned = job
    hdr = validate_header(path, pinned)
    unpack = struct.Struct(f"<{INTENSITY_OFFSET}xH{RLEN - INTENSITY_OFFSET - 2}x").iter_unpack
    ref = array.array("H")
    for _i, _n, recs in laszip.iter_chunks(path, header=hdr):
        ref.extend(v for (v,) in unpack(recs))
    got = array.array("H")
    with open(sample_path, "rb") as fh:
        got.frombytes(fh.read())
    if sys.byteorder != "little":
        got.byteswap()
    if len(ref) != hdr["point_count"]:
        raise RuntimeError(f"{path}: re-decoded {len(ref)} points != header {hdr['point_count']}")
    if got != ref:
        diff = next(i for i in range(min(len(got), len(ref))) if got[i] != ref[i]) if len(got) == len(ref) else -1
        raise RuntimeError(f"{sample_path}: differs from re-decoded intensities (len {len(got)} vs {len(ref)}, first diff {diff})")
    st = intensity_stats(ref)
    probs = regime_problems(st)
    if probs:
        raise RuntimeError(f"{sample_path}: " + "; ".join(probs))
    raw = ref.tobytes() if sys.byteorder == "little" else None
    st["sha256"] = hashlib.sha256(raw if raw is not None else open(sample_path, "rb").read()).hexdigest()
    return st


def cmd_verify(a):
    import tomllib
    rows = read_sources(a.sources)
    p = paths(a.data_root)
    manifest = tomllib.loads(open(a.manifest, encoding="utf-8").read())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary":
        raise SystemExit("manifest must declare exactly one primary series " + SERIES_ID)
    index = [json.loads(line) for line in open(p["index"], encoding="utf-8") if line.strip()]
    if len(index) != len(rows):
        raise SystemExit(f"index has {len(index)} rows, sources list {len(rows)}")
    on_disk = sorted(os.listdir(p["samples"]))
    if on_disk != sorted(r["sample_name"] for r in rows):
        raise SystemExit(f"unexpected sample files: {on_disk}")
    by_path = {row["sample_path"]: row for row in index}
    jobs = []
    for r in rows:
        sp = os.path.join(p["samples"], r["sample_name"])
        rel = os.path.relpath(sp, a.data_root)
        row = by_path.get(rel)
        if row is None:
            raise SystemExit(f"no index row for {rel}")
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 16,
                "endianness": "little", "element_size_bytes": 2, "value_count": r["header_point_count"],
                "sample_size_bytes": 2 * r["header_point_count"]}
        for k, v in want.items():
            if row.get(k) != v:
                raise SystemExit(f"{rel}: index {k}={row.get(k)!r}, expected {v!r}")
        if os.path.getsize(sp) != 2 * r["header_point_count"]:
            raise SystemExit(f"{rel}: size {os.path.getsize(sp)} != 2 x {r['header_point_count']}")
        jobs.append((os.path.join(p["dl"], r["tile"]), sp, r["header_point_count"]))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2))
    print(f"re-decoding tiles={len(jobs)} jobs={n_jobs}", flush=True)
    total = 0
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        for r, st in zip(rows, pool.imap(verify_tile, jobs)):
            row = by_path[os.path.relpath(os.path.join(p["samples"], r["sample_name"]), a.data_root)]
            for k in ("min_value", "max_value", "distinct_values", "sha256"):
                if row.get(k) != st[k]:
                    raise SystemExit(f"{r['tile']}: index {k}={row.get(k)!r} but re-derived {st[k]!r}")
            total += st["points"]
            print(f"ok {r['tile']} points={st['points']} range={st['min_value']}..{st['max_value']} "
                  f"distinct={st['distinct_values']} zero_frac={st['zero_fraction']:.3g} "
                  f"sat65535_frac={st['saturated_65535_fraction']:.3g} top_share={st['top_value_share']:.4f}", flush=True)
    s = series[0]
    if s["sample_count"] != len(rows) or s["total_size_bytes"] != 2 * total:
        raise SystemExit(f"manifest sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} "
                         f"!= realized {len(rows)}/{2 * total}")
    counts = sorted(r["header_point_count"] for r in rows)
    median = (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2
    if total < 10_000 or median < 1_000 or 2 * total > 1_000_000_000:
        raise SystemExit(f"floor/cap violated: values={total} median={median} bytes={2 * total}")
    print(f"verify ok samples={len(rows)} values={total} bytes={2 * total} median_values={median}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--laz-dir", required=True)
    c.add_argument("path")
    c.add_argument("points", type=int)
    for name in ("build", "verify"):
        b = sub.add_parser(name)
        b.add_argument("--sources", required=True)
        b.add_argument("--data-root", required=True)
        b.add_argument("--laz-dir", required=True)
        b.add_argument("--jobs", type=int, default=0)
        if name == "verify":
            b.add_argument("--manifest", required=True)
    a = ap.parse_args()
    if a.cmd == "check":
        cmd_check(a)
    else:
        _init(a.laz_dir)
        cmd_build(a) if a.cmd == "build" else cmd_verify(a)


if __name__ == "__main__":
    main()
