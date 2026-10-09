#!/usr/bin/env python3
"""Generate the recipe pins (volumes.tsv, candidates.tsv, sources.tsv) from a discovery work dir.

Stage 'candidates': needs <work>/index/<VOLUME>_INDEX.TAB for all 35 volumes.
Stage 'sources': additionally needs <work>/labels/<PRODUCT_ID>.LBL for every candidate,
  <work>/heads.tsv (product_id<TAB>content_length from HEAD on each selected IMG) and
  optionally <work>/md5/<VOLUME>_md5.txt volume checksum lists for cross-checking.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junocam as jc  # noqa: E402


def write_tsv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(value) for value in row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["candidates", "sources"])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    index_dir = args.work / "index"

    if args.stage == "candidates":
        rows = []
        for volume in jc.VOLUMES:
            path = index_dir / f"{volume}_INDEX.TAB"
            data = path.read_bytes()
            rows.append([volume, f"{jc.BASE_URL}/{volume}/INDEX/INDEX.TAB", len(data), hashlib.md5(data).hexdigest()])
        write_tsv(args.recipe_dir / "volumes.tsv", ["volume", "index_url", "index_size", "index_md5"], rows)
        cands = jc.candidates(index_dir)
        write_tsv(args.recipe_dir / "candidates.tsv",
                  ["product_id", "volume", "orbit", "version", "rel_minutes", "label_url", "label_md5", "start_time", "rationale"],
                  [[c["product_id"], c["volume"], c["orbit"], c["version"], c["rel_minutes"],
                    f"{jc.BASE_URL}/{c['volume']}/{c['label_path']}", c["label_md5"], c["start_time"], c["rationale"]] for c in cands])
        print(f"candidates={len(cands)} orbits={len({c['orbit'] for c in cands})}")
        return 0

    cands = jc.candidates(index_dir)
    for cand in cands:
        data = (args.work / "labels" / f"{cand['product_id']}.LBL").read_bytes()
        if hashlib.md5(data).hexdigest() != cand["label_md5"]:
            raise SystemExit(f"label MD5 differs from INDEX.TAB for {cand['product_id']}")
    chosen = jc.select(cands, args.work / "labels")
    heads = dict(line.split("\t") for line in (args.work / "heads.tsv").read_text().split("\n") if line.strip())
    md5_lists: dict[str, str] = {}
    for path in sorted((args.work / "md5").glob("*_md5.txt")):
        for line in path.read_text(encoding="latin-1").splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                md5_lists[parts[1].strip()] = parts[0].lower()
    rows = []
    for item in chosen:
        img_rel = item["label_path"][:-4] + ".IMG"
        if int(heads.get(item["product_id"], -1)) != item["img_size"]:
            raise SystemExit(f"HEAD size {heads.get(item['product_id'])} != LINES*1648 {item['img_size']} for {item['product_id']}")
        listed = md5_lists.get(f"{item['volume']}/{img_rel}")
        if listed is not None and listed != item["img_md5"]:
            raise SystemExit(f"volume md5 list {listed} != label IMAGE MD5 {item['img_md5']} for {item['product_id']}")
        rows.append([item["product_id"], item["volume"], item["orbit"], item["rel_minutes"], item["start_time"], item["lines"],
                     f"{jc.BASE_URL}/{item['volume']}/{img_rel}", item["img_size"], item["img_md5"],
                     "yes" if listed else "no", f"{jc.BASE_URL}/{item['volume']}/{item['label_path']}", item["label_md5"],
                     item["tdi"], item["exposure"], item["altitude"], item["rationale"]])
    write_tsv(args.recipe_dir / "sources.tsv",
              ["product_id", "volume", "orbit", "rel_minutes", "start_time", "lines", "img_url", "img_size", "img_md5",
               "md5_list_confirmed", "label_url", "label_md5", "tdi_stages", "exposure", "spacecraft_altitude", "rationale"], rows)
    print(f"sources={len(rows)} img_bytes={sum(r[7] for r in rows)} orbits={[r[2] for r in rows]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
