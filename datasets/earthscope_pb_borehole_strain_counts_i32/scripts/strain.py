#!/usr/bin/env python3
"""PB Gladwin tensor strainmeter LS1-LS4 gauge-day extraction.

Subcommands:
  validate  check downloaded miniSEED station-day files (download.sh)
  build     emit one little-endian int32 sample per complete gauge-channel UTC day
  verify    re-derive every sample from the downloads and check index/manifest
"""
from __future__ import annotations

import argparse
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

DATASET_ID = "earthscope_pb_borehole_strain_counts_i32"
SERIES_ID = "pb_gtsm_ls_gauge_counts_i32"
CHANNELS = ("LS1", "LS2", "LS3", "LS4")
NDAY = 86400
FILL = 999999
MAX_FILL = 864  # 1% of a day
MIN_DISTINCT = 16
MIN_COMPLETE_TOTAL = 300


def read_plan(path: Path):
    rows = []
    lines = path.read_text().splitlines()
    if lines[0] != "station\tday":
        raise SystemExit("plan.tsv header mismatch")
    for line in lines[1:]:
        sta, day = line.split("\t")
        rows.append((sta, dt.date.fromisoformat(day)))
    if len(set(rows)) != len(rows):
        raise SystemExit("duplicate plan rows")
    return rows


def mseed_path(dl: Path, sta: str, day: dt.date) -> Path:
    return dl / "mseed" / f"PB.{sta}.T0.LS_.{day.isoformat()}.mseed"


def day_ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()) * 1_000_000_000


def gladwin_stations(inventory: Path):
    ok = set()
    for line in inventory.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = [x.strip() for x in line.split("|")]
        if f[0] == "PB" and f[2] == "T0" and f[3] in CHANNELS and float(f[14]) == 1.0 \
                and f[10].startswith("GLADWIN TENSOR STRAINMETER"):
            ok.add((f[1], f[3]))
    return ok


def classify(path: Path, sta: str, day: dt.date):
    """Decode one station-day file; return {channel: (values|None, status)}.

    Raises SystemExit on structurally invalid payloads (wrong stream identity,
    unsupported encoding, Steim integration-constant mismatch, truncation).
    """
    buf = path.read_bytes()
    by_cha = {c: [] for c in CHANNELS}
    if buf:
        try:
            recs = list(mseed.iter_records(buf))
        except mseed.MseedError as exc:
            raise SystemExit(f"{path.name}: invalid miniSEED: {exc}")
        for r in recs:
            if (r.network, r.station, r.location) != ("PB", sta, "T0") or r.channel not in CHANNELS:
                raise SystemExit(f"{path.name}: unexpected stream {r.network}.{r.station}.{r.location}.{r.channel}")
            if r.encoding != 11:
                raise SystemExit(f"{path.name}: {r.channel} encoding {r.encoding}, expected Steim2 (11)")
            by_cha[r.channel].append(r)
    out = {}
    start = day_ns(day)
    for c in CHANNELS:
        values, status = mseed.assemble_day(by_cha[c], start, 1.0)
        if values is not None:
            nfill = values.count(FILL)
            if nfill > MAX_FILL:
                values, status = None, f"fill_{nfill}"
            elif len(set(v for v in values if v != FILL)) < MIN_DISTINCT:
                values, status = None, "degenerate"
            elif min(values) < -2**31 or max(values) >= 2**31:
                raise SystemExit(f"{path.name}: {c} value outside int32")
        out[c] = (values, status, len(by_cha[c]))
    return out


