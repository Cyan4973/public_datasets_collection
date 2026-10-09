#!/usr/bin/env python3
"""Deterministic tile selection for noaa_coastal_maine_topobathy_classification_u8.

Inputs (all published by NOAA next to the tiles, fetched by discover.sh):
  * S3 ListObjectsV2 XML pages for prefix laz/geoid18/10423/block (key, size,
    ETag, LastModified of every COPC tile);
  * minmax_2022_ngs_coastalMaine_m10423.csv (per-tile published XYZ extents,
    NAD83(2011) UTM 19N metres, NAVD88 GEOID18 heights).

Selection rule (declared before any tile is decoded; it never looks at the
classification codes):
  1. full-footprint tile: max_x - min_x >= 499.0 m and max_y - min_y >= 499.0 m
     (drops clipped project-edge tiles);
  2. shoreline-straddling tile: min_z <= -3.0 m and max_z >= +3.0 m
     (the published elevation extent crosses the intertidal zone, so the tile
     holds both submerged bottom and land);
  3. within each of the 10 project blocks, sort qualifying tiles by key and take
     the K=5 tiles at ranks floor((2i+1)*m/(2K)), i=0..K-1 (evenly spaced).

Output: sources.tsv with one row per selected tile.
"""
import argparse
import glob
import os
import re
import sys
from collections import defaultdict

PREFIX = "laz/geoid18/10423/"
BASE = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/"
K = 5
MIN_FOOTPRINT = 499.0
Z_LOW = -3.0
Z_HIGH = 3.0
NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
ENTRY = re.compile(
    r"<Contents><Key>([^<]*)</Key><LastModified>([^<]*)</LastModified>"
    r"<ETag>&quot;([^&]*)&quot;</ETag>.*?<Size>(\d+)</Size>", re.S)


def load_listing(pages_dir):
    objs = {}
    for path in sorted(glob.glob(os.path.join(pages_dir, "page_*.xml"))):
        text = open(path, encoding="utf-8").read()
        for m in ENTRY.finditer(text):
            objs[m.group(1)] = (m.group(2), m.group(3), int(m.group(4)))
    return objs


def load_minmax(path):
    out = {}
    lines = open(path, encoding="utf-8").read().splitlines()
    if not lines[0].startswith("Filename"):
        raise SystemExit("unexpected minmax header")
    for line in lines[1:]:
        if not line.strip():
            continue
        name, rest = line.split(",", 1)
        vals = [float(v) for v in NUM.findall(rest.replace("np.float64", ""))]
        if len(vals) != 6:
            raise SystemExit(f"bad minmax row: {line!r}")
        out[name.strip()] = vals
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True)
    ap.add_argument("--minmax", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    objs = load_listing(a.pages)
    mm = load_minmax(a.minmax)
    tiles = {k[len(PREFIX):]: v for k, v in objs.items() if k.endswith(".copc.laz")}
    print(f"listed_tiles={len(tiles)} minmax_rows={len(mm)}")
    if len(tiles) != 44316 or set(tiles) != set(mm):
        raise SystemExit("listing and minmax CSV disagree with the 44,316-tile project")
    by_block = defaultdict(list)
    for name, (x0, x1, y0, y1, z0, z1) in mm.items():
        if x1 - x0 >= MIN_FOOTPRINT and y1 - y0 >= MIN_FOOTPRINT and z0 <= Z_LOW and z1 >= Z_HIGH:
            by_block[name.split("/")[0]].append(name)
    if len(by_block) != 10:
        raise SystemExit(f"expected 10 blocks, got {sorted(by_block)}")
    rows = []
    for block in sorted(by_block):
        cand = sorted(by_block[block])
        m = len(cand)
        print(f"block={block} qualifying={m}")
        for i in range(K):
            name = cand[(2 * i + 1) * m // (2 * K)]
            lm, etag, size = tiles[name]
            x0, x1, y0, y1, z0, z1 = mm[name]
            rows.append((block, name, size, etag, lm, f"{z0:.3f}", f"{z1:.3f}", m, BASE + PREFIX + name))
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("block\ttile\tsize_bytes\tetag\tlast_modified\tmin_z\tmax_z\tblock_qualifying\turl\n")
        for r in rows:
            fh.write("\t".join(str(v) for v in r) + "\n")
    print(f"selected={len(rows)} bytes={sum(r[2] for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
