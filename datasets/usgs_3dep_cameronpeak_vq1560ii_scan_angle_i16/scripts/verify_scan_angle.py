#!/usr/bin/env python3
"""Independent verification for usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16.

* manifest series (exactly one primary series, int16 little) totals
  sample_count / total_size_bytes equal the realized output; the index has
  exactly one row per pinned tile with the required fields, int / 16 / little
  / element size 2, value_count == pinned point count, sample_size_bytes ==
  file size == 2 * value_count; no stray files in the series directory;
* each tile is decoded again from the local download with
  tools/laz/laszip.decode_points (whole-file path, not the chunk iterator the
  build uses), and scan angles are re-extracted with struct.iter_unpack
  (not the strided-slice path of the build) and re-packed with struct; they
  must equal the sample file byte for byte;
* decode integrity: the per-return histogram of the re-decoded records must
  equal the header's 15 extended points-by-return counts and the pinned ones;
* same missing-value policy as the build: every point record is emitted and
  every value lies within the LAS 1.4 limit -30,000..30,000;
* per-sample sha256 / min / max / distinct count / top-value share equal the
  index;
* degeneracy: every sample needs at least MIN_DISTINCT distinct values, no
  value above MAX_TOP_SHARE, a per-tile span max-min of at least MIN_TILE_SPAN
  (one tile may see only one side of the swath); the family must span at least
  -FAMILY_MIN_SPAN..+FAMILY_MIN_SPAN (about +-18 degrees).
"""
import argparse
import collections
import hashlib
import json
import multiprocessing
import os
import struct
import sys
import tomllib

DATASET_ID = "usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16"
SERIES_ID = "cpk_2021_scan_angle_i16"
REQUIRED = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
            "element_size_bytes", "sample_size_bytes", "value_count"]
MIN_DISTINCT = 100
MAX_TOP_SHARE = 0.5
SPEC_LIMIT = 30000
FAMILY_MIN_SPAN = 3000
MIN_TILE_SPAN = 2000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAZ_DIR = None


def _init(laz_dir):
    global LAZ_DIR
    LAZ_DIR = laz_dir


