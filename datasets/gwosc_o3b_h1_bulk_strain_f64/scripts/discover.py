#!/usr/bin/env python3
"""Author-time file selection for gwosc_o3b_h1_bulk_strain_f64 (no network).

discover.sh fetches the inputs with curl; this script only parses them.

``candidates``: from the GWOSC H1_DATA segment list of O3b_4KHZ_R1, list
4096-s file slots (GPS start a multiple of 4096, as in the GWOSC bulk archive)
whose whole span [start, start + 4096) lies inside one H1_DATA segment.  For
each of N targets spaced evenly over the O3b GPS span (centre of each of N equal
bins), print the K fully-covered slots nearest to the target.

``finalize``: given the per-slot GWOSC v2 strain-file detail JSON documents,
keep for each target the nearest slot whose detail reports a 4 kHz H1 file with
dutycycle 100 %, nans_fraction 0 and a positive file size, and write the pinned
files.tsv.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DURATION = 4096
ARCHIVE = "https://gwosc.org/archive/data/O3b_4KHZ_R1"


def file_url(gps: int) -> str:
    return f"{ARCHIVE}/{gps - gps % (1 << 20)}/H-H1_GWOSC_O3b_4KHZ_R1-{gps}-{DURATION}.hdf5"


def covered_slots(segments: list[list[int]]) -> list[tuple[int, list[int]]]:
    out = []
    for a, b in segments:
        s = -(-a // DURATION) * DURATION
        while s + DURATION <= b:
            out.append((s, [a, b]))
            s += DURATION
    return out


def targets(run_start: int, run_end: int, n: int) -> list[int]:
    span = run_end - run_start
    return [run_start + (2 * k + 1) * span // (2 * n) for k in range(n)]


def ranked(seg_doc: dict, run_start: int, run_end: int, n: int, k: int) -> list[tuple[int, list[tuple[int, list[int]]]]]:
    if seg_doc.get("id") != "H1_DATA" or seg_doc.get("dataset") != "O3b_4KHZ_R1":
        raise SystemExit("segment document is not O3b_4KHZ_R1 / H1_DATA")
    slots = covered_slots(seg_doc["segments"])
    out = []
    used: set[int] = set()
    for t in targets(run_start, run_end, n):
        near = sorted((s for s in slots if s[0] not in used), key=lambda s: (abs(s[0] + DURATION // 2 - t), s[0]))[:k]
        used.update(s[0] for s in near)
        out.append((t, near))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["candidates", "finalize"])
    ap.add_argument("--segments", required=True)
    ap.add_argument("--run-start", type=int, required=True)
    ap.add_argument("--run-end", type=int, required=True)
    ap.add_argument("--n", type=int, default=7)
    ap.add_argument("--per-target", type=int, default=4)
    ap.add_argument("--details-dir")
    ap.add_argument("--out")
    a = ap.parse_args()
    seg_doc = json.loads(Path(a.segments).read_text())
    plan = ranked(seg_doc, a.run_start, a.run_end, a.n, a.per_target)
    if a.mode == "candidates":
        for _t, near in plan:
            for gps, _seg in near:
                print(gps)
        return 0
    rows = []
    for t, near in plan:
        chosen = None
        for gps, seg in near:
            p = Path(a.details_dir) / f"H1-{gps}-4kHz.json"
            if not p.exists():
                continue
            d = json.loads(p.read_text())
            ok = (d.get("detector") == "H1" and d.get("sample_rate_kHz") == 4 and d.get("gps_start") == gps
                  and float(d.get("dutycycle_percent", 0)) == 100.0 and float(d.get("nans_fraction", 1)) == 0.0
                  and int(d.get("filesize_bytes", 0)) > 0
                  and d.get("hdf5_url", "").split("?")[0] == file_url(gps))
            if ok:
                chosen = (gps, seg, d)
                break
        if chosen is None:
            raise SystemExit(f"no acceptable file near target {t}")
        gps, seg, d = chosen
        rows.append([str(gps), d["utc_start"], file_url(gps), str(d["filesize_bytes"]), f"{seg[0]}-{seg[1]}",
                     repr(float(d["min_strain"])), repr(float(d["max_strain"])), repr(float(d["mean_strain"])),
                     repr(float(d["stdev_strain"])), repr(float(d["bns_range"]))])
    header = ["gps_start", "utc_start", "url", "size_bytes", "h1_data_segment", "gwosc_min_strain",
              "gwosc_max_strain", "gwosc_mean_strain", "gwosc_stdev_strain", "gwosc_bns_range_mpc"]
    text = "\t".join(header) + "\n" + "".join("\t".join(r) + "\n" for r in rows)
    Path(a.out).write_text(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
