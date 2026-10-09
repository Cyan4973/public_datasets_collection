#!/usr/bin/env python3
"""NRCS SNOTEL hourly snow depth (SNWD) -> per station-water-year uint8 samples.

Subcommands:
  check  FILE STATION_ID STATE   classify one downloaded reportGenerator CSV
                                 (prints "data <rows>" or "nodata"; exit 2 if invalid)
  build                          emit samples, index and stats from local files only
  verify                         independently re-derive everything and compare
  selftest                       run the parser on synthetic inputs

Pure standard library. Inclusion rules are fixed up front (see RULES below)
and implemented twice: once in build, once (independently) in verify.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import statistics
import struct
import sys
import tempfile
import tomllib
from pathlib import Path

DATASET_ID = "nrcs_snotel_hourly_snow_depth_u8"
PRIMARY = "snotel_snwd_hourly_u8"
AUX = "snotel_snwd_hour_offset_u16"
HEADER = "Date,Snow Depth (in)"
WATER_YEARS = (2022, 2023, 2024)
RANGE_START = "2021-10-01 00:00"
RANGE_END = "2024-09-30 23:00"
# Fixed inclusion rules, applied per station-water-year in this order:
MIN_VALID_HOURS = 1000          # fewer valid hours -> too_few_hours
VALUE_MIN, VALUE_MAX = 0, 255   # any value outside -> out_of_range (excluded, never clamped)
MAX_MODE_SHARE = 0.80           # most frequent value above this share -> mode_dominated
MIN_STATION_YEARS = 50          # recipe-level sanity floor

ROW_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}),(-?\d+(?:\.\d+)?)?$")


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------- check
def classify(path: Path, sid: str, state: str) -> tuple[str, int]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#"):
        raise ValueError("does not start with a reportGenerator comment block")
    comments = [ln for ln in lines if ln.startswith("#")]
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    ctext = "\n".join(comments)
    if "Natural Resources Conservation Service" not in ctext:
        raise ValueError("comment block lacks the NRCS reportGenerator banner")
    if not body:
        # Comment-only reply: either the hourly report for this triplet does not
        # exist ("Stations do not exist ...") or it has no rows at all.
        if f"Stations do not exist  {sid}:{state}:SNTL" in ctext or "Reporting Frequency: Hourly" in ctext:
            return "nodata", 0
        raise ValueError("comment-only reply without a recognised no-data marker")
    if "Reporting Frequency: Hourly" not in ctext:
        raise ValueError("comment block lacks 'Reporting Frequency: Hourly'")
    if body[0] != HEADER:
        raise ValueError(f"unexpected header {body[0]!r}")
    if len(body) == 1:
        return "nodata", 0  # header only: station has no hourly SNWD in the range
    if f"({sid})" not in ctext or "SNOTEL Site" not in ctext:
        raise ValueError("comment block does not name this SNOTEL site")
    if f"Date Range: {RANGE_START} to {RANGE_END}" not in ctext:
        raise ValueError("comment block does not confirm the requested date range")
    rows = body[1:]
    for ln in rows:
        m = ROW_RE.match(ln)
        if not m:
            raise ValueError(f"malformed data row {ln[:60]!r}")
        stamp = ln[:16]
        if not (RANGE_START <= stamp <= RANGE_END):
            raise ValueError(f"row outside requested range {stamp}")
    return "data", len(rows)


def cmd_check(args: argparse.Namespace) -> int:
    try:
        kind, n = classify(Path(args.file), args.station_id, args.state)
    except ValueError as exc:
        print(f"invalid {exc}")
        return 2
    print(kind if kind == "nodata" else f"{kind} {n}")
    return 0


# --------------------------------------------------------------- paths/io
def paths(repo_root: str, data_dir: str) -> dict[str, Path]:
    root = Path(repo_root) / data_dir
    return {
        "root": root,
        "dl": root / "downloads" / DATASET_ID,
        "hourly": root / "downloads" / DATASET_ID / "hourly",
        "samples": root / "samples" / DATASET_ID,
        "index": root / "index" / DATASET_ID,
        "filtered": root / "filtered" / DATASET_ID,
    }


def read_plan(dl: Path) -> list[dict]:
    plan = dl / "download_plan.tsv"
    if not plan.is_file():
        raise SystemExit(f"missing {plan}; run download.sh first")
    with plan.open(newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    if not rows:
        raise SystemExit("empty download plan")
    return rows


def sample_name(state: str, sid: str, wy: int) -> str:
    return f"{state}_{int(sid):04d}_wy{wy}.bin"


# --------------------------------------------------------------------- build
def build_parse(path: Path) -> tuple[dict[int, list[tuple[int, str]]], str | None]:
    """Return {water_year: [(hour_offset, value_text), ...]} and a station-level error."""
    by_wy: dict[int, list[tuple[int, str]]] = collections.defaultdict(list)
    prev = None
    seen_header = False
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            if not seen_header:
                if line != HEADER:
                    raise SystemExit(f"{path}: bad header {line!r}")
                seen_header = True
                continue
            m = ROW_RE.match(line)
            if not m:
                raise SystemExit(f"{path}: malformed row {line!r}")
            y, mo, d, h, mi, val = m.groups()
            stamp = dt.datetime(int(y), int(mo), int(d), int(h), int(mi))
            if prev is not None and stamp <= prev:
                return {}, "non_monotonic_timestamps"
            prev = stamp
            wy = stamp.year + 1 if stamp.month >= 10 else stamp.year
            if wy not in WATER_YEARS:
                raise SystemExit(f"{path}: row outside WY2022-2024 {line!r}")
            if val is None or val == "":
                continue  # missing hour: dropped
            delta = stamp - dt.datetime(wy - 1, 10, 1)
            secs = delta.days * 86400 + delta.seconds
            if secs % 3600:
                by_wy[wy].append((-1, val))  # off the hourly lattice
            else:
                by_wy[wy].append((secs // 3600, val))
    return by_wy, None


def build_decide(entries: list[tuple[int, str]]) -> tuple[str, list[int], list[int]]:
    if len(entries) < MIN_VALID_HOURS:
        return "too_few_hours", [], []
    values: list[int] = []
    offsets: list[int] = []
    for off, txt in entries:
        if off < 0:
            return "off_hour_lattice", [], []
        f = float(txt)
        if f != int(f):
            return "non_integral", [], []
        v = int(f)
        if v < VALUE_MIN or v > VALUE_MAX:
            return "out_of_range", [], []
        values.append(v)
        offsets.append(off)
    counts = collections.Counter(values)
    if len(counts) < 2:
        return "constant", [], []
    if max(counts.values()) / len(values) > MAX_MODE_SHARE:
        return "mode_dominated", [], []
    return "included", values, offsets


def cmd_build(args: argparse.Namespace) -> int:
    p = paths(args.repo_root, args.data_dir)
    plan = read_plan(p["dl"])
    for key in ("samples", "index", "filtered"):
        p[key].mkdir(parents=True, exist_ok=True)
    for sub in (PRIMARY, AUX):
        d = p["samples"] / sub
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.bin"):
            old.unlink()
    index_rows: list[dict] = []
    stats_rows: list[list] = []
    reasons: collections.Counter = collections.Counter()
    stations_with_data = 0
    for row in sorted(plan, key=lambda r: (r["state"], int(r["station_id"]))):
        sid, state, status = row["station_id"], row["state"], row["status"]
        if status != "data":
            reasons["station_no_hourly_snwd"] += 1
            stats_rows.append([sid, state, "", 0, "station_no_hourly_snwd", "", "", "", ""])
            continue
        stations_with_data += 1
        src = p["hourly"] / row["file"]
        by_wy, err = build_parse(src)
        for wy in WATER_YEARS:
            entries = by_wy.get(wy, [])
            if err:
                reason, values, offsets = err, [], []
            else:
                reason, values, offsets = build_decide(entries)
            reasons[reason] += 1
            if reason != "included":
                stats_rows.append([sid, state, wy, len(entries), reason, "", "", "", ""])
                continue
            name = sample_name(state, sid, wy)
            prim = bytes(values)
            aux = struct.pack(f"<{len(offsets)}H", *offsets)
            (p["samples"] / PRIMARY / name).write_bytes(prim)
            (p["samples"] / AUX / name).write_bytes(aux)
            counts = collections.Counter(values)
            mode_v, mode_n = counts.most_common(1)[0]
            zero_share = counts.get(0, 0) / len(values)
            stats_rows.append([sid, state, wy, len(values), reason, min(values), max(values),
                               f"{mode_n / len(values):.6f}", f"{zero_share:.6f}"])
            common = {"dataset_id": DATASET_ID, "station_id": sid, "state": state, "water_year": wy,
                      "endianness": "little", "value_count": len(values)}
            index_rows.append({**common, "series_id": PRIMARY, "role": "primary",
                               "sample_path": f"samples/{DATASET_ID}/{PRIMARY}/{name}",
                               "numeric_kind": "uint", "bit_width": 8, "element_size_bytes": 1,
                               "sample_size_bytes": len(prim), "min": min(values), "max": max(values),
                               "mode_value": mode_v, "mode_share": round(mode_n / len(values), 6),
                               "zero_share": round(zero_share, 6),
                               "sha256": hashlib.sha256(prim).hexdigest()})
            index_rows.append({**common, "series_id": AUX, "role": "auxiliary",
                               "sample_path": f"samples/{DATASET_ID}/{AUX}/{name}",
                               "numeric_kind": "uint", "bit_width": 16, "element_size_bytes": 2,
                               "sample_size_bytes": len(aux), "min": min(offsets), "max": max(offsets),
                               "sha256": hashlib.sha256(aux).hexdigest()})
    with (p["index"] / "samples.jsonl").open("w") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    with (p["filtered"] / "station_year_stats.tsv").open("w") as fh:
        fh.write("station_id\tstate\twater_year\tvalid_hours\tdecision\tmin\tmax\tmode_share\tzero_share\n")
        for r in stats_rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    prim_rows = [r for r in index_rows if r["series_id"] == PRIMARY]
    aux_rows = [r for r in index_rows if r["series_id"] == AUX]
    summary = {
        "stations_in_plan": len(plan),
        "stations_with_hourly_snwd": stations_with_data,
        "decisions": dict(sorted(reasons.items())),
        "primary_samples": len(prim_rows),
        "primary_values": sum(r["value_count"] for r in prim_rows),
        "primary_bytes": sum(r["sample_size_bytes"] for r in prim_rows),
        "aux_bytes": sum(r["sample_size_bytes"] for r in aux_rows),
        "median_values": statistics.median(r["value_count"] for r in prim_rows) if prim_rows else 0,
        "states": dict(sorted(collections.Counter(r["state"] for r in prim_rows).items())),
        "water_years": dict(sorted(collections.Counter(str(r["water_year"]) for r in prim_rows).items())),
    }
    (p["filtered"] / "build_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    log(json.dumps(summary, sort_keys=True))
    if len(prim_rows) < MIN_STATION_YEARS:
        raise SystemExit(f"only {len(prim_rows)} station-years included")
    return 0


# -------------------------------------------------------------------- verify
def verify_expected(src: Path) -> dict[int, tuple[str, bytes, bytes]]:
    """Independent re-derivation using csv + string slicing + ordinal arithmetic."""
    text = src.read_text(encoding="utf-8")
    body = [ln for ln in text.splitlines() if ln and ln[0] != "#"]
    assert body and body[0] == HEADER, f"{src}: header"
    epoch = {wy: dt.date(wy - 1, 10, 1).toordinal() for wy in WATER_YEARS}
    per: dict[int, list[tuple[int, str]]] = {wy: [] for wy in WATER_YEARS}
    last = -1
    monotonic = True
    for rec in csv.reader(io.StringIO("\n".join(body[1:]))):
        assert len(rec) == 2, f"{src}: field count {rec}"
        stamp, val = rec
        d = dt.date.fromisoformat(stamp[:10])
        hh, mm = int(stamp[11:13]), int(stamp[14:16])
        absolute_minutes = (d.toordinal() * 24 + hh) * 60 + mm
        if absolute_minutes <= last:
            monotonic = False
        last = absolute_minutes
        wy = d.year + (1 if d.month > 9 else 0)
        assert wy in per, f"{src}: water year {wy}"
        if val.strip() == "":
            continue
        minutes = absolute_minutes - epoch[wy] * 24 * 60
        per[wy].append((minutes, val))
    out: dict[int, tuple[str, bytes, bytes]] = {}
    for wy, entries in per.items():
        if not monotonic:
            out[wy] = ("non_monotonic_timestamps", b"", b"")
            continue
        if len(entries) < MIN_VALID_HOURS:
            out[wy] = ("too_few_hours", b"", b"")
            continue
        if any(m % 60 for m, _ in entries):
            out[wy] = ("off_hour_lattice", b"", b"")
            continue
        nums = [float(v) for _, v in entries]
        if any(not x.is_integer() for x in nums):
            out[wy] = ("non_integral", b"", b"")
            continue
        ints = [int(x) for x in nums]
        if min(ints) < VALUE_MIN or max(ints) > VALUE_MAX:
            out[wy] = ("out_of_range", b"", b"")
            continue
        hist = [0] * 256
        for v in ints:
            hist[v] += 1
        if sum(1 for c in hist if c) < 2:
            out[wy] = ("constant", b"", b"")
            continue
        if max(hist) > MAX_MODE_SHARE * len(ints):
            out[wy] = ("mode_dominated", b"", b"")
            continue
        aux = b"".join((m // 60).to_bytes(2, "little") for m, _ in entries)
        out[wy] = ("included", bytes(ints), aux)
    return out


def cmd_verify(args: argparse.Namespace) -> int:
    p = paths(args.repo_root, args.data_dir)
    plan = read_plan(p["dl"])
    pinned = set()
    with open(args.stations, newline="") as fh:
        for r in csv.DictReader(fh):
            pinned.add((r["Station Id"], r["State Code"]))
    plan_keys = {(r["station_id"], r["state"]) for r in plan}
    assert plan_keys == pinned, "download plan does not cover exactly the pinned SNTL station list"

    expected: dict[tuple[str, str], tuple[bytes, bytes]] = {}
    decisions: collections.Counter = collections.Counter()
    for r in plan:
        src = p["hourly"] / r["file"]
        if r["status"] == "nodata":
            assert not src.exists() or classify(src, r["station_id"], r["state"])[0] == "nodata"
            decisions["station_no_hourly_snwd"] += 1
            continue
        assert r["status"] == "data", r
        assert hashlib.sha256(src.read_bytes()).hexdigest() == r["sha256"], f"{src}: sha256 changed"
        for wy, (decision, prim, aux) in verify_expected(src).items():
            decisions[decision] += 1
            if decision == "included":
                expected[(PRIMARY, sample_name(r["state"], r["station_id"], wy))] = prim
                expected[(AUX, sample_name(r["state"], r["station_id"], wy))] = aux

    index = [json.loads(ln) for ln in (p["index"] / "samples.jsonl").read_text().splitlines() if ln]
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                "element_size_bytes", "sample_size_bytes", "value_count"]
    seen = set()
    for row in index:
        for k in required:
            assert k in row, f"index row missing {k}"
        assert row["dataset_id"] == DATASET_ID and row["endianness"] == "little"
        key = (row["series_id"], Path(row["sample_path"]).name)
        assert key in expected, f"unexpected sample {row['sample_path']}"
        assert key not in seen, f"duplicate index row {key}"
        seen.add(key)
        data = (p["root"] / row["sample_path"]).read_bytes()
        assert data == expected[key], f"{row['sample_path']}: bytes differ from re-derivation"
        assert len(data) == row["sample_size_bytes"] == row["value_count"] * row["element_size_bytes"]
        if row["series_id"] == PRIMARY:
            assert row["bit_width"] == 8 and row["numeric_kind"] == "uint"
            assert row["min"] == min(data) and row["max"] == max(data)
        else:
            assert row["bit_width"] == 16 and row["numeric_kind"] == "uint"
    assert seen == set(expected), f"{len(set(expected) - seen)} expected samples missing from index"
    for sub in (PRIMARY, AUX):
        on_disk = {f.name for f in (p["samples"] / sub).glob("*")}
        want = {name for s, name in expected if s == sub}
        assert on_disk == want, f"{sub}: stray or missing files on disk"

    prim = {name: b for (s, name), b in expected.items() if s == PRIMARY}
    n = len(prim)
    assert n >= MIN_STATION_YEARS, f"only {n} station-years"
    sizes = sorted(len(b) for b in prim.values())
    total = sum(sizes)
    assert total >= 10_000 and statistics.median(sizes) >= 1000, "below repository floor"
    mode_shares, zero_shares = [], []
    for name, b in prim.items():
        c = collections.Counter(b)
        assert len(c) >= 2, f"{name}: constant"
        mode_shares.append(max(c.values()) / len(b))
        zero_shares.append(c.get(0, 0) / len(b))
        assert mode_shares[-1] <= MAX_MODE_SHARE, f"{name}: mode share {mode_shares[-1]:.3f}"
    digests = collections.Counter(hashlib.sha256(b).hexdigest() for b in prim.values())
    assert max(digests.values()) == 1, "duplicate primary samples"

    manifest = tomllib.loads(Path(args.manifest).read_text())
    realized = {
        PRIMARY: (n, total),
        AUX: (n, sum(len(b) for (s, _), b in expected.items() if s == AUX)),
    }
    for series in manifest["series"]:
        want = realized[series["id"]]
        got = (series["sample_count"], series["total_size_bytes"])
        assert got == want, f"manifest {series['id']} claims {got}, realized {want}"

    def q(xs: list[float], f: float) -> float:
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(f * len(xs)))]

    report = {
        "decisions": dict(sorted(decisions.items())),
        "primary_samples": n,
        "primary_values": total,
        "primary_bytes": total,
        "median_values": statistics.median(sizes),
        "min_values": sizes[0],
        "max_values": sizes[-1],
        "mode_share_p50": round(q(mode_shares, 0.5), 4),
        "mode_share_p90": round(q(mode_shares, 0.9), 4),
        "mode_share_max": round(max(mode_shares), 4),
        "zero_share_p50": round(q(zero_shares, 0.5), 4),
        "zero_share_max": round(max(zero_shares), 4),
        "global_max_value": max(max(b) for b in prim.values()),
    }
    log("verify_report " + json.dumps(report, sort_keys=True))
    with (p["filtered"] / "verify_mode_share.tsv").open("w") as fh:
        fh.write("sample\tvalue_count\tmode_share\tzero_share\n")
        for (name, b), ms, zs in zip(prim.items(), mode_shares, zero_shares):
            fh.write(f"{name}\t{len(b)}\t{ms:.6f}\t{zs:.6f}\n")
    log("verify OK")
    return 0


# ------------------------------------------------------------------ selftest
def cmd_selftest(_: argparse.Namespace) -> int:
    def fake(rows: list[str], sid: str = "9") -> str:
        head = ["#----", "# Natural Resources Conservation Service ", "# Reporting Frequency: Hourly; Date Range: %s to %s" % (RANGE_START, RANGE_END),
                f"# Test Site ({sid}) ", "# California  SNOTEL Site - 8000 ft", "#"]
        return "\n".join(head + [HEADER] + rows) + "\n"

    start = dt.datetime(2021, 10, 1)
    rows = []
    for h in range(0, 3 * 8784, 1):
        t = start + dt.timedelta(hours=h)
        if t > dt.datetime(2024, 9, 30, 23):
            break
        if h % 7 == 3:
            continue  # missing hour (omitted row)
        wy = t.year + 1 if t.month >= 10 else t.year
        if wy == 2022:
            v = str((h // 50) % 120)
        elif wy == 2023:
            v = "300" if h % 1000 == 1 else str((h // 40) % 90)  # one out-of-range value
        else:
            v = "0" if h % 10 else "5"  # 90% zeros -> mode_dominated
        if h % 11 == 5:
            v = ""  # blank value row
        rows.append(f"{t:%Y-%m-%d %H:%M},{v}")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.csv"
        f.write_text(fake(rows))
        assert classify(f, "9", "CA")[0] == "data"
        by_wy, err = build_parse(f)
        assert err is None
        b = {wy: build_decide(by_wy[wy]) for wy in WATER_YEARS}
        v = verify_expected(f)
        assert [b[w][0] for w in WATER_YEARS] == ["included", "out_of_range", "mode_dominated"], b
        assert [v[w][0] for w in WATER_YEARS] == ["included", "out_of_range", "mode_dominated"], v
        assert bytes(b[2022][1]) == v[2022][1]
        assert struct.pack(f"<{len(b[2022][2])}H", *b[2022][2]) == v[2022][2]
        offs = b[2022][2]
        assert offs[0] == 0 and offs == sorted(offs) and max(offs) <= 8759
        exp_first = [str(((h // 50) % 120)) for h in range(0, 30) if h % 7 != 3 and h % 11 != 5]
        assert [str(x) for x in b[2022][1][: len(exp_first)]] == exp_first
        # no-data and invalid payloads
        banner = "#--- WARNING\n# Natural Resources Conservation Service \n"
        f.write_text(banner + "# Reporting Frequency: Hourly\n#\n")
        assert classify(f, "9", "CA") == ("nodata", 0)
        f.write_text(banner + "#--- ERROR\n# Stations do not exist  9:CA:SNTL\n#\n")
        assert classify(f, "9", "CA") == ("nodata", 0)
        f.write_text(banner + "# something else\n")
        try:
            classify(f, "9", "CA")
            raise AssertionError("unmarked comment-only reply accepted")
        except ValueError:
            pass
        f.write_text(fake([]))
        assert classify(f, "9", "CA") == ("nodata", 0)
        f.write_text("<html>blocked</html>\n")
        try:
            classify(f, "9", "CA")
            raise AssertionError("html accepted")
        except ValueError:
            pass
        f.write_text(fake(["2021-10-01 00:00,abc"]))
        try:
            classify(f, "9", "CA")
            raise AssertionError("bad row accepted")
        except ValueError:
            pass
        # non-monotonic
        f.write_text(fake(["2021-10-01 01:00,1", "2021-10-01 00:00,2"]))
        assert build_parse(f)[1] == "non_monotonic_timestamps"
        assert verify_expected(f)[2022][0] == "non_monotonic_timestamps"
    log("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("file")
    c.add_argument("station_id")
    c.add_argument("state")
    for name in ("build", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--repo-root", required=True)
        s.add_argument("--data-dir", required=True)
        s.add_argument("--stations")
        s.add_argument("--manifest")
    sub.add_parser("selftest")
    args = ap.parse_args()
    return {"check": cmd_check, "build": cmd_build, "verify": cmd_verify, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
