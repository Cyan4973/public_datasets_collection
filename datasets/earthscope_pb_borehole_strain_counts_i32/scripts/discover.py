#!/usr/bin/env python3
"""Resolve the pinned PB strainmeter station-day plan (documentation of how
plan.tsv was produced; build/verify never run this).

Step 1 (`probe-body`): from the fdsnws/station text inventory of PB LS? channels,
keep Gladwin tensor strainmeters (location T0, sensor description starting
"GLADWIN TENSOR STRAINMETER", 1 sps), and for every station x year in
2008..2024 inside the channel epoch emit one candidate UTC day
(month and day-of-month derived from crc32(station:year), so seasons are
spread) plus two 2-minute LS1 presence windows (00:00-00:02, 23:58-24:00).
Laser strainmeters (location LM, sensor "LASER STRAINMETER") share the LS?
channel codes but are a different instrument and are excluded.

Step 2 (`select`): parse the miniSEED presence probe; a candidate is present
when both windows returned 121 LS1 samples. For each station take up to two
present years, half its present-year list apart, rotated by station index so the
whole plan spans 2008..2024, and write
plan.tsv (station, day).  Gap-freeness is only known after the full download,
so build.sh keeps the channel-days that turn out complete.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

YEARS = range(2008, 2025)


def stations(inventory: Path):
    epochs = {}
    for line in inventory.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = [x.strip() for x in line.split("|")]
        net, sta, loc, cha = f[0:4]
        sensor, rate, start, end = f[10], float(f[14]), f[15], f[16]
        if net != "PB" or loc != "T0" or cha != "LS1" or rate != 1.0:
            continue
        if not sensor.startswith("GLADWIN TENSOR STRAINMETER"):
            continue
        s = dt.date.fromisoformat(start[:10])
        e = dt.date.fromisoformat(end[:10]) if end else dt.date(2100, 1, 1)
        epochs.setdefault(sta, []).append((s, e))
    return epochs


def candidate_day(sta: str, year: int) -> dt.date:
    h = zlib.crc32(f"{sta}:{year}".encode())
    month = 1 + h % 12
    day = 1 + (h // 12) % 28
    return dt.date(year, month, day)


def candidates(inventory: Path):
    out = []
    for sta, eps in sorted(stations(inventory).items()):
        for y in YEARS:
            d = candidate_day(sta, y)
            # skip the first 90 days after installation (grout curing)
            if any(s + dt.timedelta(days=90) <= d and d + dt.timedelta(days=1) <= e for s, e in eps):
                out.append((sta, d))
    return out


def cmd_probe_body(a):
    lines = []
    for sta, d in candidates(Path(a.inventory)):
        n = d + dt.timedelta(days=1)
        lines.append(f"PB {sta} T0 LS1 {d}T00:00:00 {d}T00:02:00")
        lines.append(f"PB {sta} T0 LS1 {d}T23:58:00 {n}T00:00:00")
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"probe windows={len(lines)} candidates={len(lines)//2}", file=sys.stderr)


def cmd_select(a):
    cands = candidates(Path(a.inventory))
    got = {}
    for r in mseed.iter_records(Path(a.probe).read_bytes()):
        if r.channel != "LS1" or r.location != "T0":
            continue
        t = dt.datetime.fromtimestamp(r.start_ns / 1e9, dt.timezone.utc)
        key = (r.station, t.date(), "a" if t.hour < 12 else "b")
        got[key] = got.get(key, 0) + r.nsamples
    present = {}
    for sta, d in cands:
        if got.get((sta, d, "a"), 0) >= 120 and got.get((sta, d, "b"), 0) >= 120:
            present.setdefault(sta, []).append(d)
    plan = []
    for k, sta in enumerate(sorted(present)):
        ds = present[sta]
        if len(ds) <= 2:
            pick = ds
        else:
            # rotate the two picks with the station index so the plan as a
            # whole spans every year, half the present-year list apart
            i = (5 * k) % len(ds)
            pick = sorted({ds[i], ds[(i + len(ds) // 2) % len(ds)]})
        plan.extend((sta, d) for d in pick)
    with open(a.out, "w") as fh:
        fh.write("station\tday\n")
        for sta, d in plan:
            fh.write(f"{sta}\t{d}\n")
    years = sorted({d.year for _, d in plan})
    print(f"candidates={len(cands)} present={sum(map(len, present.values()))} "
          f"stations={len(present)} plan={len(plan)} years={years[0]}..{years[-1]}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("probe-body"); b.add_argument("--inventory", required=True); b.add_argument("--out", required=True)
    s = sub.add_parser("select"); s.add_argument("--inventory", required=True); s.add_argument("--probe", required=True); s.add_argument("--out", required=True)
    a = p.parse_args()
    {"probe-body": cmd_probe_body, "select": cmd_select}[a.cmd](a)


if __name__ == "__main__":
    main()
