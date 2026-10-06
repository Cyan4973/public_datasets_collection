#!/usr/bin/env python3
"""JSON helper for discover.sh (no network I/O; curl does all requests).

Subcommands:
  body <west> <south> <east> <north> <start_iso> <end_iso>
      Print the STAC /search POST body for one region/window/year.
  next <previous_body.json> <page.json>
      Print the body of the next page (POST) or "GET <href>" (GET link), or
      nothing when the page has no rel=next link.
  pick <selected_ids.txt> <page.json> [<page.json> ...]
      Apply the scene rule to every feature of every page and print one TSV
      line for the chosen item, or nothing when no item qualifies:
        item_id, datetime, cloud_cover, sun_elevation, sun_azimuth, tir_href,
        candidates
  sas <response.json>
      Print the anonymous SAS query string from a Planetary Computer
      /api/sas/v1/token response (fails when no signature is present).

Scene rule (deterministic):
  - asset TIR present, href on astersa.blob.core.windows.net/aster/ ending
    in .TIR.tif
  - 0 <= eo:cloud_cover < 10 (also requested server-side)
  - view:sun_elevation > 20 (daytime acquisition; a missing property is fatal)
  - item not already chosen for another region/window
  - order by (eo:cloud_cover, datetime, id) and take the first.
"""
from __future__ import annotations

import json
import re
import sys

COLLECTION = "aster-l1t"
CLOUD_MAX = 10.0
SUN_ELEVATION_MIN = 20.0
PAGE_LIMIT = 100
HREF_RE = re.compile(r"^https://astersa\.blob\.core\.windows\.net/aster/images/L1T/\d{4}/\d{2}/\d{2}/AST_L1T_[0-9A-Za-z_]+\.TIR\.tif$")


def cmd_body(args: list[str]) -> None:
    west, south, east, north = (float(a) for a in args[:4])
    start, end = args[4], args[5]
    body = {
        "collections": [COLLECTION],
        "bbox": [west, south, east, north],
        "datetime": f"{start}/{end}",
        "query": {"eo:cloud_cover": {"gte": 0, "lt": CLOUD_MAX}},
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
        keys = ", ".join(sorted(props))
        raise SystemExit(f"FATAL: item {item_id} lacks property {key!r}; properties present: {keys}")
    return float(props[key])


def cmd_pick(args: list[str]) -> None:
    selected = set()
    try:
        selected = {line.strip() for line in open(args[0], encoding="utf-8") if line.strip()}
    except FileNotFoundError:
        pass
    candidates = []
    seen = set()
    for path in args[1:]:
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
            props = feature.get("properties", {})
            tir = feature.get("assets", {}).get("TIR")
            if not tir:
                continue
            href = str(tir.get("href", "")).split("?", 1)[0]
            if not HREF_RE.match(href):
                raise SystemExit(f"FATAL: unexpected TIR href for {item_id}: {href}")
            cloud = _num(props, "eo:cloud_cover", item_id)
            sun = _num(props, "view:sun_elevation", item_id)
            if not (0.0 <= cloud < CLOUD_MAX) or sun <= SUN_ELEVATION_MIN:
                continue
            if item_id in selected:
                continue
            azimuth = props.get("view:sun_azimuth")
            candidates.append((cloud, props["datetime"], item_id, sun, "NA" if azimuth is None else azimuth, href))
    if not candidates:
        return
    candidates.sort()
    cloud, when, item_id, sun, azimuth, href = candidates[0]
    print("\t".join(str(v) for v in (item_id, when, cloud, sun, azimuth, href, len(candidates))))


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
    if cmd == "body" and len(args) == 6:
        cmd_body(args)
    elif cmd == "next" and len(args) == 2:
        cmd_next(args)
    elif cmd == "pick" and len(args) >= 2:
        cmd_pick(args)
    elif cmd == "sas" and len(args) == 1:
        cmd_sas(args)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
