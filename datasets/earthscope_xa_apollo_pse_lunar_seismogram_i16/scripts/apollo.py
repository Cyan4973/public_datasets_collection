#!/usr/bin/env python3
"""Apollo PSE (FDSN XA 1969-1977) long-period vertical MHZ station-day extraction.

Subcommands:
  validate  check downloaded miniSEED station-day files (download.sh)
  build     emit one little-endian int16 sample per accepted station-day
  verify    re-derive every sample from the downloads and check index/manifest

Policy (shared by all subcommands through classify()):
* stream identity must be XA.<plan station>.00.MHZ at 6.625 sps, Steim2
  (encoding 11), every record inside the requested UTC day (1971-1977);
  anything else is fatal (wrong payload);
* records sorted by start time, exact duplicates dropped, each record must
  start within 1 sample period of the previous record's nominal end
  (the archive stores a constant-interval stream with -1 for missing samples,
  so a true time gap or conflicting overlap rejects the day; no splicing);
* the day must hold 566,676..572,401 samples (>= 99% of 86,400 s x 6.625);
* values must lie in -1..1023 (10-bit telemetry plus the -1 marker);
* at most 20% of the samples may be -1, and the non-(-1) samples must take
  at least 16 distinct values; otherwise the day is skipped and logged.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

DATASET_ID = "earthscope_xa_apollo_pse_lunar_seismogram_i16"
SERIES_ID = "apollo_pse_mhz_peaked_du_i16"
NET, LOC, CHA = "XA", "00", "MHZ"
STATIONS = ("S12", "S14", "S15", "S16")
RATE = 6.625
NOMINAL = int(86400 * RATE)  # 572,400
MIN_VALUES = int(0.99 * NOMINAL)  # 566,676
MAX_VALUES = NOMINAL + 1
GAP = -1
MAX_GAP_FRACTION = 0.20
MIN_DISTINCT = 16
VMIN, VMAX = -1, 1023
MIN_ACCEPTED_TOTAL = 70
FIRST_DAY, LAST_DAY = dt.date(1971, 1, 1), dt.date(1977, 9, 30)


def read_plan(path: Path):
    lines = path.read_text().splitlines()
    if lines[0] != "station\tday":
        raise SystemExit("plan.tsv header mismatch")
    rows = []
    for line in lines[1:]:
        sta, day = line.split("\t")
        d = dt.date.fromisoformat(day)
        if sta not in STATIONS or not (FIRST_DAY <= d <= LAST_DAY):
            raise SystemExit(f"plan row outside scope: {sta} {day}")
        rows.append((sta, d))
    if len(set(rows)) != len(rows):
        raise SystemExit("duplicate plan rows")
    return rows


def mseed_path(dl: Path, sta: str, day: dt.date) -> Path:
    return dl / "mseed" / f"XA.{sta}.00.MHZ.{day.isoformat()}.mseed"


def sample_name(sta: str, day: dt.date) -> str:
    return f"XA.{sta}.00.MHZ.{day.strftime('%Y%m%d')}.i16"


def day_ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()) * 1_000_000_000


def inventory_ok(path: Path):
    """Set of stations whose inventory lists XA.<sta>.00.MHZ at 6.625 sps,
    'Apollo PSE Alsep Seismometer', with an epoch inside 1969-1977."""
    ok = set()
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = [x.strip() for x in line.split("|")]
        if f[0] == NET and f[2] == LOC and f[3] == CHA and float(f[14]) == RATE \
                and f[10] == "Apollo PSE Alsep Seismometer" and f[15][:4] >= "1969" and f[16][:4] <= "1977":
            ok.add(f[1])
    return ok


def classify(path: Path, sta: str, day: dt.date):
    """Decode one station-day file -> (values|None, status, info).

    Raises SystemExit on structurally invalid payloads.
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
        if r.encoding != 11:
            raise SystemExit(f"{path.name}: encoding {r.encoding}, expected Steim2 (11)")
        if r.sample_rate != RATE:
            raise SystemExit(f"{path.name}: sample rate {r.sample_rate}, expected {RATE}")
        if not (start - 10 ** 9 <= r.start_ns < end):
            raise SystemExit(f"{path.name}: record starts outside the requested day")
    values, status, info = mseed.assemble_chain(recs, start, RATE, tol_samples=1.0)
    if values is None:
        return None, status, info
    n = len(values)
    if n < MIN_VALUES:
        return None, f"short_{n}", info
    if n > MAX_VALUES:
        return None, f"long_{n}", info
    lo, hi = min(values), max(values)
    if lo < VMIN or hi > VMAX:
        return None, f"out_of_range_{lo}_{hi}", info
    ngap = values.count(GAP)
    if ngap > MAX_GAP_FRACTION * n:
        return None, f"gap_marker_fraction_{ngap / n:.3f}", info
    if len(set(values) - {GAP}) < MIN_DISTINCT:
        return None, "degenerate", info
    return values, "accepted", info


