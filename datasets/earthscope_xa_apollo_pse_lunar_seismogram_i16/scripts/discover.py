#!/usr/bin/env python3
"""Resolve the pinned Apollo PSE station-day plan (documents how plan.tsv was
produced; build/verify never run this).

Step 1 (`probe-body`): for stations S12, S14, S15, S16 of FDSN network XA
(the 1969-1977 Apollo network; the XA code is reused by later temporary
networks, so every window is pinned inside 1971-1977 and the station/channel
codes are checked) and every year 1971..1977, derive CANDIDATES_PER_YEAR
distinct UTC days (day-of-year from crc32(station:year:k)) inside the
station's location-00 MHZ epoch (first full day after installation .. 1977-09-29,
the archive ends 1977-09-30T18:50). Emit an fdsnws-dataselect POST body with
three 10-minute windows per candidate day (03:00, 12:00, 21:00 UTC); the
EarthScope service trims records to the requested window.

Step 2 (`select`): parse the probe miniSEED. A candidate is present when each
window returned at least 95% of its 3,975 XA.<sta>.00.MHZ samples at 6.625 sps
and at most 20% of the pooled window samples are -1 gap markers. For each station take up to PER_STATION present
days, round-robin over years (crc order within a year) so the plan spreads over
1971-1977, and write plan.tsv (station, day) sorted by station then day.
Whether a full day is contiguous and below the -1 limit is only known after
the full download; build.sh keeps the station-days that pass.

Location 00 carries the peaked-mode long-period data; flat-mode epochs
(e.g. S12 1974-10-16..1975-04-09 and all stations 1975-06-28..1977-03-27) are
archived under location 01 and are deliberately not requested.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

STATIONS = ("S12", "S14", "S15", "S16")
YEARS = range(1971, 1978)
CANDIDATES_PER_YEAR = 8
PER_STATION = 36
LAST_DAY = dt.date(1977, 9, 29)
WINDOWS = ("03:00:00", "12:00:00", "21:00:00")
WINDOW_S = 600
RATE = 6.625


def epochs(inventory: Path):
    out = {}
    for line in inventory.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = [x.strip() for x in line.split("|")]
        if f[0] != "XA" or f[1] not in STATIONS or f[2] != "00" or f[3] != "MHZ" or float(f[14]) != 6.625:
            continue
        s = dt.date.fromisoformat(f[15][:10]) + dt.timedelta(days=1)
        e = min(dt.date.fromisoformat(f[16][:10]) - dt.timedelta(days=1), LAST_DAY)
        out[f[1]] = (s, e)
    return out


def candidates(inventory: Path):
    """(station, day) candidates in crc32 order per station-year."""
    eps = epochs(inventory)
    out = []
    for sta in STATIONS:
        s, e = eps[sta]
        for y in YEARS:
            ndays = (dt.date(y + 1, 1, 1) - dt.date(y, 1, 1)).days
            picked = []
            for k in range(400):
                d = dt.date(y, 1, 1) + dt.timedelta(days=zlib.crc32(f"{sta}:{y}:{k}".encode()) % ndays)
                if s <= d <= e and d not in picked:
                    picked.append(d)
                if len(picked) == CANDIDATES_PER_YEAR:
                    break
            out.extend((sta, d) for d in picked)
    return out


def cmd_probe_body(a):
    lines = ["nodata=404"]
    cands = candidates(Path(a.inventory))
    for sta, d in cands:
        for w in WINDOWS:
            t = dt.datetime.fromisoformat(f"{d}T{w}")
            lines.append(f"XA {sta} 00 MHZ {t.isoformat()} {(t + dt.timedelta(seconds=WINDOW_S)).isoformat()}")
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"candidates={len(cands)} windows={len(lines) - 1}", file=sys.stderr)


def cmd_select(a):
    cands = candidates(Path(a.inventory))
    # dataselect trims records to the requested window, so each window yields
    # ~WINDOW_S * RATE samples; attribute records by start time
    got = {}  # (station, day, window) -> [samples, minus_one_count]
    for r in mseed.iter_records(Path(a.probe).read_bytes()):
        if (r.network, r.location, r.channel) != ("XA", "00", "MHZ") or r.sample_rate != RATE or not r.nsamples:
            continue
        start = dt.datetime.fromtimestamp(r.start_ns / 1e9, dt.timezone.utc)
        for w in WINDOWS:
            t = dt.datetime.fromisoformat(f"{start.date()}T{w}+00:00")
            if t - dt.timedelta(seconds=1) <= start < t + dt.timedelta(seconds=WINDOW_S):
                g = got.setdefault((r.station, start.date(), w), [0, 0])
                g[0] += r.nsamples
                g[1] += r.samples.count(-1)
    need = int(0.95 * WINDOW_S * RATE)
    present = {}
    for sta, d in cands:
        gs = [got.get((sta, d, w), [0, 0]) for w in WINDOWS]
        ok = all(g[0] >= need for g in gs) and sum(g[1] for g in gs) <= 0.20 * sum(g[0] for g in gs)
        if ok:
            present.setdefault(sta, {}).setdefault(d.year, []).append(d)
    plan = []
    for sta in STATIONS:
        by_year = present.get(sta, {})
        pick = []
        idx = 0
        while len(pick) < PER_STATION and any(idx < len(v) for v in by_year.values()):
            for y in sorted(by_year):
                if idx < len(by_year[y]) and len(pick) < PER_STATION:
                    pick.append(by_year[y][idx])
            idx += 1
        plan.extend((sta, d) for d in sorted(pick))
        print(f"{sta}: present_by_year={ {y: len(v) for y, v in sorted(by_year.items())} } picked={len(pick)}", file=sys.stderr)
    with open(a.out, "w") as fh:
        fh.write("station\tday\n")
        for sta, d in plan:
            fh.write(f"{sta}\t{d}\n")
    print(f"candidates={len(cands)} present={sum(len(v) for s in present.values() for v in s.values())} plan={len(plan)}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("probe-body"); b.add_argument("--inventory", required=True); b.add_argument("--out", required=True)
    s = sub.add_parser("select"); s.add_argument("--inventory", required=True); s.add_argument("--probe", required=True); s.add_argument("--out", required=True)
    a = p.parse_args()
    {"probe-body": cmd_probe_body, "select": cmd_select}[a.cmd](a)


if __name__ == "__main__":
    main()
