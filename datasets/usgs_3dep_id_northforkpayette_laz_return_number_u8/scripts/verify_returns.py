#!/usr/bin/env python3
"""Verify: independently re-derive every sample and check index and manifest.

* manifest series (exactly one primary series, uint8 little) totals
  sample_count / total_size_bytes equal the realized output; the index has
  exactly one row per pinned tile with the required fields, uint8 / little /
  element size 1, value_count == sample_size_bytes == file size == pinned
  point count; no stray files in the series directory;
* each tile is decoded again from the local download with
  tools/laz/laszip.decode_points (whole-file path, not the chunk iterator the
  build uses), and return numbers are re-extracted with struct.iter_unpack
  (not the slice/translate path of the build); they must equal the sample
  file byte for byte;
* same missing-value policy as the build: every point record is emitted, no
  return number may be 0, and the per-return histogram must equal the LAS 1.4
  header's 15 extended points-by-return counts exactly;
* per-sample sha256 / min / max / histogram equal the index;
* degeneracy: every sample must hold at least 2 distinct return numbers and
  at least MIN_NON_FIRST points with return number > 1, and no value may cover
  more than MAX_TOP_SHARE of a sample; the family as a whole must have at
  least 15% non-first returns and return numbers up to at least 5.
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

DATASET_ID = "usgs_3dep_id_northforkpayette_laz_return_number_u8"
SERIES_ID = "nfp_2020_return_number_u8"
REQUIRED = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
            "element_size_bytes", "sample_size_bytes", "value_count"]
MIN_NON_FIRST = 1000
MAX_TOP_SHARE = 0.9999
FAMILY_MIN_NON_FIRST_SHARE = 0.15
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
    codes = bytes(t[0] & 0x0F for t in struct.iter_unpack("<14xB15x", memoryview(recs)[: n * rlen]))
    del recs
    with open(sample_path, "rb") as fh:
        stored = fh.read()
    if stored != codes:
        return f"{sample_path}: bytes differ from re-decoded return numbers"
    hist = collections.Counter(codes)
    if hist.get(0):
        return f"{laz_path}: {hist[0]} points with return number 0"
    by_return = [hist.get(r, 0) for r in range(1, 16)]
    if by_return != list(hdr["points_by_return_64"]) or by_return != pinned_pbr:
        return f"{laz_path}: per-return histogram {by_return} != header {hdr['points_by_return_64']}"
    return {"sha256": hashlib.sha256(codes).hexdigest(), "hist": dict(hist)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--laz-dir", required=True)
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    sys.path.insert(0, SCRIPT_DIR)
    import nfp_tiles

    root = a.data_root
    errors = []
    man = tomllib.load(open(a.manifest, "rb"))
    primaries = [s for s in man["series"] if s.get("role") == "primary"]
    if len(primaries) != 1 or primaries[0]["id"] != SERIES_ID:
        raise SystemExit("manifest must declare exactly one primary series " + SERIES_ID)
    ser = primaries[0]
    if (ser["numeric_kind"], ser["bit_width"], ser["endianness"]) != ("uint", 8, "little"):
        errors.append("manifest series type is not uint8 little-endian")
    tiles = nfp_tiles.load_sources(nfp_tiles.Path(a.sources))
    idx_path = os.path.join(root, "index", DATASET_ID, "samples.jsonl")
    rows = [json.loads(l) for l in open(idx_path, encoding="utf-8") if l.strip()]
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
                r.get("endianness"), r.get("element_size_bytes")) != (DATASET_ID, SERIES_ID, "uint", 8, "little", 1):
            errors.append(f"{tile}: index type fields wrong")
        sp = os.path.join(root, r["sample_path"])
        if os.path.dirname(os.path.abspath(sp)) != os.path.abspath(sdir):
            errors.append(f"{tile}: sample path outside the series directory")
        expected_files.add(os.path.basename(sp))
        size = os.path.getsize(sp) if os.path.isfile(sp) else -1
        if size != r.get("value_count") or size != r.get("sample_size_bytes") or size != t["pc_count"]:
            errors.append(f"{tile}: sample size {size} vs index {r.get('value_count')} vs pinned {t['pc_count']}")
        laz = os.path.join(root, "downloads", DATASET_ID, "laz", t["file_name"])
        jobs.append((tile, (laz, sp, t["pc_count"], t["points_by_return"])))
    stray = set(os.listdir(sdir)) - expected_files if os.path.isdir(sdir) else set()
    if stray:
        errors.append(f"stray files in series directory: {sorted(stray)[:5]}")
    if errors:
        raise SystemExit("verify failed before decode:\n" + "\n".join(errors))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2), 25)
    family = collections.Counter()
    total = 0
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        for (tile, _job), res in zip(jobs, pool.imap(check_tile, [j for _, j in jobs])):
            if isinstance(res, str):
                errors.append(res)
                continue
            r = by_tile[tile]
            hist = res["hist"]
            n = sum(hist.values())
            total += n
            family.update(hist)
            if res["sha256"] != r.get("sha256"):
                errors.append(f"{tile}: sha256 differs from index")
            if min(hist) != r.get("min_value") or max(hist) != r.get("max_value"):
                errors.append(f"{tile}: min/max differ from index")
            if {str(k): v for k, v in sorted(hist.items())} != r.get("return_number_histogram"):
                errors.append(f"{tile}: histogram differs from index")
            if len(hist) < 2:
                errors.append(f"{tile}: constant sample")
            if n - hist.get(1, 0) < MIN_NON_FIRST:
                errors.append(f"{tile}: only {n - hist.get(1, 0)} non-first returns")
            if max(hist.values()) > MAX_TOP_SHARE * n:
                errors.append(f"{tile}: one value covers more than {MAX_TOP_SHARE:.2%} of points")
            print(f"ok {tile} points={n} max_return={max(hist)} first_share={hist.get(1, 0) / n:.4f}", flush=True)
    if total and (total - family.get(1, 0)) < FAMILY_MIN_NON_FIRST_SHARE * total:
        errors.append(f"family non-first-return share {(total - family.get(1, 0)) / total:.4f} below "
                      f"{FAMILY_MIN_NON_FIRST_SHARE}")
    if family and max(family) < 5:
        errors.append(f"family maximum return number {max(family)} < 5")
    if len(rows) != ser.get("sample_count"):
        errors.append(f"manifest sample_count {ser.get('sample_count')} != realized {len(rows)}")
    if total != ser.get("total_size_bytes"):
        errors.append(f"manifest total_size_bytes {ser.get('total_size_bytes')} != realized {total}")
    if total < 10000 or sorted(r["value_count"] for r in rows)[len(rows) // 2] < 1000:
        errors.append("below acceptance floor")
    if errors:
        raise SystemExit("verify failed:\n" + "\n".join(errors))
    print(f"verified samples={len(rows)} total_bytes={total}")
    print("family_return_number_share=" + json.dumps({str(k): round(family[k] / total, 6) for k in sorted(family)}))


if __name__ == "__main__":
    main()
