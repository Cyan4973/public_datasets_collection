#!/usr/bin/env python3
"""Resolve the pinned tile list (sources.tsv) for the SHOALS-1000T 8526 recipe.

Inputs (fetched with curl by discover.sh, never by this script):
  listing.xml      S3 ListObjectsV2 response for prefix laz/geoid18/8526/
  stac_items.json  laz/geoid18/8526/stac/noaa_copc_item_collection_m8526.json

Output: a TSV with one row per *.copc.laz object directly under the prefix
(the 8525 Riegl VQ-820-G project lives under a different prefix and is never
listed). Columns: key, filename, size_bytes, md5 (the single-part S3 ETag),
last_modified, point_count (STAC pc:count), stac_gps_min, stac_gps_max,
stac_gps_avg (STAC pc:statistics GpsTime, rounded by the publisher), sha256
("-" here; filled in after the first verified download).
"""
import json
import re
import sys

PREFIX = "laz/geoid18/8526/"


def main(listing_path: str, stac_path: str, out_path: str) -> int:
    xml = open(listing_path, encoding="utf-8").read()
    if "<IsTruncated>false</IsTruncated>" not in xml:
        raise SystemExit("listing is truncated; paginate before pinning")
    objects = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", xml, re.S):
        key = re.search(r"<Key>(.*?)</Key>", block).group(1)
        etag = re.search(r"<ETag>(.*?)</ETag>", block).group(1).replace("&quot;", "").strip('"')
        size = int(re.search(r"<Size>(\d+)</Size>", block).group(1))
        modified = re.search(r"<LastModified>(.*?)</LastModified>", block).group(1)
        if not key.startswith(PREFIX) or "/" in key[len(PREFIX):]:
            continue
        if not key.endswith(".copc.laz"):
            continue
        if not re.fullmatch(r"[0-9a-f]{32}", etag):
            raise SystemExit(f"{key}: ETag {etag} is not a single-part MD5")
        objects.append((key, size, etag, modified))
    stac = {}
    for feature in json.load(open(stac_path, encoding="utf-8"))["features"]:
        stats = {s["name"]: s for s in feature["properties"]["pc:statistics"]}
        stac[feature["id"] + ".laz"] = (
            int(feature["properties"]["pc:count"]),
            stats["GpsTime"]["minimum"],
            stats["GpsTime"]["maximum"],
            stats["GpsTime"]["average"],
        )
    objects.sort()
    names = [key[len(PREFIX):] for key, _, _, _ in objects]
    if sorted(stac) != names:
        raise SystemExit("STAC items and S3 listing disagree on the tile set")
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("key\tfilename\tsize_bytes\tmd5\tlast_modified\tpoint_count\t"
                  "stac_gps_min\tstac_gps_max\tstac_gps_avg\tsha256\n")
        for (key, size, etag, modified), name in zip(objects, names):
            count, gmin, gmax, gavg = stac[name]
            out.write(f"{key}\t{name}\t{size}\t{etag}\t{modified}\t{count}\t"
                      f"{gmin!r}\t{gmax!r}\t{gavg!r}\t-\n")
    print(f"tiles={len(objects)} bytes={sum(o[1] for o in objects)} "
          f"points={sum(stac[n][0] for n in names)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: discover_sources.py listing.xml stac_items.json out.tsv")
    raise SystemExit(main(*sys.argv[1:]))
