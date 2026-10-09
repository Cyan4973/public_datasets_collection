#!/usr/bin/env python3
"""Document how the pinned scene list in sources.tsv was resolved.

Not run by download.sh or build.sh. It pages through the Earth Search STAC
API (sentinel-2-c1-l2a collection only) with keyset pagination, using curl
for network I/O, and writes every matching item as one TSV row:

    python3 -I discover.py OUT.tsv

Query (fixed): datetime 2024-03-01..2024-04-30, eo:cloud_cover < 15,
s2:nodata_pixel_percentage == 0, 25 <= s2:snow_ice_percentage <= 75.
select.py then applies the deterministic one-scene-per-tile rule.
"""
from __future__ import annotations

import json
import subprocess
import sys

SEARCH = "https://earth-search.aws.element84.com/v1/search"
BODY = {
    "collections": ["sentinel-2-c1-l2a"],
    "datetime": "2024-03-01T00:00:00Z/2024-04-30T23:59:59Z",
    "limit": 200,
    "query": {
        "eo:cloud_cover": {"lt": 15},
        "s2:nodata_pixel_percentage": {"eq": 0},
        "s2:snow_ice_percentage": {"gte": 25, "lte": 75},
    },
    "fields": {"include": ["id", "properties", "assets.snow"], "exclude": ["geometry", "links"]},
}
COLS = [
    "item_id", "grid_code", "datetime", "platform", "processing_baseline", "centroid_lat",
    "centroid_lon", "epsg", "cloud_cover", "snow_ice_percentage", "nodata_pixel_percentage",
    "size_bytes", "sha256", "url",
]


def post(body: dict) -> dict:
    out = subprocess.run(
        ["curl", "-fsS", "--max-time", "120", "--retry", "5", "--retry-delay", "5", "-X", "POST", SEARCH,
         "-H", "Content-Type: application/json", "-d", json.dumps(body)],
        check=True, capture_output=True,
    ).stdout
    return json.loads(out)


def main() -> None:
    out_path = sys.argv[1]
    body = dict(BODY)
    rows = []
    while True:
        page = post(body)
        for f in page["features"]:
            p = f["properties"]
            snow = f["assets"]["snow"]
            mh = snow["file:checksum"]
            assert mh.startswith("1220") and len(mh) == 68, mh
            rows.append({
                "item_id": f["id"], "grid_code": p["grid:code"], "datetime": p["datetime"],
                "platform": p["platform"], "processing_baseline": p["s2:processing_baseline"],
                "centroid_lat": p["proj:centroid"]["lat"], "centroid_lon": p["proj:centroid"]["lon"],
                "epsg": p["proj:epsg"], "cloud_cover": p["eo:cloud_cover"],
                "snow_ice_percentage": p["s2:snow_ice_percentage"],
                "nodata_pixel_percentage": p["s2:nodata_pixel_percentage"],
                "size_bytes": snow["file:size"], "sha256": mh[4:], "url": snow["href"],
            })
        nxt = [l for l in page.get("links", []) if l.get("rel") == "next"]
        print(f"page items={len(page['features'])} total={len(rows)}", file=sys.stderr)
        if not nxt or not page["features"]:
            break
        body = dict(BODY)
        body["next"] = nxt[0]["body"]["next"]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(COLS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in COLS) + "\n")
    print(f"wrote {len(rows)} rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
