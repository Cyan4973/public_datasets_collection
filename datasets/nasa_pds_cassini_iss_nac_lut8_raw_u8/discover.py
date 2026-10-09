#!/usr/bin/env python3
"""Resolve the pinned frame list (sources.tsv) for nasa_pds_cassini_iss_nac_lut8_raw_u8.

Author-time tool, not part of download/build/verify. Network I/O goes through
curl (the recipe never uses urllib). Steps:

1. Fetch index/index.tab + index/index.lbl of COISS_2050, COISS_2051 and
   COISS_2052 from the PDS Imaging Node (planetarydata.jpl.nasa.gov) and apply
   the selection rule in scripts/coiss.py.
2. Fetch the PDS Rings Node per-volume MD5 manifests
   (pds-rings.seti.org/holdings/checksums-volumes/COISS_2xxx/COISS_20NN_md5.txt)
   and look up the MD5 of every selected IMG and of the index files.
   The Rings Node and Imaging Node copies are the same PDS volume; the probe
   frame N1604723153_1.IMG fetched from the Imaging Node matched the Rings
   Node MD5 (ef56e79a30047487e85c44fbde282652).
3. HEAD every selected IMG on the Imaging Node for its Content-Length.
4. Write sources.tsv in selection order and print the pins used by
   download.sh and manifest.toml.

Usage: python3 discover.py [--work /tmp/autocollect/nasa_pds_cassini_iss_nac_lut8_raw_u8/discover]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import coiss  # noqa: E402

UA = "openzl-public-datasets-cassini-iss-discover/1.0"
RINGS_MD5 = "https://pds-rings.seti.org/holdings/checksums-volumes/COISS_2xxx/{vol}_md5.txt"


def curl(args: list[str]) -> bytes:
    cmd = ["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "3",
           "--max-time", "600", "--user-agent", UA] + args
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def fetch(url: str, target: Path) -> bytes:
    if not target.exists():
        target.write_bytes(curl([url]))
    return target.read_bytes()


def head_size(url: str) -> int:
    headers = curl(["--head", url]).decode("latin-1")
    sizes = re.findall(r"^content-length:\s*(\d+)", headers, flags=re.I | re.M)
    if not sizes:
        raise SystemExit(f"no Content-Length for {url}")
    return int(sizes[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=Path(f"/tmp/autocollect/{coiss.DATASET_ID}/discover"))
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    md5s: dict[str, str] = {}
    for vol in coiss.VOLUMES:
        base = coiss.volume_url(vol)
        tab = fetch(f"{base}/index/index.tab", args.work / f"{vol}_index.tab")
        lbl = fetch(f"{base}/index/index.lbl", args.work / f"{vol}_index.lbl")
        manifest = fetch(RINGS_MD5.format(vol=vol), args.work / f"{vol}_md5.txt").decode("ascii")
        for line in manifest.splitlines():
            digest, path = line.split(None, 1)
            md5s[path.strip()] = digest
        for name, blob in (("index.tab", tab), ("index.lbl", lbl)):
            pinned = md5s[f"{vol}/index/{name}"]
            actual = hashlib.md5(blob).hexdigest()
            if pinned != actual:
                raise SystemExit(f"{vol}/index/{name}: Rings Node MD5 {pinned} != fetched {actual}")
            print(f"pin {vol} index/{name} size={len(blob)} md5={actual}")
        rows += coiss.parse_index(tab, lbl.decode("ascii"), vol)

    selected = coiss.select(rows)
    print(f"index rows={len(rows)} eligible={sum(coiss.eligible(r) for r in rows)} selected={len(selected)}")
    out = ["\t".join(coiss.SOURCE_FIELDS)]
    total = 0
    for i, row in enumerate(selected):
        vol, spec = row["_volume"], row["FILE_SPECIFICATION_NAME"]
        url = f"{coiss.volume_url(vol)}/{spec}"
        size = head_size(url)
        md5 = md5s[f"{vol}/{spec}"]
        total += size
        out.append("\t".join([
            vol, spec, coiss.product_of(row), row["IMAGE_NUMBER"], row["OBSERVATION_ID"], row["TARGET_NAME"],
            row["TARGET_DESC"], row["FILTER_NAME"].replace('","', "+").replace(" ", ""), row["EXPOSURE_DURATION"],
            row["IMAGE_TIME"], url, str(size), md5,
        ]))
        if i % 50 == 0:
            print(f"resolved {i + 1}/{len(selected)} {spec} size={size}")
    (HERE / "sources.tsv").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"frames={len(selected)} img_bytes={total}")
    print("volumes", dict(Counter(r["_volume"] for r in selected)))
    print("observations", len({r["OBSERVATION_ID"] for r in selected}))
    print("targets", Counter(r["TARGET_NAME"] for r in selected).most_common())
    print("time_range", selected[0]["IMAGE_TIME"], selected[-1]["IMAGE_TIME"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
