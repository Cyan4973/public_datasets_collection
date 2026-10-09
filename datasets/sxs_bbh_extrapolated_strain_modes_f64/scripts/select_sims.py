#!/usr/bin/env python3
"""Select the pinned SXS:BBH simulations from saved Zenodo listing pages.

Input: JSON pages of ``GET https://zenodo.org/api/records?communities=sxs&
q="SXS:BBH"&size=25&sort=oldest&page=N`` (fetched by ``discover.sh``).

Rule (deterministic):
1. keep records whose title is ``Binary black-hole simulation SXS:BBH:NNNN``,
   whose license id is ``cc-by-4.0`` and that list at least one
   ``Lev*/rhOverM_Asymptotic_GeometricUnits_CoM.h5`` file;
2. per record use the highest ``Lev`` that has both the CoM rhOverM file and
   a ``metadata.json``;
3. sort by SXS:BBH number and keep every ``STRIDE``-th record starting with
   the first (index 0, STRIDE, 2*STRIDE, ...).

Output: ``sims.tsv`` with the pinned record id, file keys, sizes and MD5s.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys

STRIDE = 40
TITLE_RE = re.compile(r"^Binary black-hole simulation SXS:BBH:(\d{4})$")
H5_RE = re.compile(r"^(?:SXS:BBH:\d{4}/)?Lev(\d+)/rhOverM_Asymptotic_GeometricUnits_CoM\.h5$")
META_RE = re.compile(r"^(?:SXS:BBH:\d{4}/)?Lev(\d+)/metadata\.json$")
COLUMNS = ["sxs_id", "record_id", "lev", "h5_key", "h5_size", "h5_md5", "meta_key", "meta_size", "meta_md5"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pages_dir")
    ap.add_argument("output")
    ap.add_argument("--stride", type=int, default=STRIDE)
    args = ap.parse_args()
    records: dict[int, dict] = {}
    for path in sorted(glob.glob(f"{args.pages_dir}/page_*.json")):
        page = json.load(open(path, encoding="utf-8"))
        for hit in page["hits"]["hits"]:
            records[int(hit["id"])] = hit
    rows = []
    for rid, hit in records.items():
        meta = hit.get("metadata") or {}
        m = TITLE_RE.match(meta.get("title", ""))
        if not m or (meta.get("license") or {}).get("id") != "cc-by-4.0":
            continue
        h5 = {}
        js = {}
        for item in hit.get("files", []):
            mh = H5_RE.match(item["key"])
            mj = META_RE.match(item["key"])
            if mh:
                h5[int(mh.group(1))] = item
            if mj:
                js[int(mj.group(1))] = item
        levs = sorted(set(h5) & set(js))
        if not levs:
            continue
        lev = levs[-1]
        fh, fj = h5[lev], js[lev]
        rows.append({
            "sxs_id": f"SXS:BBH:{m.group(1)}",
            "record_id": rid,
            "lev": lev,
            "h5_key": fh["key"],
            "h5_size": int(fh["size"]),
            "h5_md5": fh["checksum"].removeprefix("md5:"),
            "meta_key": fj["key"],
            "meta_size": int(fj["size"]),
            "meta_md5": fj["checksum"].removeprefix("md5:"),
        })
    rows.sort(key=lambda r: r["sxs_id"])
    ids = [r["sxs_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate SXS ids among eligible records")
    chosen = rows[:: args.stride]
    with open(args.output, "w", encoding="utf-8") as out:
        out.write("\t".join(COLUMNS) + "\n")
        for r in chosen:
            out.write("\t".join(str(r[c]) for c in COLUMNS) + "\n")
    print(f"records={len(records)} eligible={len(rows)} stride={args.stride} selected={len(chosen)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
