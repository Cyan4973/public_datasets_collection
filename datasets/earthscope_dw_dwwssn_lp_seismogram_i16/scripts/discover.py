#!/usr/bin/env python3
"""Resolve the pinned DWWSSN station-day plan (documents how plan.tsv was
produced; build/verify never run this).

Epochs (`epochs()`): from the FDSN station-service channel text for network
DW, keep the LHZ (blank location, 1 sps) epochs whose SensorDescription is
'Sprengnether Series 201 S-5007-V Seismometer' with nominal scale 5.0E8 at
0.04 Hz. This drops the Geotech SL-210 stations (BER, CMB, JAS, JAS1), the
Streckeisen STS-1 epochs that replaced the Sprengnether at AFI, COL, KEV and
TOL in 1987 (much smaller counts: ~+-60 on a quiet day), CMB's Guralp CMG3,
and the SCP 1990-12-07..1991-02-20 epoch logged at double gain (1.0E9).
Candidate days lie strictly inside an epoch (first full day after its start
.. last full day before its end).

Step 1 (`probe-body`): for every kept station, split the union of its kept
epochs' candidate days into STRATA equal strata and pick one day per stratum
at crc32(station:k) offset. Emit an fdsnws-dataselect POST body with three
10-minute windows per candidate (03:00, 12:00, 21:00 UTC). The service
returns the whole 4096-byte records (~2016 samples) that intersect a window,
so presence is measured as the overlap of record spans with each window.

Step 2 (`select`): parse the probe miniSEED. A candidate is present when each
window returned at least 95% of its 600 DW.<sta>..LHZ samples at 1 sps. For
each station take PER_STATION present candidates evenly spaced in time order
(index floor(i * n_present / PER_STATION)), so every station contributes
about the same number of days spread over its whole Sprengnether epoch, and
write plan.tsv (station, day) sorted by station then day. Whether a full day
is contiguous and passes the clipping/constant policy is only known after the
full download; build.sh keeps the station-days that pass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

NET, LOC, CHA = "DW", "", "LHZ"
SENSOR = "Sprengnether Series 201 S-5007-V Seismometer"
SCALE = 5.0e8
RATE = 1.0
STRATA = 96
PER_STATION = 48
WINDOWS = ("03:00:00", "12:00:00", "21:00:00")
WINDOW_S = 600


def epochs(inventory: Path):
    """station -> sorted list of (first_full_day, last_full_day) kept epochs."""
    out = {}
    for line in inventory.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = [x.strip() for x in line.split("|")]
        if f[0] != NET or f[2] != LOC or f[3] != CHA or f[10] != SENSOR:
            continue
        if float(f[11]) != SCALE or float(f[14]) != RATE:
            continue
        s = dt.date.fromisoformat(f[15][:10]) + dt.timedelta(days=1)
        e = dt.date.fromisoformat(f[16][:10]) - dt.timedelta(days=1)
        if e >= s:
            out.setdefault(f[1], []).append((s, e))
    return {k: sorted(v) for k, v in sorted(out.items())}


def candidates(inventory: Path):
    """(station, day) candidates, one per stratum, in time order per station."""
    out = []
    for sta, eps in epochs(inventory).items():
        days = []
        for s, e in eps:
            days.extend(s + dt.timedelta(days=i) for i in range((e - s).days + 1))
        days = sorted(set(days))
        n = len(days)
        for k in range(STRATA):
            lo, hi = k * n // STRATA, (k + 1) * n // STRATA
            if hi <= lo:
                continue
            out.append((sta, days[lo + zlib.crc32(f"{sta}:{k}".encode()) % (hi - lo)]))
    return out


def cmd_probe_body(a):
    lines = ["nodata=404"]
    cands = candidates(Path(a.inventory))
    for sta, d in cands:
        for w in WINDOWS:
            t = dt.datetime.fromisoformat(f"{d}T{w}")
            lines.append(f"{NET} {sta} -- {CHA} {t.isoformat()} {(t + dt.timedelta(seconds=WINDOW_S)).isoformat()}")
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"stations={len({s for s, _ in cands})} candidates={len(cands)} windows={len(lines) - 1}", file=sys.stderr)


def cmd_select(a):
    cands = candidates(Path(a.inventory))
    got = {}  # (station, day, window) -> samples
    for r in mseed.iter_records(Path(a.probe).read_bytes(), decode=False):
        if (r.network, r.location, r.channel) != (NET, LOC, CHA) or r.sample_rate != RATE or not r.nsamples:
            continue
        if r.encoding != mseed.ENC_DWWSSN:
            continue
        # the service returns whole (untrimmed) ~2016-sample records, so count
        # the samples of each record that overlap each window
        r0 = r.start_ns / 1e9
        r1 = r0 + r.nsamples / RATE
        start = dt.datetime.fromtimestamp(r0, dt.timezone.utc)
        for w in WINDOWS:
            t = dt.datetime.fromisoformat(f"{start.date()}T{w}+00:00").timestamp()
            ov = min(r1, t + WINDOW_S) - max(r0, t)
            if ov > 0:
                key = (r.station, start.date(), w)
                got[key] = got.get(key, 0) + int(round(ov * RATE))
    need = int(0.95 * WINDOW_S * RATE)
    present = {}
    for sta, d in cands:
        if all(got.get((sta, d, w), 0) >= need for w in WINDOWS):
            present.setdefault(sta, []).append(d)
    plan = []
    for sta in sorted({s for s, _ in cands}):
        p = present.get(sta, [])
        if len(p) <= PER_STATION:
            pick = p
        else:
            pick = [p[i * len(p) // PER_STATION] for i in range(PER_STATION)]
        plan.extend((sta, d) for d in sorted(pick))
        n_c = sum(1 for s, _ in cands if s == sta)
        years = sorted({d.year for d in pick})
        print(f"{sta}: candidates={n_c} present={len(p)} picked={len(pick)} years={years[0] if years else '-'}..{years[-1] if years else '-'}",
              file=sys.stderr)
    with open(a.out, "w") as fh:
        fh.write("station\tday\n")
        for sta, d in plan:
            fh.write(f"{sta}\t{d}\n")
    print(f"candidates={len(cands)} present={sum(len(v) for v in present.values())} plan={len(plan)}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("probe-body"); b.add_argument("--inventory", required=True); b.add_argument("--out", required=True)
    s = sub.add_parser("select"); s.add_argument("--inventory", required=True); s.add_argument("--probe", required=True); s.add_argument("--out", required=True)
    a = p.parse_args()
    {"probe-body": cmd_probe_body, "select": cmd_select}[a.cmd](a)


if __name__ == "__main__":
    main()