def check_tile(job):
    sys.path.insert(0, LAZ_DIR)
    import laszip

    laz_path, sample_path, pinned_count, pinned_pbr = job
    hdr, recs = laszip.decode_points(laz_path)
    rlen = hdr["point_record_length"]
    if hdr["point_format"] != 6 or rlen != 30:
        return f"{laz_path}: unexpected point layout"
    n = hdr["point_count"]
    if n != pinned_count or len(recs) < n * rlen:
        return f"{laz_path}: header/decoded count {n}/{len(recs) // rlen} vs pinned {pinned_count}"
    view = memoryview(recs)[: n * rlen]
    angles = [t[0] for t in struct.iter_unpack("<18xh10x", view)]
    rn = collections.Counter(t[0] & 0x0F for t in struct.iter_unpack("<14xB15x", view))
    del view, recs
    by_return = [rn.get(r, 0) for r in range(1, 16)]
    if rn.get(0) or by_return != list(hdr["points_by_return_64"]) or by_return != pinned_pbr:
        return f"{laz_path}: re-decoded per-return histogram {by_return} != header {hdr['points_by_return_64']}"
    packed = struct.pack(f"<{n}h", *angles)
    with open(sample_path, "rb") as fh:
        stored = fh.read()
    if stored != packed:
        return f"{sample_path}: bytes differ from re-decoded scan angles"
    hist = collections.Counter(angles)
    return {
        "n": n,
        "sha256": hashlib.sha256(packed).hexdigest(),
        "min": min(hist),
        "max": max(hist),
        "distinct": len(hist),
        "top_share": round(hist.most_common(1)[0][1] / n, 6),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--laz-dir", required=True)
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    sys.path.insert(0, SCRIPT_DIR)
    import cpk_tiles

    root = a.data_root
    errors = []
    with open(a.manifest, "rb") as fh:
        man = tomllib.load(fh)
    primaries = [s for s in man["series"] if s.get("role") == "primary"]
    if len(primaries) != 1 or primaries[0]["id"] != SERIES_ID:
        raise SystemExit("manifest must declare exactly one primary series " + SERIES_ID)
    ser = primaries[0]
    if (ser["numeric_kind"], ser["bit_width"], ser["endianness"]) != ("int", 16, "little"):
        errors.append("manifest series type is not int16 little-endian")
    tiles = cpk_tiles.load_sources(cpk_tiles.Path(a.sources))
    idx_path = os.path.join(root, "index", DATASET_ID, "samples.jsonl")
    with open(idx_path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if len(rows) != len(tiles):
        errors.append(f"index rows {len(rows)} != pinned tiles {len(tiles)}")
    by_tile = {r.get("source_tile"): r for r in rows}
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    expected_files = set()
    jobs = []
    for t in tiles:
        tile = t["tile_id"]
        r = by_tile.get(tile)
        if r is None:
            errors.append(f"no index row for {tile}")
            continue
        for k in REQUIRED:
            if k not in r:
                errors.append(f"{tile}: index row lacks {k}")
        if (r.get("dataset_id"), r.get("series_id"), r.get("numeric_kind"), r.get("bit_width"),
                r.get("endianness"), r.get("element_size_bytes")) != (DATASET_ID, SERIES_ID, "int", 16, "little", 2):
            errors.append(f"{tile}: index type fields wrong")
        sp = os.path.join(root, r["sample_path"])
        if os.path.dirname(os.path.abspath(sp)) != os.path.abspath(sdir):
            errors.append(f"{tile}: sample path outside the series directory")
        expected_files.add(os.path.basename(sp))
        size = os.path.getsize(sp) if os.path.isfile(sp) else -1
        if r.get("value_count") != t["pc_count"] or size != r.get("sample_size_bytes") or size != 2 * t["pc_count"]:
            errors.append(f"{tile}: sample size {size} vs index {r.get('sample_size_bytes')}/{r.get('value_count')} "
                          f"vs pinned {t['pc_count']} points")
        laz = os.path.join(root, "downloads", DATASET_ID, "laz", t["file_name"])
        jobs.append((tile, (laz, sp, t["pc_count"], t["points_by_return"])))
    stray = set(os.listdir(sdir)) - expected_files if os.path.isdir(sdir) else set()
    if stray:
        errors.append(f"stray files in series directory: {sorted(stray)[:5]}")
    if errors:
        raise SystemExit("verify failed before decode:\n" + "\n".join(errors))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2), 24)
    total_values = 0
    fam_min, fam_max = SPEC_LIMIT + 1, -SPEC_LIMIT - 1
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        for (tile, _job), res in zip(jobs, pool.imap(check_tile, [j for _, j in jobs])):
            if isinstance(res, str):
                errors.append(res)
                continue
            r = by_tile[tile]
            n = res["n"]
            total_values += n
            fam_min, fam_max = min(fam_min, res["min"]), max(fam_max, res["max"])
            if res["sha256"] != r.get("sha256"):
                errors.append(f"{tile}: sha256 differs from index")
            if res["min"] != r.get("min_value") or res["max"] != r.get("max_value"):
                errors.append(f"{tile}: min/max differ from index")
            if res["distinct"] != r.get("distinct_values") or res["top_share"] != r.get("top_value_share"):
                errors.append(f"{tile}: distinct/top share differ from index")
            if res["min"] < -SPEC_LIMIT or res["max"] > SPEC_LIMIT:
                errors.append(f"{tile}: scan angle outside the LAS 1.4 limit")
            if res["distinct"] < MIN_DISTINCT:
                errors.append(f"{tile}: only {res['distinct']} distinct values")
            if res["top_share"] > MAX_TOP_SHARE:
                errors.append(f"{tile}: one value covers {res['top_share']:.2%} of points")
            if res["max"] - res["min"] < MIN_TILE_SPAN:
                errors.append(f"{tile}: scan-angle span {res['min']}..{res['max']} below {MIN_TILE_SPAN}")
            print(f"ok {tile} points={n} range={res['min']}..{res['max']} distinct={res['distinct']} "
                  f"top_share={res['top_share']}", flush=True)
    if fam_min > -FAMILY_MIN_SPAN or fam_max < FAMILY_MIN_SPAN:
        errors.append(f"family scan-angle range {fam_min}..{fam_max} narrower than +-{FAMILY_MIN_SPAN}")
    total_bytes = 2 * total_values
    if len(rows) != ser.get("sample_count"):
        errors.append(f"manifest sample_count {ser.get('sample_count')} != realized {len(rows)}")
    if total_bytes != ser.get("total_size_bytes"):
        errors.append(f"manifest total_size_bytes {ser.get('total_size_bytes')} != realized {total_bytes}")
    if total_values < 10000 or sorted(r["value_count"] for r in rows)[len(rows) // 2] < 1000:
        errors.append("below acceptance floor")
    if errors:
        raise SystemExit("verify failed:\n" + "\n".join(errors))
    print(f"verified samples={len(rows)} total_values={total_values} total_bytes={total_bytes} "
          f"family_range={fam_min}..{fam_max}")


if __name__ == "__main__":
    main()
