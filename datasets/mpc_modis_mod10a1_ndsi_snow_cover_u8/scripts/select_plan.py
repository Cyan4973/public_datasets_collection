#!/usr/bin/env python3
"""Deterministic tile/date selection for mpc_modis_mod10a1_ndsi_snow_cover_u8.

Reads the probe table written by probe.py and writes the pinned download plan
(sources.tsv). verify.sh imports select() and re-derives the plan, so
sources.tsv must always equal select(probe table).

Rule (fixed before any download.sh run; see the revision note below):
  * candidate pool: every Terra MOD10A1.061 item in MODIS sinusoidal rows
    v02-v05 (about 30-70 N) on the 1st and 15th of each month from
    2023-12-01 to 2024-04-15 (the 2023/24 Northern-Hemisphere snow season);
  * keep an item when (a) its 300x300 overview estimate has at least 45%
    valid NDSI pixels (values 0..100), (b) the producer's header attribute
    SNOWCOVERPERCENT is at least 5, and (c) its header passed the structure
    and metadata checks;
  * no other filtering, ranking, capping, or hand-picking.

Why two different signals: the overview is GDAL-resampled, so averaging
snow-free land (0) with cloud (250) yields spurious 1..100 values and the
overview badly overestimates snow (one probe tile: estimate 7.9%, real
0.07%), while its valid-fraction estimate held up (0.535 vs 0.536).
SNOWCOVERPERCENT is computed by the MODAPS PGE from the full-resolution grid.
On fully snow-covered tiles it sums with QAPERCENTCLOUDCOVER.1 to about 100,
and three full-resolution spot checks with SNOWCOVERPERCENT = 5 measured
snow/land = 5.1%, 5.3%, 5.0% (land = all pixels except ocean 239 and inland
water 237). It is therefore percent of land pixels mapped as snow (1..100).

Revision note: the first version of this rule used the overview snow
estimate (>= 0.05) instead of (b). One full-resolution spot check (the
smallest pinned file, h11v05 2023-12-15) exposed the overestimate, and (b)
replaced it before any download run. The valid threshold was then set to
0.45 rather than 0.50 after inspecting the probe table: 0.50 kept 53 items
on 22 tiles and no European tile at all; 0.45 keeps 70 items on 28 tiles,
adding European Russia/Fennoscandia (h20v02, h20v03), the Balkans (h19v04),
more of Canada (h12v03) and Siberia (h24v03). No individual item was
added or removed by hand.

Usage: select_plan.py PROBE.tsv OUT_SOURCES.tsv
"""
from __future__ import annotations

import csv
import math
import sys

DATES = [
    "2023-12-01", "2023-12-15", "2024-01-01", "2024-01-15", "2024-02-01",
    "2024-02-15", "2024-03-01", "2024-03-15", "2024-04-01", "2024-04-15",
]
ROWS = {2, 3, 4, 5}
MIN_EST_VALID = 0.45
MIN_HDR_SNOW_PERCENT = 5
COLUMNS = [
    "date", "doy", "tile", "center_lat", "center_lon", "item_id", "production_datetime",
    "size_bytes", "content_md5_hex", "est_valid_fraction", "hdr_snow_cover_percent",
    "hdr_cloud_percent", "url",
]


def tile_center(tile: str) -> tuple[float, float]:
    """Center of a MODIS sinusoidal 10x10 degree tile (lat, lon in degrees)."""
    h, v = int(tile[1:3]), int(tile[4:6])
    lat = 85.0 - 10.0 * v
    lon = (h - 18 + 0.5) * 10.0 / math.cos(math.radians(lat))
    return lat, lon


def select(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    plan = []
    for r in candidates:
        if r["date"] not in DATES or int(r["tile"][4:6]) not in ROWS:
            continue
        if r["struct_ok"] != "1" or r["meta_ok"] != "1" or r["platform"] != "terra":
            continue
        if float(r["ov_valid"]) < MIN_EST_VALID or int(r["hdr_snowcoverpercent"]) < MIN_HDR_SNOW_PERCENT:
            continue
        lat, lon = tile_center(r["tile"])
        plan.append({
            "date": r["date"], "doy": r["doy"], "tile": r["tile"],
            "center_lat": f"{lat:.1f}", "center_lon": f"{lon:.1f}",
            "item_id": r["item_id"], "production_datetime": r["production_datetime"],
            "size_bytes": r["size_bytes"], "content_md5_hex": r["md5_hex"],
            "est_valid_fraction": r["ov_valid"], "hdr_snow_cover_percent": r["hdr_snowcoverpercent"],
            "hdr_cloud_percent": r["hdr_cloudpercent"],
            "url": r["href"],
        })
    plan.sort(key=lambda r: (r["date"], r["tile"]))
    return plan


def read_tsv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def main() -> None:
    probe_path, out_path = sys.argv[1], sys.argv[2]
    plan = select(read_tsv(probe_path))
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(plan)
    total = sum(int(r["size_bytes"]) for r in plan)
    print(f"selected {len(plan)} items, {len({r['tile'] for r in plan})} tiles, {total} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
