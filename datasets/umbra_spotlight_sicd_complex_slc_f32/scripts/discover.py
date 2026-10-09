#!/usr/bin/env python3
"""Metadata-only discovery that produced sources.tsv (not run by download.sh).

1. List s3://umbra-open-data-catalog/sar-data/tasks/ anonymously (list-type=2,
   continuation tokens) with curl.
2. Sort every *_SICD.nitf by object size ascending (ties by key).
3. For each in turn, range-GET the first 4096 bytes and the last 65536 bytes,
   parse the NITF file header, the image subheader and the SICD XML DES, and
   keep the product only if sicd.assert_regime() passes (processor 0.6.x,
   SPOTLIGHT, MONOSTATIC, PFA, RE32F_IM32F, 2-band I/Q, single block, ...).
4. Skip a product whose scene centre point (SCP) lies within 0.05 deg in both
   latitude and longitude of an already selected product (same imaged scene).
5. Stop at the first conforming, non-duplicate product that would push the
   cumulative image-data bytes over 1,000,000,000.
6. For each selected product fetch the sibling *_METADATA.json (~7 KB) for the
   polarization / geometry fields that the SICD XML leaves as OTHER.

Usage: python3 -I discover.py --work /tmp/dir --out sources.tsv
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sicd  # noqa: E402

BUCKET = "https://umbra-open-data-catalog.s3.amazonaws.com/"
PREFIX = "sar-data/tasks/"
CAP = 1_000_000_000
MIB = 1 << 20


def curl(args, out=None):
    cmd = ["curl", "-fsS", "--max-time", "120", "--retry", "3"] + args
    if out:
        cmd += ["-o", out]
        subprocess.run(cmd, check=True)
        return None
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def list_bucket(work):
    rows, tok, page = [], "", 0
    while True:
        url = f"{BUCKET}?list-type=2&prefix={urllib.parse.quote(PREFIX)}&max-keys=1000"
        if tok:
            url += "&continuation-token=" + urllib.parse.quote(tok, safe="")
        path = os.path.join(work, f"list_{page:03d}.xml")
        if not os.path.exists(path):
            curl([url], path)
        txt = open(path, encoding="utf-8").read()
        for c in re.findall(r"<Contents>(.*?)</Contents>", txt, re.S):
            key = html.unescape(re.search(r"<Key>(.*?)</Key>", c).group(1))
            size = int(re.search(r"<Size>(\d+)</Size>", c).group(1))
            etag = html.unescape(re.search(r"<ETag>(.*?)</ETag>", c).group(1)).strip('"')
            lm = re.search(r"<LastModified>(.*?)</LastModified>", c).group(1)
            rows.append((key, size, etag, lm))
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", txt)
        page += 1
        if not m:
            return rows
        tok = html.unescape(m.group(1))


def part_size_for(size, etag):
    if "-" not in etag:
        return 0
    n = int(etag.split("-")[1])
    for p in (8 * MIB, 16 * MIB, 5 * MIB, 32 * MIB, 64 * MIB):
        if -(-size // p) == n:
            return p
    raise SystemExit(f"cannot infer multipart part size for {size} {etag}")


def url_of(key):
    return BUCKET + urllib.parse.quote(key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    rows = list_bucket(a.work)
    sicds = sorted((r for r in rows if r[0].endswith("_SICD.nitf")), key=lambda r: (r[1], r[0]))
    print(f"listed_keys={len(rows)} sicd_keys={len(sicds)}", file=sys.stderr)
    chosen, total, probed = [], 0, 0
    for key, size, etag, lm in sicds:
        probed += 1
        tag = f"{probed:04d}"
        hp, tp = os.path.join(a.work, tag + ".head"), os.path.join(a.work, tag + ".tail")
        if not os.path.exists(hp):
            curl(["-r", "0-4095", url_of(key)], hp)
        if not os.path.exists(tp):
            curl(["-r", f"{size - 65536}-{size - 1}", url_of(key)], tp)
        head, tail = open(hp, "rb").read(), open(tp, "rb").read()
        toff = size - len(tail)

        def read(o, n):
            if o + n <= len(head):
                return head[o:o + n]
            if o >= toff:
                return tail[o - toff:o - toff + n]
            raise sicd.NitfError(f"not probed {o}+{n}")

        try:
            info = sicd.inspect(read)
            if info["FL"] != size:
                raise sicd.NitfError("FL != object size")
            sicd.assert_regime(info)
        except sicd.NitfError as e:
            print(f"skip size={size} {key}: {e}", file=sys.stderr)
            continue
        s = info["sicd"]
        dup = [c for c in chosen if abs(c["scp_lat"] - s["scp_lat"]) < 0.05
               and abs(c["scp_lon"] - s["scp_lon"]) < 0.05]
        if dup:
            print(f"skip size={size} {key}: same scene as {dup[0]['core']}", file=sys.stderr)
            continue
        if total + info["image_data_length"] > CAP:
            print(f"stop at size={size} {key}: cap", file=sys.stderr)
            break
        total += info["image_data_length"]
        meta_key = key[: -len("_SICD.nitf")] + "_METADATA.json"
        meta = json.loads(curl([url_of(meta_key)]))
        col = meta["collects"][0]
        ish = info["image_subheader"]
        chosen.append({
            "core": os.path.basename(key)[: -len("_SICD.nitf")],
            "key": key, "url": url_of(key), "size": size, "etag": etag,
            "part_size": part_size_for(size, etag), "last_modified": lm,
            "site": key.split("/")[2],
            "rows": s["num_rows"], "cols": s["num_cols"],
            "header_length": info["HL"], "image_subheader_length": info["image_data_offset"] - info["HL"],
            "image_data_offset": info["image_data_offset"], "image_data_length": info["image_data_length"],
            "des_data_offset": info["des_data_offset"], "des_data_length": info["des_data_length"],
            "collector": s["collector"], "processor": sicd.processor_version(s["application"]),
            "scp_lat": s["scp_lat"], "scp_lon": s["scp_lon"],
            "row_ss_m": s["row_ss"], "col_ss_m": s["col_ss"],
            "row_irw_m": s["row_imp_resp_wid"], "col_irw_m": s["col_imp_resp_wid"],
            "polarization": "+".join(col["polarizations"]),
            "grazing_deg": col["angleGrazingDegrees"],
            "product_sku": meta.get("productSku", ""),
            "valid_poly_fraction": sicd.polygon_area(s["valid_polygon"]) / (s["num_rows"] * s["num_cols"]),
            "nppbh": ish["NPPBH"], "nppbv": ish["NPPBV"],
        })
    print(f"probed={probed} selected={len(chosen)} image_bytes={total}", file=sys.stderr)
    cols = ["ordinal", "core", "site", "size", "etag", "part_size", "last_modified", "rows", "cols",
            "header_length", "image_subheader_length", "image_data_offset", "image_data_length",
            "des_data_offset", "des_data_length", "collector", "processor", "polarization",
            "product_sku", "scp_lat", "scp_lon", "row_ss_m", "col_ss_m", "row_irw_m", "col_irw_m",
            "grazing_deg", "valid_poly_fraction", "url", "key"]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for i, c in enumerate(chosen, 1):
            c["ordinal"] = i
            vals = []
            for k in cols:
                v = c[k]
                if isinstance(v, float):
                    v = f"{v:.6f}" if k in ("scp_lat", "scp_lon", "valid_poly_fraction") else f"{v:.4f}"
                vals.append(str(v))
            f.write("\t".join(vals) + "\n")


if __name__ == "__main__":
    main()