def sample_stats(values):
    nonfill = [v for v in values if v != FILL]
    steps = [abs(b - a) for a, b in zip(nonfill, nonfill[1:])]
    raw = struct.pack(f"<{len(values)}i", *values)
    return raw, {
        "min": min(values),
        "max": max(values),
        "fill_999999_count": len(values) - len(nonfill),
        "nonfill_min": min(nonfill),
        "nonfill_max": max(nonfill),
        "max_abs_step": max(steps) if steps else 0,
        "distinct_values": len(set(values)),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def derive(recipe: Path, dl: Path, log=print):
    plan = read_plan(recipe / "plan.tsv")
    inv = gladwin_stations(dl / "pb_ls_channels.txt")
    results = []
    status_counts = {}
    for sta, day in plan:
        p = mseed_path(dl, sta, day)
        if not p.exists():
            raise SystemExit(f"missing download {p}")
        for c, (values, status, nrec) in classify(p, sta, day).items():
            if (sta, c) not in inv:
                raise SystemExit(f"{sta}.{c} is not a 1-sps Gladwin T0 channel in the inventory")
            key = re.sub(r"_[-0-9.]+.*$", "", status)
            status_counts[key] = status_counts.get(key, 0) + 1
            results.append((sta, day, c, values, status, nrec))
    return results, status_counts


def cmd_validate(a):
    dl = Path(a.downloads)
    plan = read_plan(Path(a.recipe) / "plan.tsv")
    inv_text = (dl / "pb_ls_channels.txt").read_text()
    if not inv_text.startswith("#Network | Station | Location | Channel"):
        raise SystemExit("station inventory is not FDSN text")
    lic = (dl / "gage_data_license.html").read_text(errors="replace")
    if "Creative Commons Attribution 4.0" not in lic or "EarthScope operated facilities" not in lic:
        raise SystemExit("license page lacks the expected CC BY 4.0 statement")
    results, counts = derive(Path(a.recipe), dl)
    complete = sum(1 for r in results if r[3] is not None)
    with open(a.outcome, "w") as fh:
        fh.write("station\tday\tchannel\tstatus\trecords\n")
        for sta, day, c, values, status, nrec in results:
            fh.write(f"{sta}\t{day}\t{c}\t{status}\t{nrec}\n")
    print(f"plan_station_days={len(plan)} gauge_days={len(results)} complete={complete} status_counts={json.dumps(counts, sort_keys=True)}")
    if complete < MIN_COMPLETE_TOTAL:
        raise SystemExit(f"only {complete} complete gauge-days (< {MIN_COMPLETE_TOTAL}); payload looks wrong")


def cmd_build(a):
    root = Path(a.data_root)
    dl = root / "downloads" / DATASET_ID
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"
    for d in (out_dir, index.parent, stats_path.parent):
        d.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.i32"):
        old.unlink()
    results, counts = derive(Path(a.recipe), dl)
    rows = []
    skipped = []
    total = 0
    for sta, day, c, values, status, nrec in results:
        if values is None:
            skipped.append({"station": sta, "day": day.isoformat(), "channel": c, "status": status})
            continue
        raw, st = sample_stats(values)
        name = f"PB.{sta}.T0.{c}.{day.strftime('%Y%m%d')}.i32"
        (out_dir / name).write_bytes(raw)
        total += len(raw)
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{name}",
            "numeric_kind": "int", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "sample_size_bytes": len(raw), "value_count": len(values),
            "network": "PB", "station": sta, "location": "T0", "channel": c,
            "utc_day": day.isoformat(), "sample_rate_hz": 1.0, "source_records": nrec, **st,
        })
    with open(index, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    agg = hashlib.sha256("".join(r["sha256"] for r in rows).encode()).hexdigest()
    stats = {
        "dataset_id": DATASET_ID, "plan_station_days": len(results) // 4, "gauge_days_considered": len(results),
        "samples": len(rows), "total_bytes": total, "status_counts": counts,
        "stations": len({r["station"] for r in rows}), "years": sorted({r["utc_day"][:4] for r in rows}),
        "fill_999999_total": sum(r["fill_999999_count"] for r in rows),
        "aggregate_sha256": agg, "skipped": skipped,
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"samples={len(rows)} total_bytes={total} stations={stats['stations']} years={stats['years'][0]}..{stats['years'][-1]} "
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
    expected = {}
    for sta, day, c, values, status, nrec in results:
        if values is not None:
            expected[f"samples/{DATASET_ID}/{SERIES_ID}/PB.{sta}.T0.{c}.{day.strftime('%Y%m%d')}.i32"] = values
    if set(expected) != set(by_path):
        raise SystemExit(f"index/sample set mismatch: expected {len(expected)} got {len(by_path)}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in out_dir.iterdir()}
    if on_disk != set(expected):
        raise SystemExit("stray or missing sample files on disk")
    total = 0
    for path, values in expected.items():
        r = by_path[path]
        data = (root / path).read_bytes()
        n = len(data) // 4
        if len(data) != NDAY * 4 or n != r["value_count"] or len(data) != r["sample_size_bytes"]:
            raise SystemExit(f"{path}: size mismatch")
        stored = list(struct.unpack(f"<{n}i", data))
        if stored != values:
            raise SystemExit(f"{path}: bytes differ from re-decoded source")
        if len(set(stored)) < 2 or len(set(v for v in stored if v != FILL)) < MIN_DISTINCT:
            raise SystemExit(f"{path}: constant or degenerate")
        if stored.count(FILL) > MAX_FILL:
            raise SystemExit(f"{path}: fill fraction too high")
        _, st = sample_stats(stored)
        for k, v in st.items():
            if r[k] != v:
                raise SystemExit(f"{path}: index field {k}={r[k]} != {v}")
        for k, v in (("numeric_kind", "int"), ("bit_width", 32), ("endianness", "little"), ("element_size_bytes", 4),
                     ("dataset_id", DATASET_ID), ("series_id", SERIES_ID)):
            if r[k] != v:
                raise SystemExit(f"{path}: index {k}={r[k]!r}")
        total += len(data)
    if series["sample_count"] != len(expected) or series["total_size_bytes"] != total:
        raise SystemExit(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
                         f"!= realized {len(expected)}/{total}")
    if total > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB")
    stations = {r["station"] for r in rows}
    if len(stations) < 20:
        raise SystemExit(f"only {len(stations)} stations realized")
    print(f"verify_ok samples={len(expected)} total_bytes={total} stations={len(stations)}")


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
