#!/usr/bin/env python3
"""Build: decode each pinned LAZ tile and emit its per-point LAS return numbers.

For every tile in sources.tsv (local file under downloads/<id>/laz/):
  * re-validate the header (LAS 1.4, system id MERGE, software LiDAR Suite,
    compressed PDRF 6, 30-byte records, pinned point count and pinned 15-entry
    extended points-by-return histogram);
  * decode all LASzip chunks in file order with the repository decoder
    tools/laz/laszip.py iter_chunks (compressor 3, POINT14 v3, 50,000-point
    chunks);
  * take byte 14 of every 30-byte PDRF-6 record and keep its low nibble, the
    LAS 1.4 return number (1..15); the high nibble (number of returns) is only
    used for statistics and the return-number <= number-of-returns check;
  * fail on any return number 0, on any mismatch between the decoded
    per-return histogram and the header's extended points-by-return counts,
    on a decoded point count different from the header, on a constant tile,
    or if more than MAX_RN_GT_NR_SHARE of the points have return number >
    number of returns;
  * write the return numbers as a raw uint8 array, one sample per tile.
No missing-value handling exists: every point record is emitted.
"""
import argparse
import collections
import hashlib
import json
import multiprocessing
import os
import sys
import time

DATASET_ID = "usgs_3dep_id_northforkpayette_laz_return_number_u8"
SERIES_ID = "nfp_2020_return_number_u8"
RLEN = 30
MAX_RN_GT_NR_SHARE = 0.001
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

LAZ_DIR = None


def _init(laz_dir):
    global LAZ_DIR
    LAZ_DIR = laz_dir


