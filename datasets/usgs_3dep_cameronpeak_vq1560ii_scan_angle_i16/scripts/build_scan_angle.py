#!/usr/bin/env python3
"""Build: decode each pinned LAZ tile and emit its per-point LAS 1.4 scan angles.

For every tile in sources.tsv (local file under downloads/<id>/laz/):
  * re-validate the header (LAS 1.4, system id 'Riegl VQ-1560 II', software
    'GeoCue LAS Updater', compressed PDRF 6, 30-byte records, LASzip
    compressor 3 with the single POINT14 v3 item, pinned point count and
    pinned 15-entry extended points-by-return histogram);
  * decode all LASzip chunks in file order with the repository decoder
    tools/laz/laszip.py iter_chunks;
  * take bytes 18-19 of every 30-byte PDRF-6 record unchanged (the signed
    little-endian int16 scan angle, 0.006 degree units);
  * decode-integrity check: the decoded per-return histogram (low nibble of
    record byte 14) must equal the header's extended points-by-return counts;
  * fail on a decoded point count different from the header, on any scan
    angle outside the LAS 1.4 range -30,000..30,000, on fewer than
    MIN_DISTINCT distinct values or one value covering more than
    MAX_TOP_SHARE of the tile;
  * write the scan angles as a raw little-endian int16 array, one sample per
    tile, value i = point i in file order.
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

DATASET_ID = "usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16"
SERIES_ID = "cpk_2021_scan_angle_i16"
RLEN = 30
MIN_DISTINCT = 100
MAX_TOP_SHARE = 0.5
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOW_NIBBLE = bytes(b & 0x0F for b in range(256))

LAZ_DIR = None


def _init(laz_dir):
    global LAZ_DIR
    LAZ_DIR = laz_dir


def decode_tile(job):
    sys.path.insert(0, LAZ_DIR)
    sys.path.insert(0, SCRIPT_DIR)
    import laszip  # repository decoder
    import cpk_tiles

    path, out_path, row = job
    t0 = time.time()
    hdr = laszip.read_header(path)
    if (hdr["version"] != "1.4" or hdr["point_format"] != 6 or hdr["point_record_length"] != RLEN
            or not hdr["compressed"]):
        raise RuntimeError(f"{path}: unexpected LAS layout {hdr['version']} pf{hdr['point_format']} "
                           f"rl{hdr['point_record_length']}")
    if hdr["system_identifier"] != cpk_tiles.EXPECT_SYSTEM_ID or hdr["generating_software"] != cpk_tiles.EXPECT_SOFTWARE:
        raise RuntimeError(f"{path}: system id {hdr['system_identifier']!r} software {hdr['generating_software']!r}")
    lz = hdr["laszip"]
    if lz["compressor"] != 3 or [(i["type"], i["size"], i["version"]) for i in lz["items"]] != [(10, 30, 3)]:
        raise RuntimeError(f"{path}: unexpected LASzip items {lz}")
    if hdr["point_count"] != row["pc_count"]:
        raise RuntimeError(f"{path}: header count {hdr['point_count']} != pinned {row['pc_count']}")
    if list(hdr["points_by_return_64"]) != row["points_by_return"]:
        raise RuntimeError(f"{path}: header points-by-return differs from pinned sources.tsv")
    out = bytearray()
    rn_hist = [0] * 16
    chunks = 0
    for idx, n, recs in laszip.iter_chunks(path, header=hdr):
        chunks += 1
        if len(recs) < n * RLEN:
            raise RuntimeError(f"{path}: short chunk {idx}")
        recs = bytes(recs[: n * RLEN])
        out += cpk_tiles.scan_angle_bytes(recs, n)
        rn = recs[14::RLEN].translate(LOW_NIBBLE)
        for v in range(16):
            c = rn.count(v)
            if c:
                rn_hist[v] += c
    values = cpk_tiles.as_int16(bytes(out))
    n_points = len(values)
    if n_points != hdr["point_count"]:
        raise RuntimeError(f"{path}: decoded {n_points} points, header says {hdr['point_count']}")
    if rn_hist[1:] != list(hdr["points_by_return_64"]):
        raise RuntimeError(f"{path}: decoded per-return histogram {rn_hist[1:]} != header "
                           f"{hdr['points_by_return_64']} (decode integrity)")
    lo, hi = min(values), max(values)
    if lo < -cpk_tiles.SCAN_ANGLE_SPEC_LIMIT or hi > cpk_tiles.SCAN_ANGLE_SPEC_LIMIT:
        raise RuntimeError(f"{path}: scan angle range {lo}..{hi} outside the LAS 1.4 limit")
    hist = collections.Counter(values)
    top_value, top_count = hist.most_common(1)[0]
    if len(hist) < MIN_DISTINCT:
        raise RuntimeError(f"{path}: only {len(hist)} distinct scan angles")
    if top_count > MAX_TOP_SHARE * n_points:
        raise RuntimeError(f"{path}: value {top_value} covers {top_count / n_points:.2%} of points")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(out)
    os.replace(tmp, out_path)
    return {
        "points": n_points,
        "chunks": chunks,
        "sha256": hashlib.sha256(out).hexdigest(),
        "min_value": lo,
        "max_value": hi,
        "distinct_values": len(hist),
        "top_value": top_value,
        "top_value_share": round(top_count / n_points, 6),
        "zero_share": round(hist.get(0, 0) / n_points, 6),
        "abs_gt_6000": sum(c for v, c in hist.items() if abs(v) > 6000),
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
    import cpk_tiles

    root = a.data_root
    dl = os.path.join(root, "downloads", DATASET_ID, "laz")
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    idir = os.path.join(root, "index", DATASET_ID)
    fdir = os.path.join(root, "filtered", DATASET_ID)
    for d in (sdir, idir, fdir):
        os.makedirs(d, exist_ok=True)
    rows = cpk_tiles.load_sources(cpk_tiles.Path(a.sources))
    for r in rows:
        r["sample_name"] = r["file_name"][:-4] + ".scan_angle_i16.bin"
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
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2), 24)
    print(f"decoding tiles={len(jobs)} jobs={n_jobs}", flush=True)
    t0 = time.time()
    results = []
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        for r, res in zip(rows, pool.imap(decode_tile, jobs)):
            print(f"tile {r['tile_id']} points={res['points']} chunks={res['chunks']} "
                  f"range={res['min_value']}..{res['max_value']} distinct={res['distinct_values']} "
                  f"top={res['top_value']}:{res['top_value_share']} {res['seconds']}s", flush=True)
            results.append(res)
    index_lines = []
    for r, res in zip(rows, results):
        index_lines.append(json.dumps({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{r['sample_name']}",
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": 2 * res["points"],
            "value_count": res["points"],
            "sample_shape": [res["points"]],
            "min_value": res["min_value"],
            "max_value": res["max_value"],
            "distinct_values": res["distinct_values"],
            "top_value_share": res["top_value_share"],
            "sha256": res["sha256"],
            "source_tile": r["tile_id"],
            "source_file": r["file_name"],
            "source_url": r["url"],
        }, sort_keys=True))
    with open(os.path.join(idir, "samples.jsonl.tmp"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(index_lines) + "\n")
    os.replace(os.path.join(idir, "samples.jsonl.tmp"), os.path.join(idir, "samples.jsonl"))
    total_values = sum(res["points"] for res in results)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "tiles": len(results),
        "total_values": total_values,
        "total_bytes": 2 * total_values,
        "median_values": sorted(res["points"] for res in results)[len(results) // 2],
        "family_min": min(res["min_value"] for res in results),
        "family_max": max(res["max_value"] for res in results),
        "per_tile": {r["tile_id"]: res for r, res in zip(rows, results)},
        "decode_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(fdir, "build_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(f"samples={len(results)} total_values={total_values} total_bytes={2 * total_values} "
          f"family_range={stats['family_min']}..{stats['family_max']}")


if __name__ == "__main__":
    main()
