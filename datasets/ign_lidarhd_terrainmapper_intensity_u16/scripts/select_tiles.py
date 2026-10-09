#!/usr/bin/env python3
"""Deterministic tile selection for ign_lidarhd_terrainmapper_intensity_u16.

Inputs (fetched by discover.sh): the WFS metadata JSON for mission 21LHD2GO and
the Atom feed pages of delivery NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22.

Rule:
  * keep only tiles of mission 21LHD2GO whose capteur is exactly
    '["Leica TerrainMapper:90560"]', classification IGN_AUTO_V5, edition
    2025-09-22 and whose url_npl lies in the pinned delivery;
  * 12 anchors on an interior grid of the 50 km x 50 km block (x NW-corner km
    442/454/466/478, y 6342/6358/6374): at least 6 km from every block edge,
    so no edge or partial tiles;
  * for each anchor take the anchor tile when it qualifies, otherwise the
    nearest qualifying tile (Chebyshev ring, then dy, then dx). Qualifying:
    15,000,000 <= nombre_points <= 32,000,000 and an Atom entry with length
    <= 230,000,000 bytes and an MD5;
  * output sources.tsv sorted by tile name.
"""
import argparse
import glob
import json
import os
import re

MISSION = "21LHD2GO"
SENSOR = '["Leica TerrainMapper:90560"]'
DELIVERY = "NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22"
XS = (442, 454, 466, 478)
YS = (6342, 6358, 6374)
MIN_POINTS, MAX_POINTS = 15_000_000, 32_000_000
MAX_BYTES = 230_000_000
ENTRY = re.compile(
    r'<link href="([^"]+)" rel="alternate" type="application/octet-stream" gpf_dl:length="(\d+)"/>'
    r'\s*<id>[^<]*</id>\s*<content>([0-9a-f]{32})</content>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wfs", required=True)
    ap.add_argument("--atom-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    feats = json.load(open(a.wfs, encoding="utf-8"))
    if feats.get("numberMatched") != len(feats["features"]):
        raise SystemExit("WFS response is paged/incomplete")
    atom = {}
    for f in sorted(glob.glob(os.path.join(a.atom_dir, "*.xml"))):
        for m in ENTRY.finditer(open(f, encoding="utf-8").read()):
            atom[m.group(1)] = (int(m.group(2)), m.group(3))
    tiles = {}
    other_sensor = 0
    for feat in feats["features"]:
        p = feat["properties"]
        if p["code_mission"] != MISSION:
            continue
        if p["capteur"] != SENSOR:
            other_sensor += 1
            continue
        if p["procede_classement"] != "IGN_AUTO_V5" or p["date_edition"] != "2025-09-22Z":
            continue
        if f"/{DELIVERY}/" not in p["url_npl"]:
            continue
        x, y = (int(v) for v in p["coordonnees_nw"].split("-"))
        tiles[(x, y)] = p
    print(f"mission tiles={len(feats['features'])} sensor_ok={len(tiles)} other_sensor={other_sensor} "
          f"atom_entries={len(atom)}")
    xs = sorted({k[0] for k in tiles})
    ys = sorted({k[1] for k in tiles})
    print(f"block x {xs[0]}..{xs[-1]} y {ys[0]}..{ys[-1]}")

    def qualifies(key):
        p = tiles.get(key)
        if p is None or not (MIN_POINTS <= p["nombre_points"] <= MAX_POINTS):
            return False
        ent = atom.get(p["url_npl"])
        return ent is not None and ent[0] <= MAX_BYTES

    chosen = []
    for ay in YS:
        for ax in XS:
            pick = None
            for ring in range(0, 4):
                cands = [(dy, dx) for dy in range(-ring, ring + 1) for dx in range(-ring, ring + 1)
                         if max(abs(dy), abs(dx)) == ring]
                for dy, dx in sorted(cands):
                    if qualifies((ax + dx, ay + dy)):
                        pick = (ax + dx, ay + dy)
                        break
                if pick:
                    break
            if pick is None:
                raise SystemExit(f"no qualifying tile near anchor {ax}-{ay}")
            if pick in chosen:
                raise SystemExit(f"duplicate pick {pick}")
            chosen.append(pick)
            p = tiles[pick]
            print(f"anchor {ax}-{ay} -> {pick[0]:04d}-{pick[1]} points={p['nombre_points']} "
                  f"bytes={atom[p['url_npl']][0]}")
    rows = []
    for key in chosen:
        p = tiles[key]
        size, md5 = atom[p["url_npl"]]
        name = p["url_npl"].rsplit("/", 1)[1]
        rows.append((name, p["coordonnees_nw"], str(p["nombre_points"]), str(size), md5,
                     p["date_debut_acquisition"].rstrip("Z"), p["date_fin_acquisition"].rstrip("Z"),
                     p["url_npl"]))
    rows.sort()
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("tile\tcoordonnees_nw\tnombre_points\tsize_bytes\tmd5\t"
                 "date_debut_acquisition\tdate_fin_acquisition\turl\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    total_b = sum(int(r[3]) for r in rows)
    total_p = sum(int(r[2]) for r in rows)
    print(f"selected tiles={len(rows)} download_bytes={total_b} points={total_p} "
          f"primary_bytes={2 * total_p}")


if __name__ == "__main__":
    main()
