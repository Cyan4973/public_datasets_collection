#!/usr/bin/env python3
"""Verify: independently re-derive every sample and check index and manifest.

* manifest series totals (sample_count, total_size_bytes) equal the realized
  output, and the index has exactly one row per pinned tile with the required
  fields, uint8 / little / element size 1, value_count == file size;
* each tile is decoded again from the local download with
  tools/laz/laszip.decode_points (whole-file path, not the chunk iterator the
  build uses); byte 16 of every 30-byte record must equal the sample file byte
  for byte, and the count must equal the pinned header point count;
* per-sample sha256 / min / max equal the index; no sample is constant or
  dominated (>99.9%) by a single code; no stray files in the series directory;
* the family must contain the topobathy domain codes 40 (bathymetric bottom)
  and 41 or 42 (water surface) in at least half of the tiles.
Same missing-value policy as the build: none, every point record is emitted.
"""
import argparse
import collections
import hashlib
import json
import multiprocessing
import os
import sys
import tomllib

DATASET_ID = "noaa_coastal_maine_topobathy_classification_u8"
SERIES_ID = "maine_topobathy_classification_u8"
REQUIRED = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
            "element_size_bytes", "sample_size_bytes", "value_count"]
LAZ_DIR = None


def _init(laz_dir):
    global LAZ_DIR
    LAZ_DIR = laz_dir


def check_tile(job):
    sys.path.insert(0, LAZ_DIR)
    import laszip

    laz_path, sample_path, pinned = job
    hdr, recs = laszip.decode_points(laz_path)
    rlen = hdr["point_record_length"]
    if hdr["point_format"] != 6 or rlen != 30:
        return f"{laz_path}: unexpected point layout"
    codes = bytes(recs[16::rlen])
    if len(codes) != pinned or len(codes) != hdr["point_count"]:
        return f"{laz_path}: decoded {len(codes)} points, pinned {pinned}"
    with open(sample_path, "rb") as fh:
        stored = fh.read()
    if stored != codes:
        return f"{sample_path}: bytes differ from re-decoded classification codes"
    hist = collections.Counter(codes)
    return {"sha256": hashlib.sha256(codes).hexdigest(), "hist": dict(hist)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--laz-dir", required=True)
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    root = a.data_root
    errors = []
    man = tomllib.load(open(a.manifest, "rb"))
    series = [s for s in man["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        raise SystemExit("manifest must declare exactly one primary series")
    ser = series[0]
    if (ser["numeric_kind"], ser["bit_width"], ser["endianness"]) != ("uint", 8, "little"):
        errors.append("manifest series type is not uint8 little-endian")
    tiles = []
    for line in open(a.sources, encoding="utf-8").read().splitlines()[1:]:
        f = line.split("\t")
        tiles.append((f[1], int(f[9])))
    idx_path = os.path.join(root, "index", DATASET_ID, "samples.jsonl")
    rows = [json.loads(l) for l in open(idx_path, encoding="utf-8") if l.strip()]
    if len(rows) != len(tiles):
        errors.append(f"index rows {len(rows)} != pinned tiles {len(tiles)}")
    by_tile = {r.get("source_tile"): r for r in rows}
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    expected_files = set()
    jobs = []
    for tile, pinned in tiles:
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
        expected_files.add(os.path.basename(sp))
        size = os.path.getsize(sp) if os.path.isfile(sp) else -1
        if size != r.get("value_count") or size != r.get("sample_size_bytes") or size != pinned:
            errors.append(f"{tile}: sample size {size} vs index {r.get('value_count')} vs pinned {pinned}")
        laz = os.path.join(root, "downloads", DATASET_ID, "tiles", tile.replace("/", "__"))
        jobs.append((tile, (laz, sp, pinned)))
    stray = set(os.listdir(sdir)) - expected_files
    if stray:
        errors.append(f"stray files in series directory: {sorted(stray)[:5]}")
    if errors:
        raise SystemExit("verify failed before decode:\n" + "\n".join(errors))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2), 25)
    family = collections.Counter()
    bathy_tiles = 0
    total = 0
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        for (tile, job), res in zip(jobs, pool.imap(check_tile, [j for _, j in jobs])):
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
            if {str(k): v for k, v in sorted(hist.items())} != r.get("class_histogram"):
                errors.append(f"{tile}: class histogram differs from index")
            if len(hist) < 2:
                errors.append(f"{tile}: constant sample")
            if max(hist.values()) > 0.999 * n:
                errors.append(f"{tile}: one code covers >99.9% of points")
            if 40 in hist and (41 in hist or 42 in hist):
                bathy_tiles += 1
            print(f"ok {tile} points={n} classes={len(hist)} top={collections.Counter(hist).most_common(3)}", flush=True)
    if bathy_tiles * 2 < len(jobs):
        errors.append(f"only {bathy_tiles}/{len(jobs)} tiles carry bathymetric bottom + water surface codes")
    if len(rows) != ser.get("sample_count"):
        errors.append(f"manifest sample_count {ser.get('sample_count')} != realized {len(rows)}")
    if total != ser.get("total_size_bytes"):
        errors.append(f"manifest total_size_bytes {ser.get('total_size_bytes')} != realized {total}")
    if total < 10000 or sorted(r["value_count"] for r in rows)[len(rows) // 2] < 1000:
        errors.append("below acceptance floor")
    if errors:
        raise SystemExit("verify failed:\n" + "\n".join(errors))
    print(f"verified samples={len(rows)} total_bytes={total} bathy_tiles={bathy_tiles}")
    print("family_class_share=" + json.dumps({str(k): round(family[k] / total, 6) for k in sorted(family)}))


if __name__ == "__main__":
    main()