def decode_tile(job):
    sys.path.insert(0, LAZ_DIR)
    sys.path.insert(0, SCRIPT_DIR)
    import laszip  # repository decoder
    import nfp_tiles

    path, out_path, row = job
    t0 = time.time()
    hdr = laszip.read_header(path)
    if (hdr["version"] != "1.4" or hdr["point_format"] != 6 or hdr["point_record_length"] != RLEN
            or not hdr["compressed"]):
        raise RuntimeError(f"{path}: unexpected LAS layout {hdr['version']} pf{hdr['point_format']} "
                           f"rl{hdr['point_record_length']}")
    if hdr["system_identifier"] != nfp_tiles.EXPECT_SYSTEM_ID or hdr["generating_software"] != nfp_tiles.EXPECT_SOFTWARE:
        raise RuntimeError(f"{path}: system id {hdr['system_identifier']!r} software {hdr['generating_software']!r}")
    lz = hdr["laszip"]
    if lz["compressor"] != 3 or [(i["type"], i["size"], i["version"]) for i in lz["items"]] != [(10, 30, 3)]:
        raise RuntimeError(f"{path}: unexpected LASzip items {lz}")
    if hdr["point_count"] != row["pc_count"]:
        raise RuntimeError(f"{path}: header count {hdr['point_count']} != pinned {row['pc_count']}")
    if list(hdr["points_by_return_64"]) != row["points_by_return"]:
        raise RuntimeError(f"{path}: header points-by-return differs from pinned sources.tsv")
    out = bytearray()
    nr_hist = collections.Counter()
    rn_gt_nr = 0
    chunks = 0
    for _idx, n, recs in laszip.iter_chunks(path, header=hdr):
        chunks += 1
        if len(recs) < n * RLEN:
            raise RuntimeError(f"{path}: short chunk {_idx}")
        recs = bytes(recs[: n * RLEN])
        rn = nfp_tiles.return_numbers(recs, n)
        nr = nfp_tiles.numbers_of_returns(recs, n)
        out += rn
        for v in range(16):
            c = nr.count(v)
            if c:
                nr_hist[v] += c
        rn_gt_nr += sum(1 for a, b in zip(rn, nr) if a > b)
    n_points = len(out)
    if n_points != hdr["point_count"]:
        raise RuntimeError(f"{path}: decoded {n_points} points, header says {hdr['point_count']}")
    rn_hist = [out.count(v) for v in range(16)]
    if rn_hist[0]:
        raise RuntimeError(f"{path}: {rn_hist[0]} points carry return number 0")
    if rn_hist[1:] != list(hdr["points_by_return_64"]):
        raise RuntimeError(f"{path}: decoded per-return histogram {rn_hist[1:]} != header {hdr['points_by_return_64']}")
    if sum(1 for c in rn_hist if c) < 2:
        raise RuntimeError(f"{path}: constant return-number stream")
    if rn_gt_nr > MAX_RN_GT_NR_SHARE * n_points:
        raise RuntimeError(f"{path}: {rn_gt_nr} points have return number > number of returns")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(out)
    os.replace(tmp, out_path)
    present = [v for v in range(16) if rn_hist[v]]
    return {
        "points": n_points,
        "chunks": chunks,
        "sha256": hashlib.sha256(out).hexdigest(),
        "return_number_histogram": {str(v): rn_hist[v] for v in present},
        "number_of_returns_histogram": {str(k): nr_hist[k] for k in sorted(nr_hist)},
        "return_number_gt_number_of_returns": rn_gt_nr,
        "min_value": min(present),
        "max_value": max(present),
        "seconds": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--laz-dir", required=True)
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    sys.path.insert(0, SCRIPT_DIR)
    import nfp_tiles

    root = a.data_root
    dl = os.path.join(root, "downloads", DATASET_ID, "laz")
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    idir = os.path.join(root, "index", DATASET_ID)
    fdir = os.path.join(root, "filtered", DATASET_ID)
    for d in (sdir, idir, fdir):
        os.makedirs(d, exist_ok=True)
    rows = nfp_tiles.load_sources(nfp_tiles.Path(a.sources))
    for r in rows:
        r["sample_name"] = r["file_name"][:-4] + ".return_number_u8.bin"
    expected = {r["sample_name"] for r in rows}
    for name in os.listdir(sdir):
        if name not in expected:
            os.remove(os.path.join(sdir, name))  # stale output from an earlier build
    jobs = []
    for r in rows:
        src = os.path.join(dl, r["file_name"])
        if not os.path.isfile(src) or os.path.getsize(src) != r["size_bytes"]:
            raise SystemExit(f"missing or incomplete download: {src}")
        jobs.append((src, os.path.join(sdir, r["sample_name"]), r))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2), 25)
    print(f"decoding tiles={len(jobs)} jobs={n_jobs}", flush=True)
    t0 = time.time()
    results = []
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        for r, res in zip(rows, pool.imap(decode_tile, jobs)):
            print(f"tile {r['tile_id']} points={res['points']} chunks={res['chunks']} "
                  f"returns={res['return_number_histogram']} rn>nr={res['return_number_gt_number_of_returns']} "
                  f"{res['seconds']}s", flush=True)
            results.append(res)
    family = collections.Counter()
    index_lines = []
    for r, res in zip(rows, results):
        family.update({int(k): v for k, v in res["return_number_histogram"].items()})
        index_lines.append(json.dumps({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{r['sample_name']}",
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": res["points"],
            "value_count": res["points"],
            "sample_shape": [res["points"]],
            "min_value": res["min_value"],
            "max_value": res["max_value"],
            "sha256": res["sha256"],
            "source_tile": r["tile_id"],
            "source_file": r["file_name"],
            "source_url": r["url"],
            "return_number_histogram": res["return_number_histogram"],
        }, sort_keys=True))
    with open(os.path.join(idir, "samples.jsonl.tmp"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(index_lines) + "\n")
    os.replace(os.path.join(idir, "samples.jsonl.tmp"), os.path.join(idir, "samples.jsonl"))
    total = sum(res["points"] for res in results)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "tiles": len(results),
        "total_values": total,
        "total_bytes": total,
        "median_values": sorted(res["points"] for res in results)[len(results) // 2],
        "family_return_number_histogram": {str(k): family[k] for k in sorted(family)},
        "family_return_number_share": {str(k): round(family[k] / total, 6) for k in sorted(family)},
        "per_tile": {r["tile_id"]: res for r, res in zip(rows, results)},
        "decode_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(fdir, "build_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(f"samples={len(results)} total_bytes={total}")
    print("family_return_number_share=" + json.dumps(stats["family_return_number_share"]))


if __name__ == "__main__":
    main()
