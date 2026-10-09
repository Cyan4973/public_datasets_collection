#!/usr/bin/env python3
"""Re-derive files.tsv from the live OzFlux THREDDS catalog (documentation aid).

Not called by download.sh/build.sh/verify.sh. It records how the pinned list in
files.tsv was resolved on 2026-10-09:

1. read ecosystem_process/ozflux/catalog.xml -> one catalogRef per site;
2. for each site take the lexically latest release folder (2020 < 2021_v1 <
   ... < 2026_v3);
3. list <site>/<release>/L3/default/catalog.xml -> every *.nc dataset;
4. read each file's OPeNDAP .dds (time length, Float64 Fco2/Fe/Fh) and .das
   (global time_step, license_name);
5. keep only files with time_step 30 (drops Otway_L3.nc and
   Tumbarumba1_20020107T1600_to_20221203T1800_L3.nc, both 60-minute).

Network I/O goes through curl (respects ~/.curlrc proxies).

Usage: python3 discover.py > files.candidate.tsv
"""
from __future__ import annotations

import re
import subprocess
import sys

CATALOG = "https://dap.tern.org.au/thredds/catalog/ecosystem_process/ozflux/"
DODS = "https://dap.tern.org.au/thredds/dodsC/"


def get(url: str) -> str:
    return subprocess.run(
        ["curl", "-fsS", "--max-time", "120", "--retry", "3", url],
        capture_output=True, text=True, check=True,
    ).stdout


def main() -> int:
    root = get(CATALOG + "catalog.xml")
    sites = re.findall(r'xlink:href="([^"/]+)/catalog.xml"', root)
    print("# site\trelease\tfile_name\turl_path\ttime_length\ttime_step_minutes")
    for site in sites:
        releases = sorted(re.findall(r'xlink:href="([^"/]+)/catalog.xml"', get(f"{CATALOG}{site}/catalog.xml")))
        if not releases:
            continue
        release = releases[-1]
        listing = get(f"{CATALOG}{site}/{release}/L3/default/catalog.xml")
        for name, path in re.findall(r'<dataset name="([^"]+\.nc)"[^>]*urlPath="([^"]+)"', listing):
            dds = get(DODS + path + ".dds")
            das = get(DODS + path + ".das")
            length = re.search(r"Float64 time\[time = (\d+)\]", dds).group(1)
            for var in ("Fco2", "Fe", "Fh"):
                if not re.search(rf"Float64 {var}\[time = {length}\]", dds):
                    raise SystemExit(f"{name}: {var} is not Float64[time={length}]")
            step = re.search(r'time_step "?([^";\n]+)"?;', das).group(1).strip()
            license_name = re.search(r'license_name "([^"]*)"', das).group(1)
            if license_name != "CC BY 4.0":
                print(f"skip {name}: license {license_name!r}", file=sys.stderr)
                continue
            if step != "30":
                print(f"skip {name}: time_step {step}", file=sys.stderr)
                continue
            print("\t".join([site, release, name, path, length, step]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
