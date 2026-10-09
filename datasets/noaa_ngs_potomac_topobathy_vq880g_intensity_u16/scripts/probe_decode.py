#!/usr/bin/env python3
"""Author-time decode probe for selected COPC tiles (range requests only).

For each tile in a selection TSV this fetches, with curl byte-range GETs, the
LAS header + VLRs, the chunk table + EVLRs at the end of the file, and five
LASzip chunks (first two, middle, last two). Those byte ranges are written at
their true offsets into a sparse local file of the tile's full size, so the
repository decoder tools/laz/laszip.py sees a normal file. It then checks the
header (LAS 1.4, PDRF 7, record length 36), decodes the five chunks with
decode_layered_chunk (which raises LazError when a layer decoder does not
consume exactly its bytes) and reports intensity statistics of the decoded
points. A tile whose probe fails is reported FAIL and must be excluded from
the selection (select_tiles.py --exclude) - never silently skipped.

Not part of download/build: it documents how the pinned tiles were vetted.
Usage: probe_decode.py SELECTED_TSV WORK_DIR LAZ_DIR OUT_TSV [--jobs N]
"""
import argparse
import multiprocessing
import os
import struct
import subprocess
import sys

LAZ_DIR = None
PAD = bytes(16)


def fetch_range(url, start, end_incl):
    out = subprocess.run(
        ["curl", "-fsS", "--max-time", "120", "--retry", "5", "-r", f"{start}-{end_incl}", url],
        check=True, capture_output=True).stdout
    if len(out) != end_incl - start + 1:
        raise RuntimeError(f"range {start}-{end_incl} returned {len(out)} bytes")
    return out


def probe(job):
    sys.path.insert(0, LAZ_DIR)
    import laszip

    tile, size, url, work = job
    path = os.path.join(work, tile.replace("/", "__"))
    try:
        with open(path, "wb") as fh:
            fh.truncate(size)
        head = fetch_range(url, 0, 65535)
        offset_points = struct.unpack_from("<I", head, 96)[0]
        if offset_points + 8 > len(head):
            head = fetch_range(url, 0, offset_points + 7)
        (table_off,) = struct.unpack_from("<q", head, offset_points)
        tail = fetch_range(url, table_off, size - 1)
        with open(path, "r+b") as fh:
            fh.write(head)
            fh.seek(table_off)
            fh.write(tail)
        hdr = laszip.read_header(path)
        if (hdr["version"], hdr["point_format"], hdr["point_record_length"]) != ("1.4", 7, 36):
            raise RuntimeError(f"layout {hdr['version']} pf{hdr['point_format']} rl{hdr['point_record_length']}")
        with open(path, "rb") as fh:
            _compressor, items, table = laszip._chunk_plan(fh, hdr)
        entries = table["entries"]
        if not entries:
            raise RuntimeError("no chunk table")
        if sum(c for c, _ in entries) != hdr["point_count"]:
            raise RuntimeError("chunk table point total != header point count")
        starts = [table["chunks_start"]]
        for _c, nb in entries:
            starts.append(starts[-1] + nb)
        if starts[-1] != table_off:
            raise RuntimeError("chunks do not end at the chunk table")
        m = len(entries)
        picks = sorted({0, min(1, m - 1), m // 2, max(m - 2, 0), m - 1})
        hist = {}
        decoded = 0
        channels = {}
        for ci in picks:
            count, nbytes = entries[ci]
            buf = fetch_range(url, starts[ci], starts[ci] + nbytes - 1)
            recs, _end, stored = laszip.decode_layered_chunk(buf + PAD, items, 36, None)
            if stored != count:
                raise RuntimeError(f"chunk {ci} stores {stored} != table {count}")
            vals = memoryview(bytes(recs)).cast("B")
            for i in range(count):
                v = vals[i * 36 + 12] | (vals[i * 36 + 13] << 8)
                hist[v] = hist.get(v, 0) + 1
                ch = (vals[i * 36 + 15] >> 4) & 3
                channels[ch] = channels.get(ch, 0) + 1
            rgb = bytes(recs[30::36]) + bytes(recs[31::36])
            if any(rgb):
                raise RuntimeError(f"chunk {ci}: non-zero RGB")
            decoded += count
        return (tile, "OK", hdr["point_count"], m, len(picks), decoded,
                hist.get(65535, 0) / decoded, hist.get(0, 0) / decoded, len(hist),
                min(hist), max(hist), channels, "")
    except Exception as exc:  # noqa: BLE001 - reported, never skipped
        return (tile, "FAIL", 0, 0, 0, 0, 0.0, 0.0, 0, 0, 0, {}, f"{type(exc).__name__}: {exc}")
    finally:
        if os.path.exists(path):
            os.remove(path)


def main():
    global LAZ_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("selected")
    ap.add_argument("work")
    ap.add_argument("laz_dir")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    LAZ_DIR = os.path.abspath(a.laz_dir)
    os.makedirs(a.work, exist_ok=True)
    jobs = []
    for line in open(a.selected, encoding="utf-8").read().splitlines()[1:]:
        f = line.split("\t")
        jobs.append((f[1], int(f[2]), f[5], a.work))
    with multiprocessing.Pool(a.jobs) as pool:
        results = pool.map(probe, jobs)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("tile\tstatus\tpoint_count\tchunks\tchunks_probed\tpoints_probed\t"
                 "share_65535\tshare_0\tdistinct\tmin\tmax\tscanner_channels\terror\n")
        for r in results:
            fh.write("\t".join(str(x) for x in r) + "\n")
            print("\t".join(str(x) for x in r))
    fails = [r[0] for r in results if r[1] != "OK"]
    print(f"probed={len(results)} failed={len(fails)} {fails}")


if __name__ == "__main__":
    main()
