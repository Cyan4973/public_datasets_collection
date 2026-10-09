#!/usr/bin/env python3
"""Resolve the fixed city-centre z15 blocks to PMTiles leaf directories and tile byte spans.

Documents how blocks.tsv was produced (run by discover.sh, not by the recipe):

  discover.py leaves HEADER_FILE CITIES_TSV          -> prints needed leaf ranges
  discover.py blocks HEADER_FILE CITIES_TSV LEAF_DIR -> writes blocks.tsv to stdout

Each city centre (lat, lon) is projected to fractional z15 Web-Mercator tile
coordinates; the block is the 8x8 tile square aligned to multiples of 8 whose
centre is nearest the city centre. Aligned 2^k squares are contiguous Hilbert
tile-id ranges, and in a clustered PMTiles archive their unique tile payloads
are contiguous in the tile-data section, so each block is one byte span.
"""
from __future__ import annotations

import csv
import hashlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pmtiles_mvt as P  # noqa: E402

Z = 15
B = 8


def block_origin(lat: float, lon: float) -> tuple[int, int]:
    n = 1 << Z
    fx = (lon + 180.0) / 360.0 * n
    lr = math.radians(lat)
    fy = (1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * n
    x0 = B * round((fx - B / 2) / B)
    y0 = B * round((fy - B / 2) / B)
    return int(x0), int(y0)


def load(header_file: str, cities_tsv: str):
    buf = Path(header_file).read_bytes()
    h = P.parse_header(buf)
    root = P.deserialize_directory(P.decompress(
        buf[h["root_dir_offset"]:h["root_dir_offset"] + h["root_dir_length"]], h["internal_compression"]))
    with open(cities_tsv, newline="") as f:
        cities = list(csv.DictReader(f, delimiter="\t"))
    return h, root, cities


def block_tile_ids(x0: int, y0: int):
    return sorted((P.zxy_to_tileid(Z, x0 + dx, y0 + dy), x0 + dx, y0 + dy) for dx in range(B) for dy in range(B))


def main() -> None:
    mode = sys.argv[1]
    h, root, cities = load(sys.argv[2], sys.argv[3])
    if mode == "leaves":
        need = {}
        for c in cities:
            x0, y0 = block_origin(float(c["lat"]), float(c["lon"]))
            for tid, _, _ in block_tile_ids(x0, y0):
                e = P.find_entry(root, tid)
                if e is None or e[3] != 0:
                    raise SystemExit(f"root entry for {c['city']} is not a leaf pointer")
                need[e[1]] = e[2]
        for off, ln in sorted(need.items()):
            print(f"{off}\t{ln}\t{h['leaf_dirs_offset'] + off}")
        return
    leaf_dir = Path(sys.argv[4])
    out = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    out.writerow(["block_id", "city", "continent", "z", "x0", "y0", "first_tile_id",
                  "leaf_offsets", "span_offset", "span_length", "tiles_in_span", "tiles_outside_span"])
    seen = set()
    for c in cities:
        x0, y0 = block_origin(float(c["lat"]), float(c["lon"]))
        if (x0, y0) in seen:
            raise SystemExit(f"duplicate block for {c['city']}")
        seen.add((x0, y0))
        ids = block_tile_ids(x0, y0)
        entries = []
        leaves = set()
        for tid, x, y in ids:
            le = P.find_entry(root, tid)
            leaves.add(le[1])
            raw = (leaf_dir / f"leaf_{le[1]}.gz").read_bytes()
            leaf = P.deserialize_directory(P.decompress(raw, h["internal_compression"]))
            e = P.find_entry(leaf, tid)
            if e is None:
                continue  # tile absent from the archive (no content)
            if e[3] == 0:
                raise SystemExit("nested leaf directories are not expected at this depth")
            entries.append((tid, e[1], e[2]))
        # Main span: merge the unique payload intervals that touch end-to-start
        # and keep the merged interval holding the most block tiles. Tiles whose
        # payload was deduplicated to a distant earlier offset fall outside it.
        uniq = sorted({(t[1], t[2]) for t in entries})
        groups = []
        for off, ln in uniq:
            if groups and off == groups[-1][1]:
                groups[-1][1] = off + ln
            elif groups and off < groups[-1][1]:
                raise SystemExit("overlapping tile payloads")
            else:
                groups.append([off, off + ln])
        def members(g):
            return sum(1 for t in entries if g[0] <= t[1] and t[1] + t[2] <= g[1])
        span_off, span_end = max(groups, key=members)
        inside = sum(1 for t in entries if span_off <= t[1] and t[1] + t[2] <= span_end)
        out.writerow([f"{c['city']}_z15_{x0}_{y0}", c["city"], c["continent"], Z, x0, y0, ids[0][0],
                      ";".join(str(v) for v in sorted(leaves)), h["tile_data_offset"] + span_off,
                      span_end - span_off, inside, len(entries) - inside])


if __name__ == "__main__":
    main()
