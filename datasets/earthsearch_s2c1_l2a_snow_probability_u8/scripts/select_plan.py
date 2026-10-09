#!/usr/bin/env python3
"""Deterministic scene selection that produced sources.tsv (documentation).

Not run by download.sh or build.sh.

    python3 -I select_plan.py ALL.tsv PROBE_DIR OUT_sources.tsv

ALL.tsv is discover.py output. Rule:
  1. Keep sentinel-2-c1-l2a items (processing baseline 05.10) whose URL is the
     SNW_20m.tif asset of the C1 bucket and |centroid_lat| <= 72.
  2. One scene per MGRS tile: the item whose s2:snow_ice_percentage is closest
     to 50 (ties: lower cloud, then earlier datetime).
  3. Group tiles into 10 deg latitude x 20 deg longitude cells; keep cells
     with >= 3 tiles; in each cell take the 4 tiles closest to 50 % snow.
  4. Probe those candidates' COG headers (range bytes 0-4095, which hold the
     IFD0 GDAL statistics written with nodata=0): nonzero fraction
     v = STATISTICS_VALID_PERCENT / 100. Require 0.30 <= v <= 0.75 so the zero
     share stays <= 0.70.
  5. Per cell pick the probed tile with v closest to 0.5; rank cells by tile
     count (descending, ties by cell key) and take the first 30.
build.sh / verify.sh enforce the real full-grid limit (mode share <= 0.80).
"""
from __future__ import annotations

import csv
import os
import re
import struct
import subprocess
import sys

N_SCENES = 30
URL_RE = re.compile(
    r"https://e84-earth-search-sentinel-data\.s3\.us-west-2\.amazonaws\.com/sentinel-2-c1-l2a/"
    r"\d{1,2}/[A-Z]/[A-Z]{2}/2024/[34]/S2[ABC]_T\d{2}[A-Z]{3}_2024\d{4}T\d{6}_L2A/SNW_20m\.tif"
)


def header_stats(path: str) -> dict:
    d = open(path, "rb").read()
    assert d[:4] == b"II*\x00", path
    off = struct.unpack_from("<I", d, 4)[0]
    n = struct.unpack_from("<H", d, off)[0]
    meta = ""
    for i in range(n):
        t, ty, c, v = struct.unpack_from("<HHII", d, off + 2 + i * 12)
        if t == 42112:
            meta = d[v:v + c].decode("latin1")
    stats = dict(re.findall(r'<Item name="STATISTICS_(\w+)" sample="0">([^<]+)</Item>', meta))
    return {k: float(x) for k, x in stats.items()}


def main() -> None:
    all_tsv, probe_dir, out_path = sys.argv[1:4]
    os.makedirs(probe_dir, exist_ok=True)
    rows = list(csv.DictReader(open(all_tsv, encoding="utf-8"), delimiter="\t"))
    rows = [r for r in rows if r["processing_baseline"] == "05.10" and URL_RE.fullmatch(r["url"])
            and abs(float(r["centroid_lat"])) <= 72]
    best: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (abs(float(r["snow_ice_percentage"]) - 50), float(r["cloud_cover"]), r["datetime"])):
        best.setdefault(r["grid_code"], r)
    cells: dict[tuple[int, int], list[dict]] = {}
    for r in best.values():
        key = (int(float(r["centroid_lat"]) // 10 * 10), int(float(r["centroid_lon"]) // 20 * 20))
        cells.setdefault(key, []).append(r)
    chosen = []
    for key in sorted(cells, key=lambda k: (-len(cells[k]), k)):
        tiles = cells[key]
        if len(tiles) < 3:
            continue
        tiles.sort(key=lambda r: (abs(float(r["snow_ice_percentage"]) - 50), float(r["cloud_cover"]), r["item_id"]))
        picks = []
        for r in tiles[:4]:
            hp = os.path.join(probe_dir, r["item_id"] + ".head")
            if not os.path.exists(hp):
                subprocess.run(["curl", "-fsS", "--max-time", "60", "--retry", "3", "-r", "0-4095", "-o", hp, r["url"]], check=True)
            st = header_stats(hp)
            v = st["VALID_PERCENT"] / 100.0
            r = dict(r, hdr_nonzero_fraction=f"{v:.4f}", hdr_nonzero_mean=f"{st['MEAN']:.3f}", cell=f"{key[0]}_{key[1]}")
            print(f"cell={key} {r['item_id']} snow={float(r['snow_ice_percentage']):.1f} v={v:.3f} mean={st['MEAN']:.1f}", file=sys.stderr)
            if 0.30 <= v <= 0.75:
                picks.append(r)
        if picks:
            picks.sort(key=lambda r: (abs(float(r["hdr_nonzero_fraction"]) - 0.5), r["item_id"]))
            chosen.append(picks[0])
        if len(chosen) == N_SCENES:
            break
    chosen.sort(key=lambda r: r["item_id"])
    cols = ["item_id", "grid_code", "datetime", "platform", "processing_baseline", "centroid_lat", "centroid_lon",
            "cloud_cover", "snow_ice_percentage", "hdr_nonzero_fraction", "hdr_nonzero_mean", "cell",
            "size_bytes", "sha256", "url"]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in chosen:
            fh.write("\t".join(str(r[c]) for c in cols) + "\n")
    print(f"selected {len(chosen)} scenes bytes={sum(int(r['size_bytes']) for r in chosen)}", file=sys.stderr)


if __name__ == "__main__":
    main()
