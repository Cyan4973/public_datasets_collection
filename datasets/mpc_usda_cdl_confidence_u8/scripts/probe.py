#!/usr/bin/env python3
"""Author-time probe that resolved and screened the pinned tiles (not run by download/build).

Steps (run from a scratch directory, network via curl):
  list    page the Planetary Computer STAC /search for every usda-cdl item of
          type 'cropland' with datetime in 2021 (fields projection: id, bbox,
          proj:transform, assets.confidence.href) -> items_2021.tsv
  screen  for candidate tiles inside six agricultural region boxes, fetch the
          COG header with a range request plus four full-resolution 512x512
          primary tiles (grid positions (1,1), (1,4), (4,1), (4,4) of the 6x6
          tile grid) and record zero share, share of 100, distinct values and
          mean over those 1,048,576 sampled pixels -> screen.tsv.
          The COG overviews are average-resampled (Iowa 163905_2182575: share
          of 100 is 0.694 at full resolution but 0.247 in the 375x375
          overview), so overviews are NOT used for screening.
  pin     select tiles per region from screen.tsv and HEAD each confidence
          blob for Content-Length and Content-MD5 -> sources.tsv

Usage: probe.py list OUT.tsv | screen ITEMS.tsv OUT.tsv | pin SCREEN.tsv OUT.tsv
"""
from __future__ import annotations

import base64
import collections
import json
import os
import subprocess
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdl_cog  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/landcoverdata/usda-cdl"

# lon_min, lat_min, lon_max, lat_max: tile bbox must lie fully inside
REGIONS = {
    "corn_belt": (-96.5, 39.0, -84.0, 44.5),        # IA, IL, IN, OH, S MN
    "plains_wheat": (-102.0, 35.0, -96.5, 41.0),    # KS, OK, S NE winter wheat
    "northern_plains": (-104.0, 45.0, -96.0, 49.0), # ND, SD, MT spring wheat / Red River
    "delta": (-92.5, 31.0, -89.5, 36.5),            # AR, MS, NE LA cotton/rice/soy
    "central_valley": (-122.6, 35.0, -118.8, 40.2), # CA Sacramento + San Joaquin
    "palouse_columbia": (-120.5, 45.5, -116.5, 47.8),  # WA/ID Palouse + Columbia Basin
    "southeast": (-86.0, 30.8, -77.0, 36.0),        # GA, AL, SC, NC coastal plain
}
CANDIDATES_PER_REGION = 18
SAMPLE_TILES = [(1, 1), (1, 4), (4, 1), (4, 4)]


def curl(args: list[str]) -> bytes:
    return subprocess.run(["curl", "-fsS", "--retry", "5", "--retry-all-errors", "--max-time", "120", *args],
                          check=True, capture_output=True).stdout


def sas_token() -> str:
    return json.loads(curl([SAS]))["token"].lstrip("?")


def cmd_list(out_path: str) -> None:
    body = {
        "collections": ["usda-cdl"], "limit": 1000,
        "query": {"usda_cdl:type": {"eq": "cropland"}},
        "datetime": "2021-01-01T00:00:00Z/2021-12-31T23:59:59Z",
        "fields": {"include": ["id", "bbox", "assets.confidence.href", "properties"], "exclude": ["links", "geometry"]},
    }
    rows = []
    while True:
        page = json.loads(curl(["-X", "POST", STAC, "-H", "Content-Type: application/json", "-d", json.dumps(body)]))
        for f in page["features"]:
            p = f["properties"]
            assert p["usda_cdl:type"] == "cropland" and p["start_datetime"].startswith("2021-")
            assert p["proj:shape"] == [3000, 3000] and p["proj:epsg"] == 5070
            href = f["assets"]["confidence"]["href"]
            rows.append((f["id"], *[f"{v:.6f}" for v in f["bbox"]], int(p["proj:transform"][2]), int(p["proj:transform"][5]), href))
        nxt = [link for link in page["links"] if link["rel"] == "next"]
        if not nxt:
            break
        body = nxt[0]["body"]
    with open(out_path, "w") as fh:
        fh.write("item_id\tlon_min\tlat_min\tlon_max\tlat_max\tx_min\ty_max\thref\n")
        for r in sorted(rows):
            fh.write("\t".join(map(str, r)) + "\n")
    print(f"items={len(rows)}")


