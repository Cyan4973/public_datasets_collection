#!/usr/bin/env python3
"""NOAA ASOS one-minute page-2 (DSI 6406) air temperature / dew point extraction.

Subcommands:
  validate  check downloaded station-month files (used by download.sh)
  build     emit int8 temperature and dew-point samples + index + ingest stats
  verify    independently re-parse the downloads (full-line regex parser, not
            the fixed-slice parser used by build) and compare every sample

Record layout (DSI 6406 documentation 2022-11-08 gives the field order; the
column positions below were confirmed on 2022 and 2024 files): fixed-width
ASCII lines, 112 characters + LF, 0-based slices:
  [0:5]   WBAN number           [5:9]   ICAO call sign      [9] blank
  [10:13] station call sign     [13:17] year (LST)  [17:19] month (LST)
  [19:21] day (LST)             [21:25] HHMM local  [25:29] HHMM UTC
  [29:92] precipitation id/intensity, lightning, 1-min precipitation amount,
          freezing-rain sensor frequency, three station pressures
  [92]    blank, or the closing ']' of a bracketed third pressure
  [93:98] dry-bulb temperature slot (deg F)
  [98:103] dew-point temperature slot (deg F)
  [103:]  blank padding
Each 5-character slot is either " vvv " (value right-justified in the middle
three characters, e.g. "  26 ", " -12 ", " 104 "), "[vvv]" (the same value
enclosed in square brackets), or missing: "[ M ]", "  M  " or all blanks.
The page-1/page-2 documentation does not define the brackets; they also
appear around lightning, freezing-rain and pressure fields. Bracketed
temperature/dew-point values are treated as flagged and dropped (counted),
not used.

Precipitation, lightning and pressure fields may be blank, "M" or bracketed;
since the temperature and dew-point slots are read from fixed columns, those
variations cannot shift them. A row is structural only if column 92 is blank
or ']', both slots are well formed, and columns 103+ are blank, which rejects
records that are shifted or truncated.

About 0.25% of minutes appear twice (a second consecutive record with the
same LST timestamp, often with slightly different pressure/temperature, as
if from a second processor). Only the first structural row of each LST
minute is used; later ones are counted as duplicate_minute_rows.

A station-month is kept only if both series have valid values for at least
MIN_VALID_COVERAGE of the calendar month's minutes; otherwise it is excluded
for both series and listed in ingest_stats.json.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

DATASET_ID = "noaa_asos_1min_pg2_temperature_dewpoint_i8"
SERIES = (
    # series_id, slot index (0 = temperature, 1 = dew point)
    ("air_temperature_degf_i8", 0),
    ("dew_point_temperature_degf_i8", 1),
)
SLOTS = ((93, 98), (98, 103))
INT8_MIN, INT8_MAX = -128, 127
MIN_SAMPLE_VALUES = 1000
MAX_MODE_SHARE = 0.80
MAX_BAD_ROW_SHARE = 0.05
# A station-month is kept only if BOTH series have valid values for at least
# this share of the calendar month's minutes (days x 1440); otherwise it is
# excluded for both series (sensor outages / long flagged runs inside files
# that passed the download-time size rule).
MIN_VALID_COVERAGE = 0.80
MISSING, FLAGGED = "missing", "flagged"


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line]
    for row in rows:
        row["size_bytes"] = int(row["size_bytes"])
    return rows


def to_int8_bytes(values: list[int]) -> bytes:
    return bytes(v & 0xFF for v in values)


def from_int8_bytes(data: bytes) -> list[int]:
    return [b - 256 if b > 127 else b for b in data]


# --------------------------------------------------------------------------
# build parser: fixed slices and character tests
# --------------------------------------------------------------------------

def parse_slot(slot: str):
    """Return int, MISSING, FLAGGED, or raise ValueError if malformed."""
    left, inner, right = slot[0], slot[1:4], slot[4]
    if (left, right) == ("[", "]"):
        bracketed = True
    elif (left, right) == (" ", " "):
        bracketed = False
    else:
        raise ValueError(slot)
    core = inner.strip(" ")
    if core in ("", "M"):
        return MISSING
    digits = inner.lstrip(" ")
    negative = digits.startswith("-")
    if negative:
        digits = digits[1:]
    if not (digits and all("0" <= ch <= "9" for ch in digits)):
        raise ValueError(slot)
    if bracketed:
        return FLAGGED
    value = int(digits)
    return -value if negative else value


def parse_file_fixed(path: Path, station: str, yyyymm: str) -> dict:
    year, month = yyyymm[:4], yyyymm[5:7]
    values = {sid: [] for sid, _ in SERIES}
    counts = collections.Counter()
    seen_minutes = set()
    with path.open("rb") as handle:
        for raw in handle:
            counts["rows"] += 1
            try:
                line = raw.decode("ascii").rstrip("\r\n")
            except UnicodeDecodeError:
                counts["bad_rows_non_ascii"] += 1
                continue
            if not line.isprintable():
                counts["bad_rows_non_ascii"] += 1
                continue
            if len(line) < 103:
                counts["bad_rows_short"] += 1
                continue
            if not (line[0:5].isdigit() and line[5:9] == station and line[9] == " "
                    and line[13:29].isdigit()):
                counts["bad_rows_prefix"] += 1
                continue
            if line[13:17] != year or line[17:19] != month:
                counts["bad_rows_other_month"] += 1
                continue
            if line[92] not in " ]" or line[103:].strip(" ") != "":
                counts["bad_rows_layout"] += 1
                continue
            try:
                fields = [parse_slot(line[a:b]) for a, b in SLOTS]
            except ValueError:
                counts["bad_rows_slots"] += 1
                continue
            counts["structural_rows"] += 1
            stamp = line[13:25]  # LST year, month, day, HHMM
            if stamp in seen_minutes:
                # the source repeats some minutes with a second record (often
                # with different pressure/temperature); keep the first one
                counts["duplicate_minute_rows"] += 1
                continue
            seen_minutes.add(stamp)
            for sid, index in SERIES:
                value = fields[index]
                if value == MISSING:
                    counts[f"missing_{sid}"] += 1
                elif value == FLAGGED:
                    counts[f"flagged_{sid}"] += 1
                elif value < INT8_MIN or value > INT8_MAX:
                    counts[f"out_of_range_{sid}"] += 1
                else:
                    values[sid].append(value)
    return {"values": values, "counts": dict(counts)}


# --------------------------------------------------------------------------
# verify parser: independent full-line regex
# --------------------------------------------------------------------------

LINE_RE = re.compile(
    rb"^(?P<wban>\d{5})(?P<icao>[A-Z0-9]{4}) [ -~]{3}(?P<year>\d{4})(?P<month>\d{2})(?P<dhm>\d{6})\d{4}"
    rb"[ -~]{63}[ \]]"
    rb"(?P<s0>\[[ -~]{3}\]| [ -~]{3} )(?P<s1>\[[ -~]{3}\]| [ -~]{3} ) *\r?$"
)
VALUE_RE = re.compile(rb"^ *(-?\d{1,3})$")
MISSING_RE = re.compile(rb"^ *M? *$")


def parse_file_regex(path: Path, station: str, yyyymm: str) -> dict:
    year, month = yyyymm[:4].encode(), yyyymm[5:7].encode()
    st = station.encode()
    values = {sid: [] for sid, _ in SERIES}
    counts = collections.Counter()
    first_seen = set()
    data = path.read_bytes()
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    for raw in lines:
        counts["rows"] += 1
        match = LINE_RE.match(raw)
        if not match or match["icao"] != st or match["year"] != year or match["month"] != month:
            counts["bad_rows"] += 1
            continue
        slots = [match["s0"], match["s1"]]
        decoded = []
        ok = True
        for slot in slots:
            inner = slot[1:4]
            if MISSING_RE.match(inner):
                decoded.append(MISSING)
                continue
            number = VALUE_RE.match(inner)
            if number is None:
                ok = False
                break
            decoded.append(FLAGGED if slot.startswith(b"[") else int(number.group(1)))
        if not ok:
            counts["bad_rows"] += 1
            continue
        counts["structural_rows"] += 1
        minute_key = match["dhm"]
        if minute_key in first_seen:
            counts["duplicate_minute_rows"] += 1
            continue
        first_seen.add(minute_key)
        for sid, index in SERIES:
            value = decoded[index]
            if value == MISSING:
                counts[f"missing_{sid}"] += 1
            elif value == FLAGGED:
                counts[f"flagged_{sid}"] += 1
            elif not INT8_MIN <= value <= INT8_MAX:
                counts[f"out_of_range_{sid}"] += 1
            else:
                values[sid].append(value)
    return {"values": values, "counts": dict(counts)}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def mode_share(values: list[int]) -> float:
    if not values:
        return 1.0
    hist = collections.Counter(values)
    return max(hist.values()) / len(values)


def sample_relpath(sid: str, station: str, yyyymm: str) -> str:
    return f"samples/{DATASET_ID}/{sid}/{station}_{yyyymm}.i8.bin"


def month_minutes(yyyymm: str) -> int:
    return calendar.monthrange(int(yyyymm[:4]), int(yyyymm[5:7]))[1] * 1440


def coverage_ok(values: dict, yyyymm: str) -> tuple[bool, dict]:
    full = month_minutes(yyyymm)
    cov = {sid: round(len(values[sid]) / full, 6) for sid, _ in SERIES}
    return all(c >= MIN_VALID_COVERAGE for c in cov.values()), cov


def bad_row_total(counts: dict) -> int:
    return sum(v for k, v in counts.items() if k.startswith("bad_rows"))


# --------------------------------------------------------------------------
# validate (download.sh)
# --------------------------------------------------------------------------

def cmd_validate(args) -> int:
    rows = read_sources(Path(args.sources))
    download_dir = Path(args.download_dir)
    failures = []
    invalid = []
    for row in rows:
        path = download_dir / row["month"] / row["filename"]
        if not path.is_file():
            failures.append(f"missing {path}")
            continue
        size = path.stat().st_size
        if size != row["size_bytes"]:
            failures.append(f"size mismatch {path}: {size} != {row['size_bytes']}")
            invalid.append(path)
            continue
        data = path.read_bytes()
        if not data.endswith(b"\n"):
            failures.append(f"truncated (no trailing LF) {path}")
            invalid.append(path)
            continue
        lines = data.split(b"\n")[:-1]
        prefix = re.compile(
            rb"^\d{5}" + row["station"].encode() + rb" [ -~]{3}"
            + row["month"].replace("-", "").encode() + rb"\d{10}"
        )
        good = sum(1 for line in lines if prefix.match(line))
        if not lines or good / len(lines) < 0.99 or not prefix.match(lines[0]):
            failures.append(f"semantic check failed {path}: {good}/{len(lines)} lines carry the expected WBAN+ICAO+year-month prefix")
            invalid.append(path)
            continue
        print(f"ok {row['station']} {row['month']} bytes={size} lines={len(lines)}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        if args.delete_invalid:
            for path in invalid:
                print(f"deleting invalid payload {path}", file=sys.stderr)
                path.unlink()
        return 1
    print(f"validated station_months={len(rows)}")
    return 0


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build(args) -> int:
    rows = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    download_dir = Path(args.download_dir) if args.download_dir else data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    for sid, _ in SERIES:
        out_dir = samples_root / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("*.bin"):
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    index_rows = []
    totals = collections.Counter()
    per_file = []
    excluded = []
    for row in rows:
        station, yyyymm = row["station"], row["month"]
        path = download_dir / yyyymm / row["filename"]
        if not path.is_file() or path.stat().st_size != row["size_bytes"]:
            raise SystemExit(f"missing or wrong-size download {path}; run download.sh")
        parsed = parse_file_fixed(path, station, yyyymm)
        counts = parsed["counts"]
        bad = bad_row_total(counts)
        if counts.get("rows", 0) == 0 or bad / counts["rows"] > MAX_BAD_ROW_SHARE:
            raise SystemExit(f"{path}: malformed row share too high ({bad}/{counts.get('rows', 0)}): {counts}")
        totals.update(counts)
        keep, cov = coverage_ok(parsed["values"], yyyymm)
        file_entry = {"station": station, "month": yyyymm, "counts": counts, "coverage": cov,
                      "kept": keep, "series": {}}
        if not keep:
            excluded.append({"station": station, "month": yyyymm, "coverage": cov})
            per_file.append(file_entry)
            print(f"{station} {yyyymm} EXCLUDED valid coverage {cov} < {MIN_VALID_COVERAGE}")
            continue
        for sid, _ in SERIES:
            vals = parsed["values"][sid]
            if len(vals) < MIN_SAMPLE_VALUES:
                raise SystemExit(f"{station} {yyyymm} {sid}: only {len(vals)} values")
            share = mode_share(vals)
            if share >= MAX_MODE_SHARE or len(set(vals)) < 3:
                raise SystemExit(f"{station} {yyyymm} {sid}: degenerate (mode share {share:.3f})")
            data = to_int8_bytes(vals)
            rel = sample_relpath(sid, station, yyyymm)
            (data_root / rel).write_bytes(data)
            stored = from_int8_bytes(data)
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "sample_path": rel,
                "numeric_kind": "int",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(data),
                "value_count": len(data),
                "station": station,
                "month": yyyymm,
                "source_file": row["filename"],
                "min": min(stored),
                "max": max(stored),
                "mode_share": round(share, 6),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            file_entry["series"][sid] = {"values": len(data), "min": min(stored), "max": max(stored),
                                         "mode_share": round(share, 4)}
            totals[f"values_{sid}"] += len(data)
        per_file.append(file_entry)
        print(f"{station} {yyyymm} rows={counts['rows']} bad={bad} "
              + " ".join(f"{sid}={file_entry['series'][sid]['values']}"
                         f"[{file_entry['series'][sid]['min']},{file_entry['series'][sid]['max']}]"
                         for sid, _ in SERIES))

    with index_path.open("w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    kept_rows = [e for e in per_file if e["kept"]]
    summary = {"dataset_id": DATASET_ID, "station_months_downloaded": len(rows),
               "station_months_kept": len(kept_rows),
               "stations_kept": len({e["station"] for e in kept_rows}),
               "min_valid_coverage": MIN_VALID_COVERAGE, "excluded": excluded,
               "totals": dict(totals), "series": {}}
    for sid, _ in SERIES:
        sel = [r for r in index_rows if r["series_id"] == sid]
        sizes = sorted(r["sample_size_bytes"] for r in sel)
        summary["series"][sid] = {
            "sample_count": len(sel),
            "total_size_bytes": sum(sizes),
            "median_sample_values": sizes[len(sizes) // 2],
            "min_sample_values": sizes[0],
            "max_mode_share": max(r["mode_share"] for r in sel),
            "median_mode_share": sorted(r["mode_share"] for r in sel)[len(sel) // 2],
            "min": min(r["min"] for r in sel),
            "max": max(r["max"] for r in sel),
        }
    summary["per_file"] = per_file
    stats_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_file"}, indent=1, sort_keys=True))
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def load_manifest_series(manifest: Path) -> dict:
    import tomllib
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data.get("series", [])}


def cmd_verify(args) -> int:
    rows = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    download_dir = Path(args.download_dir) if args.download_dir else data_root / "downloads" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    failures = []
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    by_path = {r["sample_path"]: r for r in index}
    if len(by_path) != len(index):
        failures.append("duplicate sample_path in index")
    expected_paths = set()
    verify_excluded = []
    totals = collections.Counter()
    for row in rows:
        station, yyyymm = row["station"], row["month"]
        path = download_dir / yyyymm / row["filename"]
        if not path.is_file() or path.stat().st_size != row["size_bytes"]:
            failures.append(f"missing or wrong-size download {path}")
            continue
        parsed = parse_file_regex(path, station, yyyymm)
        counts = parsed["counts"]
        totals.update(counts)
        if counts.get("bad_rows", 0) > MAX_BAD_ROW_SHARE * counts.get("rows", 0):
            failures.append(f"{path}: malformed row share too high")
        full = month_minutes(yyyymm)
        if any(len(parsed["values"][sid]) < MIN_VALID_COVERAGE * full for sid, _ in SERIES):
            verify_excluded.append(f"{station} {yyyymm}")
            continue
        for sid, _ in SERIES:
            rel = sample_relpath(sid, station, yyyymm)
            expected_paths.add(rel)
            want_values = parsed["values"][sid]
            want = bytes((v + 256) % 256 for v in want_values)
            entry = by_path.get(rel)
            sample = data_root / rel
            if entry is None or not sample.is_file():
                failures.append(f"missing sample/index row {rel}")
                continue
            got = sample.read_bytes()
            if got != want:
                failures.append(f"content mismatch {rel}: {len(got)} vs re-derived {len(want)} values")
                continue
            signed = [b if b < 128 else b - 256 for b in got]
            checks = {
                "dataset_id": DATASET_ID, "series_id": sid, "numeric_kind": "int", "bit_width": 8,
                "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(got),
                "value_count": len(got), "min": min(signed), "max": max(signed),
                "sha256": hashlib.sha256(got).hexdigest(),
            }
            for key, value in checks.items():
                if entry.get(key) != value:
                    failures.append(f"index field {key} mismatch for {rel}: {entry.get(key)!r} != {value!r}")
            share = mode_share(signed)
            if len(got) < MIN_SAMPLE_VALUES or len(set(signed)) < 3 or share >= MAX_MODE_SHARE:
                failures.append(f"degenerate sample {rel}: values={len(got)} distinct={len(set(signed))} mode_share={share:.3f}")
            totals[f"values_{sid}"] += len(got)
    extra = set(by_path) - expected_paths
    if extra:
        failures.append(f"{len(extra)} unexpected index rows, e.g. {sorted(extra)[0]}")
    for sid, _ in SERIES:
        on_disk = {f"samples/{DATASET_ID}/{sid}/{p.name}" for p in (data_root / "samples" / DATASET_ID / sid).glob("*")}
        stray = on_disk - expected_paths
        if stray:
            failures.append(f"{len(stray)} stray files in {sid}, e.g. {sorted(stray)[0]}")

    # cross-check the build's ingest counts with the independent parser
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    built = stats["totals"]
    keys = ["rows", "structural_rows", "duplicate_minute_rows"]
    for sid, _ in SERIES:
        keys += [f"missing_{sid}", f"flagged_{sid}", f"out_of_range_{sid}", f"values_{sid}"]
    for key in keys:
        if int(built.get(key, 0)) != int(totals.get(key, 0)):
            failures.append(f"count mismatch {key}: build={built.get(key, 0)} verify={totals.get(key, 0)}")
    built_excluded = [f"{e['station']} {e['month']}" for e in stats.get("excluded", [])]
    if built_excluded != verify_excluded:
        failures.append(f"excluded station-months differ: build={built_excluded} verify={verify_excluded}")
    print(f"excluded station-months (valid coverage < {MIN_VALID_COVERAGE}): {len(verify_excluded)} {verify_excluded}")
    built_bad = sum(v for k, v in built.items() if k.startswith("bad_rows"))
    if built_bad != totals.get("bad_rows", 0):
        failures.append(f"bad-row mismatch: build={built_bad} verify={totals.get('bad_rows', 0)}")

    # manifest consistency
    if args.manifest:
        manifest_series = load_manifest_series(Path(args.manifest))
        for sid, _ in SERIES:
            sel = [r for r in index if r["series_id"] == sid]
            count, size = len(sel), sum(r["sample_size_bytes"] for r in sel)
            spec = manifest_series.get(sid)
            if spec is None:
                failures.append(f"manifest lacks series {sid}")
                continue
            if spec.get("sample_count") != count or spec.get("total_size_bytes") != size:
                failures.append(f"manifest {sid}: sample_count/total_size_bytes {spec.get('sample_count')}/{spec.get('total_size_bytes')} != realized {count}/{size}")
            print(f"series {sid}: samples={count} bytes={size}")

    print(json.dumps(dict(totals), sort_keys=True))
    if failures:
        for failure in failures[:50]:
            print("FAIL", failure, file=sys.stderr)
        print(f"verify FAILED ({len(failures)} problems)", file=sys.stderr)
        return 1
    print("verify ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--sources", required=True)
    p.add_argument("--download-dir", required=True)
    p.add_argument("--delete-invalid", action="store_true")
    p.set_defaults(func=cmd_validate)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--data-root", required=True)
        p.add_argument("--download-dir", default=None, help="override (self-tests only)")
        p.add_argument("--manifest", default=None)
        p.set_defaults(func=func)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
