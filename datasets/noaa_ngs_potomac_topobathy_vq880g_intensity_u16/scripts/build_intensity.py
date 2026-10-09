#!/usr/bin/env python3
"""Build: decode each pinned COPC tile and emit its per-point intensity array.

For every tile in sources.tsv (local file under downloads/<id>/tiles/):
  * decode all LASzip chunks with the repository decoder tools/laz/laszip.py
    (compressor 3, POINT14 v3 + RGB14 v3 items, variable COPC chunks; every
    layer decoder must consume exactly its layer bytes or LazError is raised);
  * take bytes 12..13 of every 36-byte PDRF-7 record (the LAS Intensity
    field, unsigned 16-bit little-endian) in stored file order, i.e. the COPC
    octree-node (chunk) order written by NOAA OCM, point order within a node
    as stored;
  * integrity checks against the LAS header: decoded point count equals the
    header and the pinned count, the 15 extended points-by-return counts
    (return number = low nibble of byte 14), and decoded X/Y/Z inside the
    header bounds (half a scale step slack);
  * write the intensity values unchanged as raw little-endian uint16, one
    sample per tile.
No missing-value handling exists: every point record is emitted, including
intensity 0 and the saturated value 65535. RGB (bytes 30..35) is all zero in
this delivery and is not emitted; its non-zero count is recorded in the stats.
"""
import argparse
import array
import collections
import hashlib
import json
import multiprocessing
import os
import struct
import sys
import time

DATASET_ID = "noaa_ngs_potomac_topobathy_vq880g_intensity_u16"
SERIES_ID = "potomac_topobathy_intensity_u16"
RLEN = 36
INTENSITY_OFFSET = 12
MAX_DOMINANT_SHARE = 0.5
MIN_DISTINCT = 64
MAX_PRIMARY_BYTES = 1_000_000_000
XYZ = struct.Struct("<iii24x")

LAZ_DIR = None


def read_sources(path):
    rows = []
    for line in open(path, encoding="utf-8").read().splitlines()[1:]:
        f = line.split("\t")
        rows.append({"delivery": f[0], "tile": f[1], "size": int(f[2]), "etag": f[3],
                     "url": f[5], "point_count": int(f[6]),
                     "sha256": f[7] if len(f) > 7 and f[7] else ""})
    return rows


def sample_name(tile):
    return tile.replace("/", "__").replace(".copc.laz", ".bin")


