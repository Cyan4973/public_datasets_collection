#!/usr/bin/env python3
"""Author-time resolver for sources.tsv (not run by download/build/verify).

Fetches (with curl) the VGPW_1001 INDEX/INDEX.TAB and EXTRAS/MD5LF.TXT into a
scratch directory, splits the Voyager 1 PWS waveform frames into eight
mission-phase strata by START_TIME, takes a fixed number of frames per
stratum at evenly spaced ranks floor((i + 0.5) * n / k), and replaces a pick
whose DAT (HTTP HEAD Content-Length) holds fewer than MIN_RECORDS 1024-byte
records with the next unused rank (wrapping). Writes sources.tsv with path,
START_TIME, stratum, exact DAT/LBL sizes, upstream MD5s and Last-Modified.

Usage: python3 discover.py --work /tmp/autocollect/<id>/discover --out sources.tsv
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "https://space.physics.uiowa.edu/plasma-wave/voyager/data/VGPW_1001"
UA = "openzl-public-datasets-voyager-pws/1.0"
MIN_RECORDS = 512  # header + at least 511 data lines
STRATA = [
    # id, start (inclusive), stop (exclusive), picks, description
    ("A_prejupiter", "1978-08-01", "1979-02-28", 40, "Earth-Jupiter cruise and Jupiter approach (before first bow shock)"),
    ("B_jupiter", "1979-02-28", "1979-03-23", 100, "Jupiter encounter, bow shock to bow shock"),
    ("C_jupiter_saturn", "1979-03-23", "1980-11-11", 30, "Jupiter-Saturn cruise"),
    ("D_saturn", "1980-11-11", "1980-11-17", 20, "Saturn encounter, bow shock to bow shock"),
    ("E_cruise_full", "1980-11-17", "1992-11-03", 70, "outer-heliosphere cruise, all lines returned"),
    ("F_cruise_decimated", "1992-11-03", "2004-12-16", 50, "solar-wind cruise after 1992-11-03 (1 line in 5 returned)"),
    ("G_heliosheath", "2004-12-16", "2012-08-25", 40, "heliosheath (termination shock to heliopause)"),
    ("H_interstellar", "2012-08-25", "2024-01-01", 50, "interstellar medium beyond the heliopause"),
]


def curl(url: str, out: Path | None = None, head: bool = False) -> str:
    cmd = ["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "3",
           "--max-time", "120", "--user-agent", UA]
    if head:
        cmd += ["--head"]
    if out is not None:
        cmd += ["--output", str(out)]
    cmd.append(url)
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def head(url: str) -> tuple[int, str]:
    text = curl(url, head=True)
    size, modified = -1, ""
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if k.lower() == "content-length":
            size = int(v.strip())
        elif k.lower() == "last-modified":
            modified = v.strip()
    return size, modified


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    index = args.work / "INDEX.TAB"
    md5 = args.work / "MD5LF.TXT"
    if not index.exists():
        curl(f"{BASE}/INDEX/INDEX.TAB", index)
    if not md5.exists():
        curl(f"{BASE}/EXTRAS/MD5LF.TXT", md5)
    md5s = {}
    for line in md5.read_text(encoding="latin-1").splitlines():
        h, _, p = line.partition("  ")
        md5s[p.strip()] = h.strip()

    frames = []
    for line in index.read_text(encoding="latin-1").splitlines()[1:]:
        f = [x.strip().strip('"').strip() for x in line.split(",")]
        vol, product, start, sclk, lbl_path = f[0], f[1], f[2], f[3], f[4]
        if vol != "VGPW_1001" or not product.startswith("VG1P") or not lbl_path.endswith(".LBL"):
            raise SystemExit(f"unexpected index row {line!r}")
        frames.append((start, product, sclk, lbl_path[:-4]))
    frames.sort()

    rows = []
    for sid, a, b, k, _desc in STRATA:
        pool = [fr for fr in frames if a <= fr[0] < b]
        n = len(pool)
        used: set[int] = set()
        picks = []
        skipped = 0
        for i in range(k):
            r = int((i + 0.5) * n / k)
            for step in range(n):
                rr = (r + step) % n
                if rr in used:
                    continue
                used.add(rr)
                start, product, sclk, stem = pool[rr]
                size, modified = head(f"{BASE}/{stem}.DAT")
                if size < MIN_RECORDS * 1024 or size % 1024:
                    skipped += 1
                    continue
                lsize, _ = head(f"{BASE}/{stem}.LBL")
                picks.append((rr, start, product, sclk, stem, size, modified, lsize))
                break
            else:
                raise SystemExit(f"{sid}: ran out of frames")
        print(f"{sid}: pool={n} picks={len(picks)} skipped_short={skipped}", file=sys.stderr)
        for rr, start, product, sclk, stem, size, modified, lsize in sorted(picks):
            rows.append([sid, product, start, sclk, stem, str(rr), str(size), str(size // 1024),
                         md5s[stem + ".DAT"], modified, str(lsize), md5s[stem + ".LBL"]])
    hdr = ["stratum", "product_id", "start_time", "sclk", "path_stem", "stratum_rank", "dat_size", "file_records",
           "dat_md5", "dat_last_modified", "lbl_size", "lbl_md5"]
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(hdr) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    print(f"wrote {len(rows)} frames, dat_bytes={sum(int(r[6]) for r in rows)}, "
          f"lbl_bytes={sum(int(r[10]) for r in rows)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