def sample_stats(values):
    raw = struct.pack(f"<{len(values)}h", *values)
    valid = [v for v in values if v != GAP]
    cnt = collections.Counter(valid)
    mode, mode_n = cnt.most_common(1)[0]
    steps = [abs(b - a) for a, b in zip(valid, valid[1:])]
    return raw, {
        "min": min(values),
        "max": max(values),
        "gap_marker_count": len(values) - len(valid),
        "valid_min": min(valid),
        "valid_max": max(valid),
        "distinct_values": len(set(values)),
        "mode_value": mode,
        "mode_fraction": round(mode_n / len(values), 6),
        "max_abs_step_valid": max(steps) if steps else 0,
        "count_1023": cnt.get(1023, 0),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def derive(recipe: Path, dl: Path):
    plan = read_plan(recipe / "plan.tsv")
    inv = inventory_ok(dl / "xa_channels.txt")
    results = []
    counts = {}
    for sta, day in plan:
        if sta not in inv:
            raise SystemExit(f"{sta}: not an XA 00 MHZ 6.625-sps Apollo PSE channel in the inventory")
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
    inv_text = (dl / "xa_channels.txt").read_text()
    if not inv_text.startswith("#Network | Station | Location | Channel"):
        raise SystemExit("station inventory is not FDSN text")
    lic = (dl / "nasa_smd_science_information_policy.html").read_text(errors="replace")
    if "It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies" not in lic:
        raise SystemExit("NASA SMD policy page lacks the expected open-data statement")
    net = (dl / "fdsn_xa_1969.html").read_text(errors="replace")
    if "Apollo Passive Seismic Experiments" not in net or "10.7914/SN/XA_1969" not in net:
        raise SystemExit("FDSN XA_1969 network page lacks the expected Apollo PSE / DOI text")
    results, counts = derive(Path(a.recipe), dl)
    accepted = [r for r in results if r[2] is not None]
    with open(a.outcome, "w") as fh:
        fh.write("station\tday\tstatus\trecords\tvalues\n")
        for sta, day, values, status, info in results:
            fh.write(f"{sta}\t{day}\t{status}\t{info.get('records', 0)}\t{len(values) if values else 0}\n")
    stations = {r[0] for r in accepted}
    years = {r[1].year for r in accepted}
    print(f"plan_station_days={len(results)} accepted={len(accepted)} stations={sorted(stations)} "
          f"years={sorted(years)} status_counts={json.dumps(counts, sort_keys=True)}")
    if len(accepted) < MIN_ACCEPTED_TOTAL or len(stations) < 4 or len(years) < 6:
        raise SystemExit(f"only {len(accepted)} accepted station-days / {len(stations)} stations / "
                         f"{len(years)} years; payload looks wrong")


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
        "gap_marker_total": sum(r["gap_marker_count"] for r in rows),
        "aggregate_sha256": agg, "skipped": skipped,
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"samples={len(rows)} total_bytes={total} total_values={stats['total_values']} "
          f"per_station={stats['per_station']} years={stats['years']} "
          f"status_counts={json.dumps(counts, sort_keys=True)} aggregate_sha256={agg}")


def cmd_verify(a):
    root = Path(a.data_root)
    recipe = Path(a.recipe)
    manifest = tomllib.loads((recipe / "manifest.toml").read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(l) for l in index.read_text().splitlines() if l.strip()]
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows):
        raise SystemExit("duplicate sample_path in index")
    results, _ = derive(recipe, root / "downloads" / DATASET_ID)
    expected = {f"samples/{DATASET_ID}/{SERIES_ID}/{sample_name(sta, day)}": values
                for sta, day, values, status, info in results if values is not None}
    if set(expected) != set(by_path):
        raise SystemExit(f"index/sample set mismatch: expected {len(expected)} got {len(by_path)}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in out_dir.iterdir()}
    if on_disk != set(expected):
        raise SystemExit("stray or missing sample files on disk")
    total = 0
    for path, values in expected.items():
        r = by_path[path]
        data = (root / path).read_bytes()
        n = len(data) // 2
        if len(data) % 2 or n != r["value_count"] or len(data) != r["sample_size_bytes"]:
            raise SystemExit(f"{path}: size mismatch")
        if not (MIN_VALUES <= n <= MAX_VALUES):
            raise SystemExit(f"{path}: value count {n} outside the full-day window")
        stored = list(struct.unpack(f"<{n}h", data))
        if stored != values:
            raise SystemExit(f"{path}: bytes differ from re-decoded source")
        if min(stored) < VMIN or max(stored) > VMAX:
            raise SystemExit(f"{path}: value outside -1..1023")
        if stored.count(GAP) > MAX_GAP_FRACTION * n:
            raise SystemExit(f"{path}: -1 gap-marker fraction above 20%")
        if len(set(stored) - {GAP}) < MIN_DISTINCT:
            raise SystemExit(f"{path}: constant or degenerate")
        _, st = sample_stats(stored)
        for k, v in st.items():
            if r[k] != v:
                raise SystemExit(f"{path}: index field {k}={r[k]} != {v}")
        for k, v in (("numeric_kind", "int"), ("bit_width", 16), ("endianness", "little"),
                     ("element_size_bytes", 2), ("dataset_id", DATASET_ID), ("series_id", SERIES_ID)):
            if r[k] != v:
                raise SystemExit(f"{path}: index {k}={r[k]!r}")
        total += len(data)
    if series["sample_count"] != len(expected) or series["total_size_bytes"] != total:
        raise SystemExit(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
                         f"!= realized {len(expected)}/{total}")
    if total > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB")
    stations = {r["station"] for r in rows}
    years = {r["utc_day"][:4] for r in rows}
    if len(stations) < 4 or len(years) < 6:
        raise SystemExit(f"realized scope too narrow: stations={sorted(stations)} years={sorted(years)}")
    print(f"verify_ok samples={len(expected)} total_bytes={total} stations={sorted(stations)} years={sorted(years)}")


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
