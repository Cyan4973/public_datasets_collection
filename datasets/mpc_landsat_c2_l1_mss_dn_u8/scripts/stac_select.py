#!/usr/bin/env python3
"""JSON helper for discover.sh and download.sh (no network I/O; curl does all requests).

Subcommands:
  body <wrs_path> <wrs_row>
      Print the STAC /search POST body for one WRS-2 path/row.
  next <previous_body.json> <page.json>
      Print the body of the next page (POST) or "GET <href>", or nothing.
  pick <page.json> [<page.json> ...]
      Apply the scene rule to every feature and print one TSV line for the
      chosen item, or nothing when no item qualifies:
        item_id, product_id, datetime, cloud_cover, sun_elevation, sun_azimuth,
        proj_rows, proj_cols, candidates, then <asset>=<href> for the five
        assets green, red, nir08, nir09, mtl.json
  sas <response.json>
      Print the anonymous SAS query string from a Planetary Computer
      /api/sas/v1/token response (fails when no signature is present).

Scene rule (deterministic), per fixed WRS-2 path/row:
  - collection landsat-c2-l1, platform landsat-5, instruments == ["mss"],
    landsat:correction L1TP, landsat:collection_category T1,
    landsat:collection_number 02, landsat:wrs_type 2 (all requested
    server-side where the API allows and re-checked here)
  - item id LM05_L1TP_<path><row>_<YYYYMMDD>_02_T1
  - datetime within 1984-03-01 .. 1993-12-31 (the original Landsat-5 MSS
    era; the 2012-2013 MSS re-activation is excluded)
  - 0 <= eo:cloud_cover < 5 and view:sun_elevation > 30
  - assets green/red/nir08/nir09 (B1..B4) and mtl.json present with hrefs on
    landsateuwest.blob.core.windows.net/landsat-c2/level-1/standard/mss/
  - order by (eo:cloud_cover, -view:sun_elevation, datetime, id), take first.
"""
from __future__ import annotations

import json
import re
import sys

COLLECTION = "landsat-c2-l1"
DATETIME = "1984-03-01T00:00:00Z/1993-12-31T23:59:59Z"
DATE_MIN, DATE_MAX = "1984-03-01", "1993-12-31"
CLOUD_MAX = 5.0
SUN_ELEVATION_MIN = 30.0
PAGE_LIMIT = 100
ASSETS = [("green", "B1"), ("red", "B2"), ("nir08", "B3"), ("nir09", "B4"), ("mtl.json", "MTL")]
HREF_RE = re.compile(
    r"^https://landsateuwest\.blob\.core\.windows\.net/landsat-c2/level-1/standard/mss/"
    r"(?P<year>\d{4})/(?P<path>\d{3})/(?P<row>\d{3})/(?P<pid>LM05_L1TP_\d{6}_\d{8}_\d{8}_02_T1)/"
    r"(?P=pid)_(?P<suffix>B[1-4]\.TIF|MTL\.json)$"
)


def cmd_body(args: list[str]) -> None:
    path, row = args
    if not (re.fullmatch(r"\d{3}", path) and re.fullmatch(r"\d{3}", row)):
        raise SystemExit(f"FATAL: bad WRS-2 path/row {path}/{row}")
    body = {
        "collections": [COLLECTION],
        "datetime": DATETIME,
        "query": {
            "platform": {"eq": "landsat-5"},
            "landsat:correction": {"eq": "L1TP"},
            "landsat:collection_category": {"eq": "T1"},
            "landsat:wrs_path": {"eq": path},
            "landsat:wrs_row": {"eq": row},
            "eo:cloud_cover": {"gte": 0, "lt": CLOUD_MAX},
        },
        "limit": PAGE_LIMIT,
    }
    print(json.dumps(body, separators=(",", ":")))


def cmd_next(args: list[str]) -> None:
    previous = json.load(open(args[0], encoding="utf-8"))
    page = json.load(open(args[1], encoding="utf-8"))
    for link in page.get("links", []):
        if link.get("rel") != "next":
            continue
        method = str(link.get("method", "GET")).upper()
        if method == "POST" and isinstance(link.get("body"), dict):
            body = dict(previous)
            body.update(link["body"])
            print(json.dumps(body, separators=(",", ":")))
        else:
            print("GET " + link["href"])
        return