def region_candidates(items_path: str) -> list[tuple[str, dict]]:
    with open(items_path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows = [dict(zip(header, line.rstrip("\n").split("\t"))) for line in fh]
    out = []
    for region, (x0, y0, x1, y1) in REGIONS.items():
        inside = [r for r in rows if float(r["lon_min"]) >= x0 and float(r["lon_max"]) <= x1
                  and float(r["lat_min"]) >= y0 and float(r["lat_max"]) <= y1]
        inside.sort(key=lambda r: (int(r["x_min"]), int(r["y_max"])))
        n = len(inside)
        k = min(CANDIDATES_PER_REGION, n)
        picks = [inside[(i * n) // k] for i in range(k)] if k else []
        out += [(region, r) for r in picks]
        print(f"region={region} tiles_inside={n} candidates={k}", file=sys.stderr)
    return out


def cmd_screen(items_path: str, out_path: str) -> None:
    token = sas_token()
    done = set()
    if os.path.exists(out_path):
        with open(out_path) as fh:
            done = {line.split("\t")[1] for line in fh if not line.startswith("region\t")}
    else:
        with open(out_path, "w") as fh:
            fh.write("region\titem_id\tlon_min\tlat_min\tlon_max\tlat_max\tsampled\tzero_share\tshare100\tdistinct\tmean_nonzero\thref\n")
    for region, r in region_candidates(items_path):
        if r["item_id"] in done:
            continue
        url = f"{r['href']}?{token}"
        head = curl(["-r", "0-16383", url])
        ifds = cdl_cog.parse_ifds(head, allow_truncated=True)
        prim = cdl_cog.check_primary(ifds)
        offs, cnts = prim[324], prim[325]
        hist: collections.Counter = collections.Counter()
        for ty, tx in SAMPLE_TILES:
            k = ty * 6 + tx
            raw = zlib.decompress(curl(["-r", f"{offs[k]}-{offs[k] + cnts[k] - 1}", url]))
            assert len(raw) == 512 * 512
            hist.update(raw)
        n = sum(hist.values())
        nz = n - hist[0]
        mean = sum(v * c for v, c in hist.items()) / nz if nz else 0.0
        assert max(hist) <= 100, (r["item_id"], max(hist))
        line = [region, r["item_id"], r["lon_min"], r["lat_min"], r["lon_max"], r["lat_max"], n,
                f"{hist[0] / n:.4f}", f"{hist[100] / n:.4f}", len(hist), f"{mean:.2f}", r["href"]]
        with open(out_path, "a") as fh:
            fh.write("\t".join(map(str, line)) + "\n")
        print("\t".join(map(str, line[:11])), file=sys.stderr)


def cmd_pin(screen_path: str, out_path: str, per_region: int = 8,
            max_zero: float = 0.02, max_100: float = 0.70) -> None:
    with open(screen_path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows = [dict(zip(header, line.rstrip("\n").split("\t"))) for line in fh]
    token = sas_token()
    pinned = []
    for region in REGIONS:
        ok = [r for r in rows if r["region"] == region and float(r["zero_share"]) <= max_zero
              and float(r["share100"]) <= max_100]
        ok.sort(key=lambda r: r["item_id"])
        n = len(ok)
        k = min(per_region, n)
        picks = [ok[(i * n) // k] for i in range(k)] if k else []
        print(f"region={region} eligible={n} pinned={k}", file=sys.stderr)
        for r in picks:
            hdr = curl(["-I", f"{r['href']}?{token}"]).decode("latin-1")
            fields = {}
            for line in hdr.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    fields[key.strip().lower()] = val.strip()
            size = int(fields["content-length"])
            md5 = base64.b64decode(fields["content-md5"]).hex()
            pinned.append((region, r["item_id"], r["lon_min"], r["lat_min"], r["lon_max"], r["lat_max"],
                           r["zero_share"], r["share100"], size, md5, r["href"]))
    with open(out_path, "w") as fh:
        fh.write("region\titem_id\tlon_min\tlat_min\tlon_max\tlat_max\tscreen_zero_share\tscreen_share100\tsize_bytes\tcontent_md5_hex\turl\n")
        for p in pinned:
            fh.write("\t".join(map(str, p)) + "\n")
    print(f"pinned={len(pinned)} bytes={sum(p[8] for p in pinned)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list(sys.argv[2])
    elif cmd == "screen":
        cmd_screen(sys.argv[2], sys.argv[3])
    elif cmd == "pin":
        cmd_pin(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
