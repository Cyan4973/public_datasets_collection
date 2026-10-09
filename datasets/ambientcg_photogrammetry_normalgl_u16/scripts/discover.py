#!/usr/bin/env python3
"""Rebuild scripts/assets.tsv from discover.sh fetches (documentation of how the pin was made).

Inputs (under --work):
  api_page_<offset>.json   ambientCG v2 full_json pages (type=Material, sort=Alphabet)
  tails/<asset>.tail       last 16384 bytes of <asset>_1K-PNG.zip
  heads/<asset>.head       local file header + first bytes of the NormalGL member
Modes:
  ranges  print "<asset> <zip_size>" for every PBRPhotogrammetry asset, then after
          tails exist, "<asset> <head_start> <head_end>" with --heads
  table   emit assets.tsv on stdout
"""
from __future__ import annotations

import argparse
import glob
import json
import struct
import sys
from pathlib import Path


def photogrammetry_assets(work: Path) -> dict[str, dict]:
    assets: dict[str, dict] = {}
    total = None
    for page in sorted(glob.glob(str(work / "api_page_*.json"))):
        doc = json.loads(Path(page).read_text(encoding="utf-8"))
        total = doc["numberOfResults"]
        for asset in doc["foundAssets"]:
            # creationMethod is the reliable field; creationMethodName is mislabelled in the API.
            if asset["creationMethod"] == "PBRPhotogrammetry":
                assets[asset["assetId"]] = asset
    seen = sum(len(json.loads(Path(p).read_text(encoding="utf-8"))["foundAssets"])
               for p in glob.glob(str(work / "api_page_*.json")))
    if total is None or seen != total:
        raise SystemExit(f"API paging incomplete: saw {seen} of {total}")
    return dict(sorted(assets.items()))


def zip_1k_png(asset: dict) -> dict:
    downloads = asset["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
    hits = [d for d in downloads if d["attribute"] == "1K-PNG"]
    if len(hits) != 1:
        raise SystemExit(f"{asset['assetId']}: expected one 1K-PNG zip")
    return hits[0]


def normalgl_entry(asset_id: str, zip_size: int, tail: bytes) -> dict:
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit(f"{asset_id}: no EOCD in tail")
    _sig, _d, _cd, _n1, count, _cdsize, cdoff, _cl = struct.unpack_from("<IHHHHIIH", tail, eocd)
    pos = cdoff - (zip_size - len(tail))
    if pos < 0:
        raise SystemExit(f"{asset_id}: central directory not inside tail")
    wanted = f"{asset_id}_1K-PNG_NormalGL.png"
    found = None
    for _ in range(count):
        fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, pos)
        if fields[0] != 0x02014B50:
            raise SystemExit(f"{asset_id}: bad central directory entry")
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        name = tail[pos + 46:pos + 46 + name_len].decode()
        method, flags = fields[4], fields[3]
        if method != 0 or flags & 0x0009:
            raise SystemExit(f"{asset_id}: member {name} not plain STORED (method {method} flags {flags})")
        if name == wanted:
            found = {"crc": fields[7], "csize": fields[8], "usize": fields[9], "lho": fields[16]}
        pos += 46 + name_len + extra_len + comment_len
    if not found or found["csize"] != found["usize"]:
        raise SystemExit(f"{asset_id}: NormalGL member missing or sizes differ")
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["assets", "heads", "table"])
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    assets = photogrammetry_assets(args.work)
    if args.mode == "assets":
        for asset_id, asset in assets.items():
            print(asset_id, zip_1k_png(asset)["size"])
        return
    rows = []
    for asset_id, asset in assets.items():
        zip_size = int(zip_1k_png(asset)["size"])
        entry = normalgl_entry(asset_id, zip_size, (args.work / "tails" / f"{asset_id}.tail").read_bytes())
        if args.mode == "heads":
            print(asset_id, entry["lho"], entry["lho"] + 30 + len(asset_id) + 40 + 511)
            continue
        head = (args.work / "heads" / f"{asset_id}.head").read_bytes()
        sig, _v, _f, method, _t, _d, crc, csize, _u, name_len, extra_len = struct.unpack_from("<IHHHHHIIIHH", head, 0)
        if sig != 0x04034B50 or method != 0 or crc != entry["crc"] or csize != entry["csize"]:
            raise SystemExit(f"{asset_id}: local header disagrees with central directory")
        data_off = 30 + name_len + extra_len
        png = head[data_off:data_off + 33]
        if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
            raise SystemExit(f"{asset_id}: member is not a PNG")
        width, height, depth, color = struct.unpack(">IIBB", png[16:26])
        if depth != 16 or color not in (2, 6):
            print(f"skip {asset_id}: bit depth {depth} colour type {color}", file=sys.stderr)
            continue
        rows.append([asset_id, asset["releaseDate"][:10], asset["displayCategory"], zip_size,
                     entry["lho"], entry["lho"] + data_off, entry["csize"], f"{entry['crc']:08x}",
                     width, height, color])
    print("\t".join(["asset_id", "selected", "release_date", "display_category", "zip_size",
                     "member_lho", "member_data_offset", "member_size", "member_crc32",
                     "width", "height", "color_type"]))
    for index, row in enumerate(rows):
        print("\t".join(map(str, [row[0], 1 if index % 3 == 0 else 0] + row[1:])))


if __name__ == "__main__":
    main()
