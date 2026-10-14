#!/usr/bin/env python3
"""DWWSSN (FDSN DW, USGS ASL 1980-1994) Sprengnether LHZ station-day extraction.

Subcommands:
  validate  check downloaded miniSEED station-day files (download.sh)
  build     emit one little-endian int16 sample per accepted station-day
  verify    re-derive every sample from the downloads and check index/manifest

Policy (shared by all subcommands through classify()):
* every plan station-day must lie strictly inside an LHZ epoch of the station
  inventory whose sensor is 'Sprengnether Series 201 S-5007-V Seismometer'
  at nominal scale 5.0E8 (1 sps, blank location);
* stream identity must be DW.<plan station>..LHZ at 1 sps, DWWSSN encoding
  (32), every record overlapping the requested UTC day; anything else is
  fatal (wrong payload). Records starting before 00:00 or at/after the next
  00:00 (dataselect returns whole overlapping records) are dropped;
* records sorted by start time, exact duplicates dropped, each record must
  start within 1 sample of the previous record's nominal end (a gap or a
  conflicting overlap rejects the day; no splicing, no fill);
* the day must hold 85,536..86,410 samples (>= 99% of 86,400; the last whole
  record may run a few samples past midnight);
* fill: runs of >= 60 identical consecutive samples are digitizer fill /
  dead-channel stretches (probed natural days never repeat a value for more
  than 18 s; fill runs are thousands of samples of the value 128). A day is
  skipped if such runs cover more than 1% of its samples;
* at most 5% of the samples may sit on the int16 full-scale rails
  (|v| >= 32767), the most frequent value may cover at most 50% of the day,
  and the day must take at least 64 distinct values; otherwise the day is
  skipped and logged ("flat_fill" / "mostly_clipped" / "mostly_constant" /
  "degenerate");
* step noise: the median absolute first difference must be <= 128 counts.
  On the 1 sps long-period channel accepted days have a median |step| of
  0..53 (median 5); a few days (HON 1984-05..07) show a broadband
  oscillation with median |step| 220..324 and std ~7,000, a malfunction
  regime, and are skipped ("noisy_steps").
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import itertools
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

DATASET_ID = "earthscope_dw_dwwssn_lp_seismogram_i16"
SERIES_ID = "dwwssn_lhz_sprengnether_counts_i16"
NET, LOC, CHA = "DW", "", "LHZ"
SENSOR = "Sprengnether Series 201 S-5007-V Seismometer"
SCALE = 5.0e8
RATE = 1.0
NOMINAL = 86400
MIN_VALUES = int(0.99 * NOMINAL)  # 85,536
MAX_VALUES = NOMINAL + 10  # 86,410: whole last record may run a few samples past midnight (early-1980s clock drift)
MAX_CLIP_FRACTION = 0.05
MAX_MODE_FRACTION = 0.50
MIN_DISTINCT = 64
FLAT_RUN = 60
MAX_FLAT_FRACTION = 0.01
MAX_MEDIAN_STEP = 128
MIN_ACCEPTED_TOTAL = 300
MIN_STATIONS = 12


def read_plan(path: Path):
    lines = path.read_text().splitlines()
    if lines[0] != "station\tday":
        raise SystemExit("plan.tsv header mismatch")
    rows = []
    for line in lines[1:]:
        sta, day = line.split("\t")
        if not re.fullmatch(r"[A-Z0-9]{3,5}", sta):
            raise SystemExit(f"bad plan station {sta!r}")
        rows.append((sta, dt.date.fromisoformat(day)))
    if len(set(rows)) != len(rows):
        raise SystemExit("duplicate plan rows")
    return rows


def inventory_epochs(path: Path):
    """station -> list of (first_full_day, last_full_day) Sprengnether LHZ epochs."""
    text = path.read_text()
    if not text.startswith("#Network | Station | Location | Channel"):
        raise SystemExit("station inventory is not FDSN text")
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = [x.strip() for x in line.split("|")]
        if f[0] != NET or f[2] != LOC or f[3] != CHA or f[10] != SENSOR:
            continue
        if float(f[11]) != SCALE or float(f[14]) != RATE:
            continue
        s = dt.date.fromisoformat(f[15][:10]) + dt.timedelta(days=1)
        e = dt.date.fromisoformat(f[16][:10]) - dt.timedelta(days=1)
        out.setdefault(f[1], []).append((s, e))
    return out


def mseed_path(dl: Path, sta: str, day: dt.date) -> Path:
    return dl / "mseed" / f"DW.{sta}..LHZ.{day.isoformat()}.mseed"


def sample_name(sta: str, day: dt.date) -> str:
    return f"DW.{sta}..LHZ.{day.strftime('%Y%m%d')}.i16"


def day_ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()) * 1_000_000_000


def flat_run_samples(values):
    """Samples inside runs of >= FLAT_RUN identical consecutive values."""
    return sum(n for n in (sum(1 for _ in g) for _, g in itertools.groupby(values)) if n >= FLAT_RUN)


def median_abs_step(values):
    steps = sorted(abs(b - a) for a, b in zip(values, values[1:]))
    return steps[len(steps) // 2] if steps else 0


def policy(values):
    """Return None if the full-day value list passes the content policy, else a skip status."""
    n = len(values)
    if n < MIN_VALUES:
        return f"short_{n}"
    if n > MAX_VALUES:
        return f"long_{n}"
    flat = flat_run_samples(values)
    if flat > MAX_FLAT_FRACTION * n:
        return f"flat_fill_{flat / n:.3f}"
    clip = sum(1 for v in values if v >= 32767 or v <= -32767)
    if clip > MAX_CLIP_FRACTION * n:
        return f"mostly_clipped_{clip / n:.3f}"
    cnt = collections.Counter(values)
    if cnt.most_common(1)[0][1] > MAX_MODE_FRACTION * n:
        return f"mostly_constant_{cnt.most_common(1)[0][1] / n:.3f}"
    if len(cnt) < MIN_DISTINCT:
        return f"degenerate_{len(cnt)}"
    med = median_abs_step(values)
    if med > MAX_MEDIAN_STEP:
        return f"noisy_steps_{med}"
    return None


def classify(path: Path, sta: str, day: dt.date):
    """Decode one station-day file -> (values|None, status, info).

    Raises SystemExit on structurally invalid or wrong-stream payloads.
    """
    buf = path.read_bytes()
    if not buf:
        return None, "no_data", {"records": 0}
    try:
        recs = list(mseed.iter_records(buf))
    except mseed.MseedError as exc:
        raise SystemExit(f"{path.name}: invalid miniSEED: {exc}")
    start = day_ns(day)
    end = start + 86400 * 1_000_000_000
    for r in recs:
        if (r.network, r.station, r.location, r.channel) != (NET, sta, LOC, CHA):
            raise SystemExit(f"{path.name}: unexpected stream {r.network}.{r.station}.{r.location}.{r.channel}")
        if r.encoding != mseed.ENC_DWWSSN:
            raise SystemExit(f"{path.name}: encoding {r.encoding}, expected DWWSSN (32)")
        if r.sample_rate != RATE:
            raise SystemExit(f"{path.name}: sample rate {r.sample_rate}, expected {RATE}")
        # FDSN dataselect returns every record that overlaps the inclusive
        # request window [day 00:00, next day 00:00], so a record may begin
        # before the day or exactly at the next midnight; assemble_chain drops
        # those. A record that does not touch the window at all is fatal.
        r_end = r.start_ns + int(r.nsamples * 1e9 / RATE)
        if r_end < start - 10 ** 9 or r.start_ns > end + 10 ** 9:
            raise SystemExit(f"{path.name}: record does not overlap the requested day")
    values, status, info = mseed.assemble_chain(recs, start, RATE, tol_samples=1.0)
    if values is None:
        return None, status, info
    bad = policy(values)
    if bad:
        return None, bad, info
    return values, "accepted", info


def sample_stats(values):
    raw = struct.pack(f"<{len(values)}h", *values)
    cnt = collections.Counter(values)
    mode, mode_n = cnt.most_common(1)[0]
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    steps = [abs(b - a) for a, b in zip(values, values[1:])]
    return raw, {
        "min": min(values),
        "max": max(values),
        "distinct_values": len(cnt),
        "mode_value": mode,
        "mode_fraction": round(mode_n / n, 6),
        "clip_count": sum(c for v, c in cnt.items() if v >= 32767 or v <= -32767),
        "std": round(sd, 3),
        "flat_run_samples": flat_run_samples(values),
        "max_abs_step": max(steps) if steps else 0,
        "median_abs_step": median_abs_step(values),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def derive(recipe: Path, dl: Path):
    plan = read_plan(recipe / "plan.tsv")
    eps = inventory_epochs(dl / "dw_channels.txt")
    results = []
    counts = {}
    for sta, day in plan:
        if not any(s <= day <= e for s, e in eps.get(sta, [])):
            raise SystemExit(f"{sta} {day}: not inside a Sprengnether S-5007-V LHZ epoch of the inventory")
        p = mseed_path(dl, sta, day)
        if not p.exists():
            raise SystemExit(f"missing download {p}")
        values, status, info = classify(p, sta, day)
        key = re.sub(r"_[-0-9.]+.*$", "", status)
        counts[key] = counts.get(key, 0) + 1
        results.append((sta, day, values, status, info))
    return results, counts


def cmd_validate(a):
    dl = Path(a.downloads)
    lic = (dl / "usgs_data_licensing.html").read_text(errors="replace")
    if "anyone may use, copy, distribute, adapt, display and perform that work" not in lic \
            or "wholly produced by USGS employees" not in lic:
        raise SystemExit("USGS data-licensing page lacks the expected public-domain / CC0 statements")
    net = (dl / "fdsn_dw.html").read_text(errors="replace")
    if "Digital World-Wide Standardized Seismograph Network" not in net or "10.7914/SN/DW" not in net \
            or "Albuquerque Seismological Laboratory/USGS" not in net:
        raise SystemExit("FDSN DW network page lacks the expected DWWSSN / DOI / operator text")
    netxml = (dl / "dw_network.xml").read_text(errors="replace")
    if not re.search(r'<Network code="DW"[^>]*restrictedStatus="open"', netxml):
        raise SystemExit("station service does not list network DW as restrictedStatus=open")
    results, counts = derive(Path(a.recipe), dl)
    accepted = [r for r in results if r[2] is not None]
    with open(a.outcome, "w") as fh:
        fh.write("station\tday\tstatus\trecords\tvalues\n")
        for sta, day, values, status, info in results:
            fh.write(f"{sta}\t{day}\t{status}\t{info.get('records', 0)}\t{len(values) if values else 0}\n")
    stations = {r[0] for r in accepted}
    print(f"plan_station_days={len(results)} accepted={len(accepted)} stations={len(stations)} "
          f"status_counts={json.dumps(counts, sort_keys=True)}")
    if len(accepted) < MIN_ACCEPTED_TOTAL or len(stations) < MIN_STATIONS:
        raise SystemExit(f"only {len(accepted)} accepted station-days / {len(stations)} stations; payload looks wrong")


def cmd_build(a):
    root = Path(a.data_root)
    dl = root / "downloads" / DATASET_ID
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"
    for d in (out_dir, index.parent, stats_path.parent):
        d.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.i16"):
        old.unlink()
    results, counts = derive(Path(a.recipe), dl)
    rows, skipped, total = [], [], 0
    for sta, day, values, status, info in results:
        if values is None:
            skipped.append({"station": sta, "day": day.isoformat(), "status": status})
            continue
        raw, st = sample_stats(values)
        name = sample_name(sta, day)
        (out_dir / name).write_bytes(raw)
        total += len(raw)
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{name}",
            "numeric_kind": "int", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": len(raw), "value_count": len(values),
            "network": NET, "station": sta, "location": LOC, "channel": CHA,
            "utc_day": day.isoformat(), "sample_rate_hz": RATE,
            "source_records": info["records"], "max_abs_chain_dev_samples": info["max_abs_chain_dev"],
            **st,
        })
    with open(index, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    agg = hashlib.sha256("".join(r["sha256"] for r in rows).encode()).hexdigest()
    per_station = collections.Counter(r["station"] for r in rows)
    stats = {
        "dataset_id": DATASET_ID, "plan_station_days": len(results), "samples": len(rows),
        "total_bytes": total, "total_values": sum(r["value_count"] for r in rows),
        "status_counts": counts, "per_station": dict(sorted(per_station.items())),
        "years": sorted({r["utc_day"][:4] for r in rows}),
        "days_with_clipping": sum(1 for r in rows if r["clip_count"]),
        "clip_total": sum(r["clip_count"] for r in rows),
        "aggregate_sha256": agg, "skipped": skipped,
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"samples={len(rows)} total_bytes={total} total_values={stats['total_values']} "
          f"per_station={stats['per_station']} years={stats['years']} "
          f"days_with_clipping={stats['days_with_clipping']} "
          f"status_counts={json.dumps(counts, sort_keys=True)} aggregate_sha256={agg}")


def raw_day_values(path: Path, day: dt.date):
    """Independent minimal decode (does not use mseed.py): walk fixed 4096-byte
    big-endian DWWSSN records, keep those starting inside the UTC day, sort by
    start, drop exact duplicates, and concatenate the >h payloads."""
    buf = path.read_bytes()
    if len(buf) % 4096:
        raise SystemExit(f"{path.name}: not whole 4096-byte records")
    d0 = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    recs = []
    for off in range(0, len(buf), 4096):
        year, doy, hh, mm, ss, _u, tenk, nsamp, factor, mult = struct.unpack_from(">HHBBBBHHhh", buf, off + 20)
        data_off, blk_off = struct.unpack_from(">HH", buf, off + 44)
        btype, _nx, enc, word, rexp = struct.unpack_from(">HHBBB", buf, off + blk_off)
        if btype != 1000 or enc != 32 or word != 1 or rexp != 12 or (factor, mult) != (1, 1):
            raise SystemExit(f"{path.name}: unexpected record layout at {off}")
        t = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(
            days=doy - 1, hours=hh, minutes=mm, seconds=ss, microseconds=tenk * 100)
        rel = (t - d0).total_seconds()
        if not (-0.5 <= rel < 86400 - 0.5):
            continue
        recs.append((rel, struct.unpack_from(f">{nsamp}h", buf, off + data_off)))
    recs.sort(key=lambda x: (x[0], len(x[1])))
    out, last = [], None
    for rel, vals in recs:
        if last is not None and last == (rel, vals):
            continue
        out.extend(vals)
        last = (rel, vals)
    return out


def cmd_verify(a):
    root = Path(a.data_root)
    recipe = Path(a.recipe)
    manifest = tomllib.loads((recipe / "manifest.toml").read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    dl = root / "downloads" / DATASET_ID
    index = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(l) for l in index.read_text().splitlines() if l.strip()]
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows):
        raise SystemExit("duplicate sample_path in index")
    results, _ = derive(recipe, dl)
    expected = {f"samples/{DATASET_ID}/{SERIES_ID}/{sample_name(sta, day)}": (sta, day, values)
                for sta, day, values, status, info in results if values is not None}
    if set(expected) != set(by_path):
        raise SystemExit(f"index/sample set mismatch: expected {len(expected)} got {len(by_path)}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in out_dir.iterdir()}
    if on_disk != set(expected):
        raise SystemExit("stray or missing sample files on disk")
    total = 0
    for path, (sta, day, values) in expected.items():
        r = by_path[path]
        data = (root / path).read_bytes()
        n = len(data) // 2
        if len(data) % 2 or n != r["value_count"] or len(data) != r["sample_size_bytes"]:
            raise SystemExit(f"{path}: size mismatch")
        stored = list(struct.unpack(f"<{n}h", data))
        if stored != values:
            raise SystemExit(f"{path}: bytes differ from re-decoded source")
        if stored != raw_day_values(mseed_path(dl, sta, day), day):
            raise SystemExit(f"{path}: bytes differ from the independent raw record decode")
        bad = policy(stored)
        if bad:
            raise SystemExit(f"{path}: stored sample fails policy ({bad})")
        if len(set(stored)) < MIN_DISTINCT:
            raise SystemExit(f"{path}: constant or degenerate")
        _, st = sample_stats(stored)
        for k, v in st.items():
            if r[k] != v:
                raise SystemExit(f"{path}: index field {k}={r[k]} != {v}")
        for k, v in (("numeric_kind", "int"), ("bit_width", 16), ("endianness", "little"),
                     ("element_size_bytes", 2), ("dataset_id", DATASET_ID), ("series_id", SERIES_ID),
                     ("station", sta), ("utc_day", day.isoformat())):
            if r[k] != v:
                raise SystemExit(f"{path}: index {k}={r[k]!r}")
        total += len(data)
    if series["sample_count"] != len(expected) or series["total_size_bytes"] != total:
        raise SystemExit(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
                         f"!= realized {len(expected)}/{total}")
    if total > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB")
    stations = {r["station"] for r in rows}
    if len(expected) < MIN_ACCEPTED_TOTAL or len(stations) < MIN_STATIONS:
        raise SystemExit(f"realized scope too narrow: samples={len(expected)} stations={sorted(stations)}")
    print(f"verify_ok samples={len(expected)} total_bytes={total} stations={len(stations)} "
          f"years={sorted({r['utc_day'][:4] for r in rows})}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--recipe", required=True); v.add_argument("--downloads", required=True); v.add_argument("--outcome", required=True)
    for name in ("build", "verify"):
        b = sub.add_parser(name)
        b.add_argument("--recipe", required=True); b.add_argument("--data-root", required=True)
    a = p.parse_args()
    {"validate": cmd_validate, "build": cmd_build, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
