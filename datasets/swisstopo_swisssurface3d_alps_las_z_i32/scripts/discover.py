#!/usr/bin/env python3
"""Document and re-derive the pinned tile selection in sources.tsv.

Not called by download.sh. Run from a scratch directory:
  python3 -I discover.py --sources <recipe>/sources.tsv --workdir /tmp/x

Selection rule (probed 2026-10-08):
 1. STAC query collections/ch.swisstopo.swisssurface3d/items with
    bbox=7.85,46.40,8.15,46.60 (Bernese Oberland / Aletsch), all pages
    -> 647 items (398 from 2021, 224 from 2022, 25 from 2023).
 2. Keep swisssurface3d_2021_* items whose 1 km tile has no item from
    another year in the same query (drops the acquisition-block border tiles,
    which can be partial) -> 327 tiles.
 3. Range-GET the first 8 KiB of each zip, inflate the LAS header, and keep
    tiles with the uniform delivery profile: LAS 1.2, point format 1, 28-byte
    records, no VLRs, scale 0.01, Z offset 0, generating software las2las.
    This drops 2640-1153 and 2640-1154, which were produced by lasmerge -> 325.
 4. Sort by item id and take index floor(step*j + step/2), step = 325/15,
    j = 0..14: a deterministic, spatially spread selection of 15 tiles
    (955,570,404 bytes of int32 Z, under the 1 GB primary cap).
Network I/O uses curl (subprocess), as recipes must not depend on urllib.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import subprocess
import zlib
from pathlib import Path

STAC = (
    "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swisssurface3d/items"
    "?bbox=7.85,46.40,8.15,46.60&limit=100"
)
COUNT = 15


def curl(*args: str) -> bytes:
    return subprocess.check_output(["curl", "-sfL", "--max-time", "120", *args])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)

    items, url = [], STAC
    while url:
        page = json.loads(curl(url))
        items += page["features"]
        url = next((link["href"] for link in page["links"] if link["rel"] == "next"), None)
    by_tile: dict[str, list[str]] = {}
    for item in items:
        by_tile.setdefault(item["id"].split("_")[2], []).append(item["id"])
    candidates = sorted(
        item for item in (i["id"] for i in items)
        if item.startswith("swisssurface3d_2021_") and len(by_tile[item.split("_")[2]]) == 1
    )
    assets = {i["id"]: next(iter(i["assets"].items())) for i in items}
    eligible = []
    for item_id in candidates:
        head = curl("-r", "0-8191", assets[item_id][1]["href"])
        name_len, extra_len = struct.unpack_from("<HH", head, 26)
        las = zlib.decompressobj(-15).decompress(head[30 + name_len + extra_len:])
        hs, pofs, nvlr, pf, rl, _n = struct.unpack_from("<HIIBHI", las, 94)
        scale = struct.unpack_from("<3d", las, 131)
        oz = struct.unpack_from("<d", las, 171)[0]
        software = las[58:90].rstrip(b"\0").decode("ascii", "replace")
        if ((las[24], las[25]), hs, pofs, nvlr, pf, rl, scale, oz) == (
            (1, 2), 227, 227, 0, 1, 28, (0.01, 0.01, 0.01), 0.0
        ) and software.startswith("las2las"):
            eligible.append(item_id)
    step = len(eligible) / COUNT
    selected = [eligible[int(step * j + step / 2)] for j in range(COUNT)]
    with args.sources.open(newline="") as handle:
        pinned = [row["item_id"] for row in csv.DictReader(handle, delimiter="\t")]
    print(f"items={len(items)} candidates={len(candidates)} eligible={len(eligible)}")
    for item_id in selected:
        multihash = assets[item_id][1]["checksum:multihash"].lower()
        print(item_id, assets[item_id][0], multihash[4:])
    if selected != pinned:
        raise SystemExit("selection differs from sources.tsv (upstream catalogue changed)")
    print("selection matches sources.tsv")


if __name__ == "__main__":
    main()
