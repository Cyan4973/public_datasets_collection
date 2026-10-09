#!/usr/bin/env python3
"""Build: decode each pinned COPC tile and emit its per-point classification bytes.

For every tile in sources.tsv (local file under downloads/<id>/tiles/):
  * decode all LASzip chunks with the repository decoder tools/laz/laszip.py
    (compressor 3, POINT14 v3, variable COPC chunks; every layer decoder must
    consume exactly its layer bytes or LazError is raised);
  * take byte 16 of every 30-byte PDRF-6 record (the full-byte LAS 1.4
    classification field; classification flags live in byte 15 and are not
    touched) in stored file order;
  * integrity checks against the LAS header: decoded point count, the 15
    extended points-by-return counts (return number = low nibble of byte 14),
    and decoded X/Y/Z inside the header bounds (half a scale step slack);
  * write the codes unchanged as a raw uint8 array, one sample per tile.
No missing-value handling exists: every point record is emitted.
"""
import argparse
import collections
import hashlib
import json
import multiprocessing
import os
import struct
import sys
import time

DATASET_ID = "noaa_coastal_maine_topobathy_classification_u8"
SERIES_ID = "maine_topobathy_classification_u8"
RLEN = 30
CLASS_OFFSET = 16
# Codes named in the metadata lineage (contractor scheme and final NOAA scheme)
# plus 0 (never classified) and 17/18 (ASPRS bridge deck / high noise).
DOCUMENTED = {0, 1, 2, 7, 17, 18, 22, 40, 41, 42, 43, 45, 64, 65, 71, 72, 81, 82, 85}
MAX_UNDOCUMENTED_SHARE = 0.01
XYZ = struct.Struct("<iii18x")

LAZ_DIR = None


def decode_tile(job):
    sys.path.insert(0, LAZ_DIR)
    import laszip  # repository decoder

    path, out_path, pinned_count = job
    t0 = time.time()
    hdr = laszip.read_header(path)
    if hdr["version"] != "1.4" or hdr["point_format"] != 6 or hdr["point_record_length"] != RLEN:
        raise RuntimeError(f"{path}: unexpected LAS layout {hdr['version']} pf{hdr['point_format']} rl{hdr['point_record_length']}")
    if hdr["point_count"] != pinned_count:
        raise RuntimeError(f"{path}: header count {hdr['point_count']} != pinned {pinned_count}")
    codes = bytearray()
    returns = collections.Counter()
    channels = collections.Counter()
    flag_bits = collections.Counter()
    lo = [2**31, 2**31, 2**31]
    hi = [-2**31, -2**31, -2**31]
    chunks = 0
    for _idx, n, recs in laszip.iter_chunks(path, header=hdr):
        chunks += 1
        if len(recs) < n * RLEN:
            raise RuntimeError(f"{path}: short chunk")
        recs = bytes(recs[: n * RLEN])
        codes += recs[CLASS_OFFSET::RLEN]
        returns.update(b & 0x0F for b in recs[14::RLEN])
        fl = collections.Counter(recs[15::RLEN])
        for b, c in fl.items():
            channels[(b >> 4) & 3] += c
            for bit, name in ((1, "synthetic"), (2, "keypoint"), (4, "withheld"), (8, "overlap")):
                if b & bit:
                    flag_bits[name] += c
        xs, ys, zs = zip(*XYZ.iter_unpack(recs))
        lo = [min(lo[0], min(xs)), min(lo[1], min(ys)), min(lo[2], min(zs))]
        hi = [max(hi[0], max(xs)), max(hi[1], max(ys)), max(hi[2], max(zs))]
    if len(codes) != hdr["point_count"]:
        raise RuntimeError(f"{path}: decoded {len(codes)} points, header says {hdr['point_count']}")
    by_return = [returns.get(r, 0) for r in range(1, 16)]
    if by_return != list(hdr["points_by_return_64"]):
        raise RuntimeError(f"{path}: decoded points-by-return {by_return} != header {hdr['points_by_return_64']}")
    for axis in range(3):
        s, o = hdr["scale"][axis], hdr["offset"][axis]
        dmin, dmax = lo[axis] * s + o, hi[axis] * s + o
        if dmin < hdr["min"][axis] - s / 2 or dmax > hdr["max"][axis] + s / 2:
            raise RuntimeError(f"{path}: axis {axis} decoded range {dmin}..{dmax} outside header {hdr['min'][axis]}..{hdr['max'][axis]}")
    hist = collections.Counter(codes)
    undocumented = sum(c for k, c in hist.items() if k not in DOCUMENTED)
    if undocumented > MAX_UNDOCUMENTED_SHARE * len(codes):
        raise RuntimeError(f"{path}: {undocumented} points carry undocumented class codes {sorted(k for k in hist if k not in DOCUMENTED)}")
    if len(hist) < 2:
        raise RuntimeError(f"{path}: constant classification stream")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(codes)
    os.replace(tmp, out_path)
    return {
        "points": len(codes),
        "chunks": chunks,
        "sha256": hashlib.sha256(codes).hexdigest(),
        "class_histogram": {str(k): hist[k] for k in sorted(hist)},
        "scanner_channels": {str(k): channels[k] for k in sorted(channels)},
        "classification_flag_counts": dict(sorted(flag_bits.items())),
        "points_by_return": by_return,
        "min_value": min(hist),
        "max_value": max(hist),
        "seconds": round(time.time() - t0, 1),
    }


