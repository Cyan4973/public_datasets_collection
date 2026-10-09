#!/usr/bin/env python3
"""Turn saved OSF files-API listing pages into the pinned sources.tsv.

Input: the JSON pages of
  https://api.osf.io/v2/nodes/6hfpz/files/osfstorage/?page=N&page[size]=100&sort=name
(saved by discover.sh). Folders (the INDEX folder) are ignored.

Selection rule (deterministic): walk athlete zips in ascending file-name order
(names are random athlete UUIDs, so name order is an unbiased shuffle), keep
zips whose size is within [MIN_ZIP_BYTES, MAX_ZIP_BYTES], and stop as soon as
the cumulative kept size reaches TARGET_BYTES. The size cap keeps a few very
prolific athletes (zips up to 264 MB) from dominating; the floor drops empty
or near-empty athlete zips.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_ZIP_BYTES = 100_000
MAX_ZIP_BYTES = 20_000_000
TARGET_BYTES = 2_800_000_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    rows = []
    for page in sorted(args.pages.glob("page_*.json")):
        for item in json.loads(page.read_text(encoding="utf-8"))["data"]:
            a = item["attributes"]
            if a["kind"] != "file":
                continue
            rows.append((a["name"], item["id"], int(a["size"]), a["extra"]["hashes"]["sha256"],
                         a["extra"]["hashes"]["md5"], a["date_modified"]))
    names = [r[0] for r in rows]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate names across pages: listing drifted while paging, re-run discovery")
    rows.sort()
    if not all(r[0].endswith(".zip") for r in rows):
        raise SystemExit("unexpected non-zip file in osfstorage root")
    kept, total = [], 0
    for r in rows:
        if not MIN_ZIP_BYTES <= r[2] <= MAX_ZIP_BYTES:
            continue
        kept.append(r)
        total += r[2]
        if total >= TARGET_BYTES:
            break
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("filename\tosf_file_id\tsize_bytes\tsha256\tmd5\tdate_modified\turl\n")
        for name, fid, size, sha, md5, dm in kept:
            fh.write(f"{name}\t{fid}\t{size}\t{sha}\t{md5}\t{dm}\thttps://osf.io/download/{fid}/\n")
    print(f"listed_files={len(rows)} listed_bytes={sum(r[2] for r in rows)} "
          f"selected={len(kept)} selected_bytes={total} last={kept[-1][0]}")


if __name__ == "__main__":
    main()