def _num(props: dict, key: str, item_id: str) -> float:
    if key not in props or props[key] is None:
        raise SystemExit(f"FATAL: item {item_id} lacks property {key!r}; present: {', '.join(sorted(props))}")
    return float(props[key])


def cmd_pick(args: list[str]) -> None:
    candidates = []
    seen = set()
    for path in args:
        page = json.load(open(path, encoding="utf-8"))
        if page.get("type") != "FeatureCollection":
            raise SystemExit(f"FATAL: {path} is not a STAC FeatureCollection")
        for feature in page.get("features", []):
            item_id = feature["id"]
            if item_id in seen:
                continue
            seen.add(item_id)
            if feature.get("collection") not in (None, COLLECTION):
                raise SystemExit(f"FATAL: item {item_id} from collection {feature.get('collection')!r}")
            p = feature.get("properties", {})
            wrs = f"{p.get('landsat:wrs_path')}{p.get('landsat:wrs_row')}"
            if not re.fullmatch(rf"LM05_L1TP_{wrs}_\d{{8}}_02_T1", item_id):
                continue
            if (p.get("platform") != "landsat-5" or p.get("instruments") != ["mss"]
                    or p.get("landsat:correction") != "L1TP" or p.get("landsat:collection_category") != "T1"
                    or p.get("landsat:collection_number") != "02" or str(p.get("landsat:wrs_type")) != "2"):
                continue
            when = str(p.get("datetime", ""))
            if not (DATE_MIN <= when[:10] <= DATE_MAX):
                continue
            cloud = _num(p, "eo:cloud_cover", item_id)
            sun = _num(p, "view:sun_elevation", item_id)
            if not (0.0 <= cloud < CLOUD_MAX) or sun <= SUN_ELEVATION_MIN:
                continue
            assets = feature.get("assets", {})
            hrefs = []
            product_ids = set()
            ok = True
            for key, suffix in ASSETS:
                href = str(assets.get(key, {}).get("href", "")).split("?", 1)[0]
                m = HREF_RE.match(href)
                if not m:
                    ok = False
                    break
                want = f"{suffix}.TIF" if suffix.startswith("B") else "MTL.json"
                if m.group("suffix") != want or m.group("path") + m.group("row") != wrs:
                    raise SystemExit(f"FATAL: asset {key} of {item_id} has unexpected href {href}")
                product_ids.add(m.group("pid"))
                hrefs.append(f"{key}={href}")
            if not ok:
                continue
            if len(product_ids) != 1:
                raise SystemExit(f"FATAL: assets of {item_id} point to different products {product_ids}")
            pid = product_ids.pop()
            if pid[:25] != item_id[:25] or not pid.endswith("_02_T1"):
                raise SystemExit(f"FATAL: product id {pid} does not match item {item_id}")
            shape = p.get("proj:shape") or [0, 0]
            azimuth = p.get("view:sun_azimuth")
            candidates.append(((cloud, -sun, when, item_id),
                               [item_id, pid, when, cloud, sun, "NA" if azimuth is None else azimuth,
                                int(shape[0]), int(shape[1])] + hrefs))
    if not candidates:
        return
    candidates.sort(key=lambda c: c[0])
    row = candidates[0][1]
    row.insert(8, len(candidates))
    print("\t".join(str(v) for v in row))


def cmd_sas(args: list[str]) -> None:
    doc = json.load(open(args[0], encoding="utf-8"))
    value = str(doc.get("token", "")).lstrip("?")
    if not value or "sig=" not in value:
        raise SystemExit("FATAL: Planetary Computer SAS response has no signature")
    print(value)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, args = argv[1], argv[2:]
    if cmd == "body" and len(args) == 2:
        cmd_body(args)
    elif cmd == "next" and len(args) == 2:
        cmd_next(args)
    elif cmd == "pick" and len(args) >= 1:
        cmd_pick(args)
    elif cmd == "sas" and len(args) == 1:
        cmd_sas(args)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
