#!/usr/bin/env python3
"""GoldenCheetah OpenData (OSF 6hfpz, CC0) -> per-activity cycling cadence uint8.

Subcommands:
  check-download  structural validation of the pinned athlete zips (zip CRCs,
                  one RIDES JSON member, activity CSV members and headers)
  build           emit one uint8 sample per kept cycling activity
  verify          independently re-derive every sample and check index/manifest

Each athlete zip holds '{<uuid>}.json' (VERSION, ATHLETE, RIDES: one entry per
activity with a UTC 'date', 'sport' and a 15-character 'data' presence-flag
string whose 6th character is 'C' when cadence was recorded) and one CSV per
activity named after the activity's start time in the athlete's local clock,
with columns secs,km,power,hr,cad,alt at 1 s steps. Only the 'cad' column is
read. ATHLETE demographics are never read or emitted.

Pure standard library.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import csv
import datetime
import hashlib
import io
import itertools
import json
import re
import statistics
import sys
import time
import tomllib
import zipfile
from pathlib import Path

DATASET_ID = "goldencheetah_opendata_cycling_cadence_u8"
SERIES_ID = "gc_bike_cadence_rpm_u8"
HEADER = "secs,km,power,hr,cad,alt"
CAD_COL = 4
NCOLS = 6

# Skip policy (shared by build and verify; verify re-implements it).
MIN_VALUES = 1000            # drop activities with fewer cadence values
MAX_ZERO_FRACTION = 0.90     # drop mostly-zero (sensor absent / all-zero) activities
MIN_DISTINCT = 10            # drop near-constant activities
MAX_PLATEAU_RUN = 300        # drop if one nonzero value repeats >= 300 consecutive rows
MAX_VALUE = 255
SECS_COL = 0
MIN_ONE_SECOND_STEP_FRACTION = 0.95  # time lattice: >=95% of secs deltas exactly 1
# CSV-name (local clock) to RIDES-date (UTC) matching.
OFFSET_STEP = 900            # time-zone offsets are whole quarter hours
MAX_ABS_OFFSET = 14 * 3600
# Athlete zips whose published RIDES JSON is not valid JSON (byte-identical to
# the OSF SHA-256, so an upstream defect). Without RIDES no activity can be
# matched to its sport, so these athletes are skipped whole. Any other JSON
# failure is fatal, and a listed zip that parses is also fatal.
KNOWN_BAD_RIDES_JSON = {
    "1293c64a-7388-4366-9a8c-3c7951ae61a8.zip",  # missing ',' at line 18570 col 56
}

CSV_NAME_RE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})\.csv$")
UINT_RE = re.compile(r"^[0-9]+$")


def paths(repo_root: Path, data_dir: str) -> dict[str, Path]:
    root = Path(data_dir) if Path(data_dir).is_absolute() else (repo_root / data_dir)
    root = root.resolve()
    return {
        "data": root,
        "downloads": root / "downloads" / DATASET_ID / "zips",
        "samples": root / "samples" / DATASET_ID / SERIES_ID,
        "index": root / "index" / DATASET_ID,
        "filtered": root / "filtered" / DATASET_ID,
    }


def load_sources(tsv: Path) -> list[dict]:
    lines = tsv.read_text(encoding="utf-8").splitlines()
    hdr = lines[0].split("\t")
    rows = [dict(zip(hdr, l.split("\t"))) for l in lines[1:] if l.strip()]
    for r in rows:
        r["size_bytes"] = int(r["size_bytes"])
    return rows


def athlete_json_name(zip_name: str) -> str:
    return "{" + zip_name[:-4] + "}.json"


# ------------------------------------------------------------ check-download

def cmd_check_download(args) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    sources = load_sources(Path(args.sources))
    totals = collections.Counter()
    for src in sources:
        zp = p["downloads"] / src["filename"]
        try:
            zf = zipfile.ZipFile(zp)
        except zipfile.BadZipFile as exc:
            raise SystemExit(f"{zp.name}: not a zip ({exc})")
        with zf:
            bad = zf.testzip()
            if bad is not None:
                raise SystemExit(f"{zp.name}: CRC failure in member {bad}")
            names = zf.namelist()
            jname = athlete_json_name(src["filename"])
            if jname not in names:
                raise SystemExit(f"{zp.name}: missing athlete JSON member {jname}")
            try:
                meta = json.loads(zf.read(jname))
            except json.JSONDecodeError as exc:
                if src["filename"] in KNOWN_BAD_RIDES_JSON:
                    totals["known_bad_rides_json"] += 1
                    totals["zips"] += 1
                    continue
                raise SystemExit(f"{zp.name}: RIDES JSON does not parse ({exc})")
            if src["filename"] in KNOWN_BAD_RIDES_JSON:
                raise SystemExit(f"{zp.name}: listed as known-bad JSON but parses; update KNOWN_BAD_RIDES_JSON")
            if not isinstance(meta.get("RIDES"), list):
                raise SystemExit(f"{zp.name}: JSON has no RIDES list")
            csvs = [n for n in names if n.endswith(".csv")]
            others = [n for n in names if n != jname and not n.endswith(".csv")]
            if others:
                raise SystemExit(f"{zp.name}: unexpected members {others[:5]}")
            header_bad = 0
            for n in csvs:
                with zf.open(n) as fh:
                    first = fh.readline().decode("utf-8", "replace").strip()
                if first != HEADER:
                    header_bad += 1
            totals["zips"] += 1
            totals["rides"] += len(meta["RIDES"])
            totals["csv_members"] += len(csvs)
            totals["csv_bad_header"] += header_bad
            totals["csv_bad_name"] += sum(1 for n in csvs if not CSV_NAME_RE.match(n))
    if totals["zips"] != len(sources):
        raise SystemExit("not every source zip was checked")
    print("check-download ok " + " ".join(f"{k}={v}" for k, v in sorted(totals.items())))


# --------------------------------------------------------------- build path

def ride_epoch_build(date: str) -> int | None:
    try:
        return calendar.timegm(time.strptime(date, "%Y/%m/%d %H:%M:%S UTC"))
    except (TypeError, ValueError):
        return None


def match_build(csv_names: list[str], rides: list) -> dict[str, tuple[int, int]]:
    """Return csv name -> (ride index, local-minus-UTC offset seconds)."""
    by_epoch: dict[int, list[int]] = collections.defaultdict(list)
    for i, r in enumerate(rides):
        e = ride_epoch_build(r.get("date")) if isinstance(r, dict) else None
        if e is not None:
            by_epoch[e].append(i)
    offsets = range(-MAX_ABS_OFFSET, MAX_ABS_OFFSET + 1, OFFSET_STEP)
    cands: dict[str, list[tuple[int, int]]] = {}
    for name in csv_names:
        m = CSV_NAME_RE.match(name)
        if not m:
            continue
        local = calendar.timegm(tuple(int(g) for g in m.groups()) + (0, 0, 0))
        found = []
        for off in offsets:
            for i in by_epoch.get(local - off, ()):
                found.append((i, off))
        cands[name] = found
    uniq = collections.Counter(c[0][1] for c in cands.values() if len(c) == 1)
    modal = None
    if uniq:
        modal = sorted(uniq.items(), key=lambda kv: (-kv[1], abs(kv[0]), kv[0]))[0][0]
    chosen: dict[str, tuple[int, int]] = {}
    for name, found in cands.items():
        if len(found) > 1:
            found = [c for c in found if c[1] == modal]
        if len(found) == 1:
            chosen[name] = found[0]
    claims = collections.Counter(v[0] for v in chosen.values())
    return {k: v for k, v in chosen.items() if claims[v[0]] == 1}


def parse_cad_build(raw: bytes) -> tuple[str, list[int] | None, list[int] | None]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "undecodable_csv", None, None
    lines = text.split("\n")
    if lines[0].rstrip("\r") != HEADER:
        return "bad_header", None, None
    vals: list[int] = []
    secs_cells: list[str] = []
    for line in lines[1:]:
        line = line.rstrip("\r")
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != NCOLS:
            return "malformed_row", None, None
        cell = parts[CAD_COL]
        if cell == "":
            return "empty_cadence_cell", None, None
        if not UINT_RE.match(cell):
            return "non_integer_cadence", None, None
        v = int(cell)
        if v > MAX_VALUE:
            return "cadence_above_255", None, None
        vals.append(v)
        secs_cells.append(parts[SECS_COL])
    # Time lattice: integer secs, strictly increasing, >=95% one-second steps.
    if not all(UINT_RE.match(s) for s in secs_cells):
        return "secs_not_integer", None, None
    secs = [int(s) for s in secs_cells]
    deltas = [b - a for a, b in zip(secs, secs[1:])]
    if any(d < 1 for d in deltas):
        return "secs_not_strictly_increasing", None, None
    if deltas and deltas.count(1) < MIN_ONE_SECOND_STEP_FRACTION * len(deltas):
        return "secs_step_not_1s", None, None
    return "ok", vals, secs


def quality_build(vals: list[int]) -> tuple[str, dict]:
    n = len(vals)
    if n < MIN_VALUES:
        return "short_activity", {}
    zeros = vals.count(0)
    longest, run, prev = 0, 0, None
    for v in vals:
        run = run + 1 if v == prev else 1
        prev = v
        if v and run > longest:
            longest = run
    distinct = len(set(vals))
    info = {"zero_fraction": round(zeros / n, 6), "max_nonzero_run": longest, "distinct_values": distinct}
    if zeros / n > MAX_ZERO_FRACTION:
        return "mostly_zero", info
    if distinct < MIN_DISTINCT:
        return "low_distinct", info
    if longest >= MAX_PLATEAU_RUN:
        return "constant_plateau", info
    return "ok", info


def cmd_build(args) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    sources = load_sources(Path(args.sources))
    p["samples"].mkdir(parents=True, exist_ok=True)
    p["index"].mkdir(parents=True, exist_ok=True)
    p["filtered"].mkdir(parents=True, exist_ok=True)
    for old in p["samples"].glob("*.bin"):
        old.unlink()

    reasons = collections.Counter()
    seen_hashes: set[str] = set()
    index_rows = []
    per_athlete = []
    for src in sources:
        zname = src["filename"]
        athlete = zname[:-4]
        kept_here = 0
        a_reasons = collections.Counter()
        if zname in KNOWN_BAD_RIDES_JSON:
            reasons["athlete_skipped_malformed_rides_json"] += 1
            per_athlete.append({"athlete": athlete, "zip_bytes": src["size_bytes"], "kept": 0,
                                "skipped": {"malformed_rides_json": 1}})
            continue
        candidates = []
        with zipfile.ZipFile(p["downloads"] / zname) as zf:
            meta = json.loads(zf.read(athlete_json_name(zname)))
            rides = meta["RIDES"]
            csv_names = sorted(n for n in zf.namelist() if n.endswith(".csv"))
            matched = match_build(csv_names, rides)
            for name in csv_names:
                reasons["csv_members"] += 1
                if not CSV_NAME_RE.match(name):
                    a_reasons["bad_csv_name"] += 1
                    continue
                if name not in matched:
                    a_reasons["unmatched_ride"] += 1
                    continue
                ride_i, off = matched[name]
                ride = rides[ride_i]
                if ride.get("sport") != "Bike":
                    a_reasons["not_bike"] += 1
                    continue
                flags = ride.get("data")
                if not isinstance(flags, str) or len(flags) < 6 or flags[5] != "C":
                    a_reasons["no_cadence_flag"] += 1
                    continue
                status, vals, secs = parse_cad_build(zf.read(name))
                if status != "ok":
                    a_reasons[status] += 1
                    continue
                status, info = quality_build(vals)
                if status != "ok":
                    a_reasons[status] += 1
                    continue
                start = ride_epoch_build(ride["date"])
                candidates.append((start, name, off, ride, vals, secs, info))
        # Same-athlete overlap rule (dual-device recordings of one ride).
        candidates.sort(key=lambda c: (c[0], c[1]))
        latest_end = None
        for start, name, off, ride, vals, secs, info in candidates:
            if latest_end is not None and start < latest_end:
                a_reasons["overlapping_recording"] += 1
                continue
            end = start + secs[-1]
            latest_end = end if latest_end is None else max(latest_end, end)
            payload = bytes(vals)
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_hashes:
                a_reasons["duplicate_payload"] += 1
                continue
            seen_hashes.add(digest)
            rel = Path("samples") / DATASET_ID / SERIES_ID / f"{athlete}__{name[:-4]}.bin"
            (p["data"] / rel).write_bytes(payload)
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": rel.as_posix(),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(payload),
                "value_count": len(payload),
                "athlete": athlete,
                "activity_csv": name,
                "ride_date_utc": ride["date"],
                "local_minus_utc_seconds": off,
                "min": min(payload),
                "max": max(payload),
                "sha256": digest,
                "secs_last": secs[-1],
                "secs_gap_count": sum(1 for a, b in zip(secs, secs[1:]) if b - a > 1),
                **info,
            })
            kept_here += 1
        reasons.update(a_reasons)
        per_athlete.append({"athlete": athlete, "zip_bytes": src["size_bytes"], "kept": kept_here,
                            "skipped": dict(a_reasons)})

    with open(p["index"] / "samples.jsonl", "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    sizes = [r["value_count"] for r in index_rows]
    stats = {
        "dataset_id": DATASET_ID,
        "athlete_zips": len(sources),
        "athletes_with_kept_activities": sum(1 for a in per_athlete if a["kept"]),
        "sample_count": len(index_rows),
        "total_values": sum(sizes),
        "median_values": statistics.median(sizes) if sizes else 0,
        "max_kept_per_athlete": max((a["kept"] for a in per_athlete), default=0),
        "skip_reasons": dict(sorted(reasons.items())),
        "per_athlete": per_athlete,
    }
    (p["filtered"] / "ingest_stats.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "per_athlete"}, indent=1))


# --------------------------------------------------------------- verify path
# Deliberately separate: datetime-based O(n*m) matching, csv-module parsing,
# itertools.groupby run lengths, byte-for-byte comparison against disk.

def verify_match(csv_names, rides):
    ride_dt = []
    for r in rides:
        try:
            ride_dt.append(datetime.datetime.strptime(r["date"], "%Y/%m/%d %H:%M:%S UTC"))
        except (KeyError, TypeError, ValueError):
            ride_dt.append(None)
    options = {}
    for name in csv_names:
        try:
            if len(name) != 23:
                raise ValueError
            local = datetime.datetime.strptime(name, "%Y_%m_%d_%H_%M_%S.csv")
        except ValueError:
            continue
        opts = []
        for i, u in enumerate(ride_dt):
            if u is None:
                continue
            delta = local - u
            secs = delta.days * 86400 + delta.seconds
            if -MAX_ABS_OFFSET <= secs <= MAX_ABS_OFFSET and secs % OFFSET_STEP == 0:
                opts.append((i, secs))
        options[name] = opts
    single = [o[0][1] for o in options.values() if len(o) == 1]
    best = None
    if single:
        counts = collections.Counter(single)
        top = max(counts.values())
        best = min((o for o, c in counts.items() if c == top), key=lambda o: (abs(o), o))
    picks = {}
    for name, opts in options.items():
        if len(opts) == 1:
            picks[name] = opts[0]
        elif len(opts) > 1:
            m = [o for o in opts if o[1] == best]
            if len(m) == 1:
                picks[name] = m[0]
    users = collections.defaultdict(list)
    for name, (i, _) in picks.items():
        users[i].append(name)
    return {name: v for name, v in picks.items() if len(users[v[0]]) == 1}


def verify_activity(raw: bytes):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        head = next(reader)
    except StopIteration:
        return None
    if ",".join(head) != HEADER:
        return None
    out = bytearray()
    times: list[int] = []
    for row in reader:
        if not row:
            continue
        if len(row) != NCOLS:
            return None
        cell = row[CAD_COL]
        if not cell or not cell.isascii() or not cell.isdigit():
            return None
        v = int(cell)
        if v > MAX_VALUE:
            return None
        out.append(v)
        tcell = row[0]
        if not tcell or not tcell.isascii() or not tcell.isdigit():
            return None
        times.append(int(tcell))
    ones = 0
    for a, b in itertools.pairwise(times):
        if b <= a:
            return None
        ones += (b - a == 1)
    steps = len(times) - 1
    if steps > 0 and ones * 100 < 95 * steps:
        return None
    payload = bytes(out)
    if len(payload) < MIN_VALUES:
        return None
    if payload.count(0) > MAX_ZERO_FRACTION * len(payload):
        return None
    if len(set(payload)) < MIN_DISTINCT:
        return None
    if any(k != 0 and sum(1 for _ in g) >= MAX_PLATEAU_RUN for k, g in itertools.groupby(payload)):
        return None
    return payload, times


def cmd_verify(args) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    sources = load_sources(Path(args.sources))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("verify: manifest must declare the primary series exactly once")
    series = series[0]

    expected: dict[str, tuple[bytes, dict]] = {}
    digests: set[bytes] = set()
    for src in sources:
        zname = src["filename"]
        with zipfile.ZipFile(p["downloads"] / zname) as zf:
            jraw = zf.read("{" + zname.removesuffix(".zip") + "}.json")
            try:
                json.loads(jraw)
            except ValueError:
                if zname in KNOWN_BAD_RIDES_JSON:
                    continue
                raise SystemExit(f"verify: {zname} RIDES JSON does not parse")
            if zname in KNOWN_BAD_RIDES_JSON:
                raise SystemExit(f"verify: {zname} listed as malformed but parses")
            rides = json.loads(zf.read("{" + zname.removesuffix(".zip") + "}.json"))["RIDES"]
            names = sorted(n for n in zf.namelist() if n.endswith(".csv"))
            picks = verify_match(names, rides)
            survivors = []
            for name in names:
                if name not in picks:
                    continue
                ride = rides[picks[name][0]]
                if ride.get("sport") != "Bike" or str(ride.get("data", ""))[5:6] != "C":
                    continue
                got = verify_activity(zf.read(name))
                if got is None:
                    continue
                t0 = datetime.datetime.strptime(ride["date"], "%Y/%m/%d %H:%M:%S UTC")
                survivors.append((t0, name, ride, picks[name][1], got[0], got[1]))
        # Overlap rule: chronological, keep only starts at/after every kept end.
        frontier = None
        for t0, name, ride, off, payload, times in sorted(survivors, key=lambda s: (s[0], s[1])):
            if frontier is not None and t0 < frontier:
                continue
            t1 = t0 + datetime.timedelta(seconds=times[-1])
            if frontier is None or t1 > frontier:
                frontier = t1
            d = hashlib.sha256(payload).digest()
            if d in digests:
                continue
            digests.add(d)
            rel = f"samples/{DATASET_ID}/{SERIES_ID}/{zname.removesuffix('.zip')}__{name.removesuffix('.csv')}.bin"
            gaps = sum(1 for a, b in itertools.pairwise(times) if b - a != 1)
            expected[rel] = (payload, {"ride_date_utc": ride["date"], "local_minus_utc_seconds": off,
                                       "secs_last": times[-1], "secs_gap_count": gaps})

    index_rows = [json.loads(l) for l in (p["index"] / "samples.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    indexed = {r["sample_path"]: r for r in index_rows}
    if len(indexed) != len(index_rows):
        raise SystemExit("verify: duplicate sample_path rows in index")
    if set(indexed) != set(expected):
        miss = sorted(set(expected) - set(indexed))[:5]
        extra = sorted(set(indexed) - set(expected))[:5]
        raise SystemExit(f"verify: index/sample set mismatch missing={miss} extra={extra} "
                         f"(expected {len(expected)}, indexed {len(indexed)})")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{f.name}" for f in p["samples"].iterdir()}
    if on_disk != set(expected):
        raise SystemExit(f"verify: stray or missing sample files: {sorted(on_disk ^ set(expected))[:5]}")

    total = 0
    sizes = []
    for rel, (payload, extra) in sorted(expected.items()):
        row = indexed[rel]
        if (p["data"] / rel).read_bytes() != payload:
            raise SystemExit(f"verify: {rel} differs from independent re-derivation")
        want = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(payload),
            "value_count": len(payload), "min": min(payload), "max": max(payload),
            "distinct_values": len(set(payload)), "sha256": hashlib.sha256(payload).hexdigest(), **extra,
        }
        for k, v in want.items():
            if row.get(k) != v:
                raise SystemExit(f"verify: {rel} index {k}={row.get(k)!r} expected {v!r}")
        if row["min"] == row["max"]:
            raise SystemExit(f"verify: {rel} constant")
        total += len(payload)
        sizes.append(len(payload))

    if not sizes:
        raise SystemExit("verify: no samples")
    med = statistics.median(sizes)
    if total < 10_000 or med < 1000:
        raise SystemExit(f"verify: below floor total={total} median={med}")
    if series["sample_count"] != len(sizes) or series["total_size_bytes"] != total:
        raise SystemExit(f"verify: manifest sample_count/total_size_bytes {series['sample_count']}/"
                         f"{series['total_size_bytes']} != realized {len(sizes)}/{total}")
    if total > 1_000_000_000:
        raise SystemExit("verify: primary output above 1 GB cap")
    athletes = collections.Counter(r["athlete"] for r in index_rows)
    print(f"verify ok samples={len(sizes)} total_values={total} median_values={med} "
          f"athletes={len(athletes)} max_per_athlete={max(athletes.values())}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check-download", "build", "verify"])
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest")
    args = ap.parse_args()
    {"check-download": cmd_check_download, "build": cmd_build, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
