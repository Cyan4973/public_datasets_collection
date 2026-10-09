#!/usr/bin/env python3
"""Verify: independently re-derive every intensity sample and check the index.

Independent of build_intensity.py: re-reads sources.tsv and the downloaded
tiles, re-decodes every tile with tools/laz/laszip.py, and extracts the
Intensity field with struct.iter_unpack('<12xH22x') per record (build uses
byte slicing). Every stored sample must equal the re-derived values exactly.
Also checks: the index has exactly one row per pinned tile with the required
fields and consistent sizes/counts/min/max/sha256; no stray sample files;
each sample is non-constant, has >= 64 distinct values and no value above
50 %; same missing-value policy as build (none: every point emitted, 0 and
65535 kept); manifest sample_count and total_size_bytes equal the realized
output; floors and the 1 GB cap hold.
"""
import argparse
import hashlib
import json
import multiprocessing
import os
import struct
import sys
import tomllib

DATASET_ID = "noaa_ngs_potomac_topobathy_vq880g_intensity_u16"
SERIES_ID = "potomac_topobathy_intensity_u16"
RLEN = 36
REC = struct.Struct("<12xH22x")
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width",
              "endianness", "element_size_bytes", "sample_size_bytes", "value_count"]
LAZ_DIR = None


def check_tile(job):
    sys.path.insert(0, LAZ_DIR)
    import laszip

    src, sample_path, pinned = job
    hdr = laszip.read_header(src)
    if (hdr["version"], hdr["point_format"], hdr["point_record_length"]) != ("1.4", 7, RLEN):
        raise RuntimeError(f"{src}: unexpected layout")
    if hdr["point_count"] != pinned:
        raise RuntimeError(f"{src}: point count {hdr['point_count']} != pinned {pinned}")
    sha = hashlib.sha256()
    hist = {}
    n_total = 0
    with open(sample_path, "rb") as fh:
        for _i, n, recs in laszip.iter_chunks(src, header=hdr):
            vals = [v for (v,) in REC.iter_unpack(bytes(recs[: n * RLEN]))]
            expect = struct.pack(f"<{n}H", *vals)
            got = fh.read(2 * n)
            if got != expect:
                raise RuntimeError(f"{sample_path}: mismatch in points {n_total}..{n_total + n}")
            sha.update(got)
            for v in vals:
                hist[v] = hist.get(v, 0) + 1
            n_total += n
        if fh.read(1):
            raise RuntimeError(f"{sample_path}: trailing bytes beyond {n_total} values")
    if n_total != pinned:
        raise RuntimeError(f"{src}: decoded {n_total} points != {pinned}")
    top = max(hist.values())
    if len(hist) < 64 or top > 0.5 * n_total:
        raise RuntimeError(f"{sample_path}: degenerate (distinct={len(hist)} top={top}/{n_total})")
    return {"values": n_total, "sha256": sha.hexdigest(), "min": min(hist), "max": max(hist)}


def main():
    global LAZ_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--laz-dir", required=True)
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    LAZ_DIR = os.path.abspath(a.laz_dir)
    root = a.data_root
    tiles = []
    for line in open(os.path.join(a.recipe_dir, "sources.tsv"), encoding="utf-8").read().splitlines()[1:]:
        f = line.split("\t")
        tiles.append((f[1], int(f[2]), f[5], int(f[6])))
    index_path = os.path.join(root, "index", DATASET_ID, "samples.jsonl")
    rows = [json.loads(l) for l in open(index_path, encoding="utf-8") if l.strip()]
    if len(rows) != len(tiles):
        raise SystemExit(f"index has {len(rows)} rows, sources.tsv has {len(tiles)} tiles")
    by_tile = {}
    for row in rows:
        for k in INDEX_KEYS:
            if k not in row:
                raise SystemExit(f"index row lacks {k}: {row}")
        if (row["dataset_id"], row["series_id"], row["numeric_kind"], row["bit_width"],
                row["endianness"], row["element_size_bytes"]) != (DATASET_ID, SERIES_ID, "uint", 16, "little", 2):
            raise SystemExit(f"index row has wrong type fields: {row}")
        if row["sample_size_bytes"] != 2 * row["value_count"]:
            raise SystemExit(f"size/count mismatch: {row}")
        by_tile[row["source_tile"]] = row
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    expected_files = set()
    jobs = []
    for tile, size, url, pinned in tiles:
        row = by_tile.get(tile)
        if row is None:
            raise SystemExit(f"no index row for {tile}")
        name = tile.replace("/", "__").replace(".copc.laz", ".bin")
        if row["sample_path"] != f"samples/{DATASET_ID}/{SERIES_ID}/{name}" or row["source_url"] != url:
            raise SystemExit(f"index path/url mismatch for {tile}")
        if row["value_count"] != pinned:
            raise SystemExit(f"{tile}: index count {row['value_count']} != pinned {pinned}")
        sample = os.path.join(root, row["sample_path"])
        if os.path.getsize(sample) != row["sample_size_bytes"]:
            raise SystemExit(f"{sample}: file size != index")
        src = os.path.join(root, "downloads", DATASET_ID, "tiles", tile.replace("/", "__"))
        if os.path.getsize(src) != size:
            raise SystemExit(f"{src}: size != pinned")
        expected_files.add(name)
        jobs.append((src, sample, pinned))
    stray = set(os.listdir(sdir)) - expected_files
    if stray:
        raise SystemExit(f"stray sample files: {sorted(stray)[:5]}")
    n_jobs = a.jobs or min(16, os.cpu_count() or 1)
    with multiprocessing.Pool(n_jobs) as pool:
        results = pool.map(check_tile, jobs, chunksize=1)
    total_values = 0
    for (tile, _s, _u, _p), res in zip(tiles, results):
        row = by_tile[tile]
        if (res["sha256"], res["min"], res["max"]) != (row["sha256"], row["min_value"], row["max_value"]):
            raise SystemExit(f"{tile}: sha256/min/max differ from index")
        total_values += res["values"]
        print(f"ok {tile} values={res['values']} range={res['min']}..{res['max']}", flush=True)
    total_bytes = 2 * total_values
    counts = sorted(r["value_count"] for r in rows)
    median = (counts[(len(counts) - 1) // 2] + counts[len(counts) // 2]) / 2
    if total_values < 10_000 or median < 1000 or total_bytes > 1_000_000_000:
        raise SystemExit(f"floor/cap violated: values={total_values} median={median} bytes={total_bytes}")
    manifest = tomllib.load(open(os.path.join(a.recipe_dir, "manifest.toml"), "rb"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest lacks the primary series")
    if series[0]["sample_count"] != len(rows) or series[0]["total_size_bytes"] != total_bytes:
        raise SystemExit(f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/"
                         f"{series[0]['total_size_bytes']} != realized {len(rows)}/{total_bytes}")
    print(f"verified samples={len(rows)} values={total_values} bytes={total_bytes} median={median}")


if __name__ == "__main__":
    main()