def main():
    global LAZ_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--laz-dir", required=True)
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    LAZ_DIR = a.laz_dir
    root = a.data_root
    dl = os.path.join(root, "downloads", DATASET_ID, "tiles")
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    idir = os.path.join(root, "index", DATASET_ID)
    fdir = os.path.join(root, "filtered", DATASET_ID)
    for d in (sdir, idir, fdir):
        os.makedirs(d, exist_ok=True)
    rows = []
    for line in open(a.sources, encoding="utf-8").read().splitlines()[1:]:
        f = line.split("\t")
        rows.append({"block": f[0], "tile": f[1], "size": int(f[2]), "url": f[8], "point_count": int(f[9])})
    expected = {r["tile"].replace("/", "__").replace(".copc.laz", ".bin") for r in rows}
    for name in os.listdir(sdir):
        if name not in expected:
            os.remove(os.path.join(sdir, name))  # stale output from an earlier build
    jobs = []
    for r in rows:
        src = os.path.join(dl, r["tile"].replace("/", "__"))
        if not os.path.isfile(src) or os.path.getsize(src) != r["size"]:
            raise SystemExit(f"missing or incomplete download: {src}")
        r["sample_name"] = r["tile"].replace("/", "__").replace(".copc.laz", ".bin")
        jobs.append((src, os.path.join(sdir, r["sample_name"]), r["point_count"]))
    n_jobs = a.jobs or min(len(jobs), max(1, (os.cpu_count() or 2) // 2), 25)
    print(f"decoding tiles={len(jobs)} jobs={n_jobs}", flush=True)
    t0 = time.time()
    with multiprocessing.Pool(n_jobs, initializer=_init, initargs=(a.laz_dir,)) as pool:
        results = []
        for r, res in zip(rows, pool.imap(decode_tile, jobs)):
            print(f"tile {r['tile']} points={res['points']} chunks={res['chunks']} "
                  f"classes={res['class_histogram']} {res['seconds']}s", flush=True)
            results.append(res)
    family = collections.Counter()
    index_lines = []
    for r, res in zip(rows, results):
        family.update({int(k): v for k, v in res["class_histogram"].items()})
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
            "min_value": res["min_value"],
            "max_value": res["max_value"],
            "sha256": res["sha256"],
            "source_tile": r["tile"],
            "source_url": r["url"],
            "project_block": r["block"],
            "class_histogram": res["class_histogram"],
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
        "family_class_histogram": {str(k): family[k] for k in sorted(family)},
        "family_class_share": {str(k): round(family[k] / total, 6) for k in sorted(family)},
        "per_tile": {r["tile"]: res for r, res in zip(rows, results)},
        "decode_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(fdir, "ingest_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(f"samples={len(results)} total_bytes={total}")
    print("family_class_share=" + json.dumps(stats["family_class_share"]))


def _init(laz_dir):
    global LAZ_DIR
    LAZ_DIR = laz_dir


if __name__ == "__main__":
    main()