def decode_tile(job):
    sys.path.insert(0, LAZ_DIR)
    import laszip  # repository decoder

    path, out_path, pinned_count = job
    t0 = time.time()
    hdr = laszip.read_header(path)
    if hdr["version"] != "1.4" or hdr["point_format"] != 7 or hdr["point_record_length"] != RLEN:
        raise RuntimeError(f"{path}: unexpected LAS layout {hdr['version']} "
                           f"pf{hdr['point_format']} rl{hdr['point_record_length']}")
    if hdr["point_count"] != pinned_count:
        raise RuntimeError(f"{path}: header count {hdr['point_count']} != pinned {pinned_count}")
    payload = bytearray()
    returns = collections.Counter()
    channels = collections.Counter()
    sources = set()
    rgb_nonzero = 0
    lo = [2**31] * 3
    hi = [-2**31] * 3
    chunks = 0
    for _idx, n, recs in laszip.iter_chunks(path, header=hdr):
        chunks += 1
        if len(recs) < n * RLEN:
            raise RuntimeError(f"{path}: short chunk")
        recs = bytes(recs[: n * RLEN])
        part = bytearray(2 * n)
        part[0::2] = recs[INTENSITY_OFFSET::RLEN]
        part[1::2] = recs[INTENSITY_OFFSET + 1::RLEN]
        payload += part
        for b, c in collections.Counter(recs[14::RLEN]).items():
            returns[b & 0x0F] += c
        for b, c in collections.Counter(recs[15::RLEN]).items():
            channels[(b >> 4) & 3] += c
        psid = bytearray(2 * n)
        psid[0::2] = recs[20::RLEN]
        psid[1::2] = recs[21::RLEN]
        src = array.array("H")
        src.frombytes(bytes(psid))
        sources.update(src)
        for k in range(30, 36):
            rgb_nonzero += n - recs[k::RLEN].count(0)
        xs, ys, zs = zip(*XYZ.iter_unpack(recs))
        lo = [min(lo[0], min(xs)), min(lo[1], min(ys)), min(lo[2], min(zs))]
        hi = [max(hi[0], max(xs)), max(hi[1], max(ys)), max(hi[2], max(zs))]
    count = len(payload) // 2
    if count != hdr["point_count"]:
        raise RuntimeError(f"{path}: decoded {count} points, header says {hdr['point_count']}")
    by_return = [returns.get(r, 0) for r in range(1, 16)]
    if by_return != list(hdr["points_by_return_64"]):
        raise RuntimeError(f"{path}: decoded points-by-return {by_return} != header "
                           f"{hdr['points_by_return_64']}")
    for axis in range(3):
        s, o = hdr["scale"][axis], hdr["offset"][axis]
        dmin, dmax = lo[axis] * s + o, hi[axis] * s + o
        if dmin < hdr["min"][axis] - s / 2 or dmax > hdr["max"][axis] + s / 2:
            raise RuntimeError(f"{path}: axis {axis} decoded range {dmin}..{dmax} outside header "
                               f"{hdr['min'][axis]}..{hdr['max'][axis]}")
    vals = array.array("H")
    vals.frombytes(bytes(payload))
    if sys.byteorder != "little":
        vals.byteswap()
    hist = collections.Counter(vals)
    top_value, top_count = hist.most_common(1)[0]
    if len(hist) < MIN_DISTINCT:
        raise RuntimeError(f"{path}: only {len(hist)} distinct intensity values")
    if top_count > MAX_DOMINANT_SHARE * count:
        raise RuntimeError(f"{path}: value {top_value} covers {top_count}/{count} points")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, out_path)
    return {
        "points": count,
        "chunks": chunks,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "min_value": min(hist),
        "max_value": max(hist),
        "distinct_values": len(hist),
        "count_65535": hist.get(65535, 0),
        "count_0": hist.get(0, 0),
        "dominant_value": top_value,
        "dominant_share": round(top_count / count, 6),
        "mean": round(sum(v * c for v, c in hist.items()) / count, 3),
        "scanner_channels": {str(k): channels[k] for k in sorted(channels)},
        "point_source_ids": len(sources),
        "rgb_nonzero_bytes": rgb_nonzero,
        "points_by_return": by_return,
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
    LAZ_DIR = os.path.abspath(a.laz_dir)
    root = a.data_root
    dl = os.path.join(root, "downloads", DATASET_ID, "tiles")
    sdir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    idir = os.path.join(root, "index", DATASET_ID)
    fdir = os.path.join(root, "filtered", DATASET_ID)
    for d in (sdir, idir, fdir):
        os.makedirs(d, exist_ok=True)
    rows = read_sources(a.sources)
    expected = {sample_name(r["tile"]) for r in rows}
    if len(expected) != len(rows):
        raise SystemExit("duplicate tiles in sources.tsv")
    for name in os.listdir(sdir):
        if name not in expected:
            os.remove(os.path.join(sdir, name))  # stale output from an earlier build
    jobs = []
    for r in rows:
        src = os.path.join(dl, r["tile"].replace("/", "__"))
        if not os.path.isfile(src) or os.path.getsize(src) != r["size"]:
            raise SystemExit(f"missing or incomplete download (run download.sh): {src}")
        jobs.append((src, os.path.join(sdir, sample_name(r["tile"])), r["point_count"]))
    n_jobs = a.jobs or min(16, os.cpu_count() or 1)
    t0 = time.time()
    with multiprocessing.Pool(n_jobs) as pool:
        results = pool.map(decode_tile, jobs, chunksize=1)
    index_rows = []
    total_values = 0
    total_65535 = 0
    total_0 = 0
    per_tile = []
    for r, res in zip(rows, results):
        name = sample_name(r["tile"])
        size = res["points"] * 2
        total_values += res["points"]
        total_65535 += res["count_65535"]
        total_0 += res["count_0"]
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{name}",
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": size,
            "value_count": res["points"],
            "min_value": res["min_value"],
            "max_value": res["max_value"],
            "sha256": res["sha256"],
            "source_tile": r["tile"],
            "source_url": r["url"],
        })
        per_tile.append({"tile": r["tile"], **res})
        print(f"tile {r['tile']} points={res['points']} chunks={res['chunks']} "
              f"distinct={res['distinct_values']} range={res['min_value']}..{res['max_value']} "
              f"share65535={res['count_65535'] / res['points']:.6f} "
              f"share0={res['count_0'] / res['points']:.6f} channels={res['scanner_channels']} "
              f"flightlines={res['point_source_ids']} rgb_nonzero={res['rgb_nonzero_bytes']} "
              f"t={res['seconds']}s", flush=True)
    total_bytes = total_values * 2
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output {total_bytes} exceeds cap")
    sizes = sorted(row["value_count"] for row in index_rows)
    median = sizes[len(sizes) // 2] if len(sizes) % 2 else (sizes[len(sizes) // 2 - 1] + sizes[len(sizes) // 2]) / 2
    if median < 1000:
        raise SystemExit(f"median sample size {median} below floor")
    index_path = os.path.join(idir, "samples.jsonl")
    with open(index_path + ".tmp", "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(index_path + ".tmp", index_path)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(index_rows),
        "total_values": total_values,
        "total_size_bytes": total_bytes,
        "median_sample_values": median,
        "share_65535": round(total_65535 / total_values, 8),
        "share_0": round(total_0 / total_values, 8),
        "tiles": per_tile,
    }
    with open(os.path.join(fdir, "ingest_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(f"samples={len(index_rows)} values={total_values} bytes={total_bytes} median={median} "
          f"share65535={stats['share_65535']} share0={stats['share_0']} "
          f"elapsed={time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
