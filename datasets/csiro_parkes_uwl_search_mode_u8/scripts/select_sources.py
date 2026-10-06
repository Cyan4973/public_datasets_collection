#!/usr/bin/env python3
"""Apply the documented selection rule to DAP metadata fetched by discover.sh.

Inputs (in --discovery-dir): search.json, collection_<id>.json,
collection_<id>_data.json and <id>.log for each P1018 collection.

Rule:
  1. Keep collections whose title starts with 'Parkes observations for project
     P1018 semester 2019APRS', licence CC BY 4.0, accessLevel Public, and whose
     log lists UWLSRCH files (uwl_*.sf). This drops the empty 66064 and the
     BPSR-only 41516.
  2. From each <id>.log, map raw/<obs>_<k>.sf to its source directory and keep
     only 'ProxCen_S' (on-source science scans).
  3. Eligible observations: all 16 files (k = 0..15) inside one collection.
  4. In time order, take eligible indices round(i * (N - 1) / 7), i = 0..7.
  5. Use file k = 8 (middle of the observation) and SUBINT row NAXIS2 // 2.
Output: TSV with observation, collection, DOI, file id, filename, fileSize,
log MD5, presigned URL (last column, ephemeral).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

N_PICK = 8
FILE_INDEX = 8
TITLE_PREFIX = "Parkes observations for project P1018 semester 2019APRS"
LICENCE = "Creative Commons Attribution 4.0 International Licence"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discovery-dir", required=True)
    args = ap.parse_args()
    root = Path(args.discovery_dir)
    search = json.loads((root / "search.json").read_text(encoding="utf-8"))
    obs_files: dict[str, list[tuple[int, int, str]]] = collections.defaultdict(list)
    file_meta: dict[str, tuple] = {}
    for coll in search["dataCollections"]:
        cid = int(coll["dataCollectionId"])
        meta = json.loads((root / f"collection_{cid}.json").read_text(encoding="utf-8"))
        if not str(meta.get("title", "")).startswith(TITLE_PREFIX):
            continue
        if meta.get("licence") != LICENCE or meta.get("accessLevel") != "Public":
            print(f"# skip {cid}: licence/access {meta.get('licence')!r}/{meta.get('accessLevel')!r}")
            continue
        log_path = root / f"{cid}.log"
        if not log_path.is_file():
            print(f"# skip {cid}: no collection log (empty collection)")
            continue
        listing = json.loads((root / f"collection_{cid}_data.json").read_text(encoding="utf-8"))
        files = {f["filename"]: f for f in listing.get("file", [])}
        uwl = 0
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            match = re.fullmatch(r"raw/(uwl_\d{6}_\d{6})_(\d+)\.sf", parts[1])
            if not match:
                continue
            uwl += 1
            source = parts[2].split("/")[-2]
            if source != "ProxCen_S":
                continue
            obs_files[match.group(1)].append((cid, int(match.group(2)), parts[1]))
            entry = files[parts[1]]
            file_meta[parts[1]] = (cid, meta.get("doi"), entry["id"], entry["fileSize"], parts[6],
                                   entry["presignedLink"]["href"])
        if not uwl:
            print(f"# skip {cid}: no UWL search-mode files (e.g. BPSR only)")
    eligible = [
        obs for obs in sorted(obs_files)
        if len({c for c, _, _ in obs_files[obs]}) == 1
        and sorted(k for _, k, _ in obs_files[obs]) == list(range(16))
    ]
    print(f"# ProxCen_S observations: {len(obs_files)}; eligible (16 files in one collection): {len(eligible)}")
    picks = [eligible[round(i * (len(eligible) - 1) / (N_PICK - 1))] for i in range(N_PICK)]
    print("observation_id\tcollection_id\tcollection_doi\tfile_id\tfilename\tfile_size\tfile_md5_from_collection_log\tpresigned_url")
    for obs in picks:
        fname = f"raw/{obs}_{FILE_INDEX}.sf"
        cid, doi, fid, size, md5, href = file_meta[fname]
        print(f"{obs}\t{cid}\t{doi}\t{fid}\t{fname}\t{size}\t{md5}\t{href}")


if __name__ == "__main__":
    main()
