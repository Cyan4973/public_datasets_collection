#!/usr/bin/env python3
"""Decode the German UVA_VPTS radar-month VPTS CSV files into float32 eta matrices.

Subcommands:
  inventory  stream the pinned de.tgz and check that its member set equals the
             German radar-months listed in the deposit's coverage.csv
  build      decode every radar-month member, emit one little-endian float32
             (profile x 25 heights) eta matrix per member, write the index and
             ingest statistics

Standard library only. The archive is streamed (tarfile "r|gz"); nothing is
extracted to disk.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import shutil
import struct
import sys
import tarfile
from pathlib import Path

DATASET_ID = "aloft_uva_vpts_animal_reflectivity_f32"
SERIES_ID = "uva_vpts_eta_f32"
RADARS = (
    "deasb", "deboo", "dedrs", "deeis", "deemd", "deess", "defbg", "defld", "dehnr",
    "deisn", "demem", "deneu", "denhb", "deoft", "depro", "deros", "detur", "deumd",
)
HEIGHTS = tuple(range(0, 4801, 200))
N_HEIGHTS = len(HEIGHTS)
FIELDS = (
    "radar", "datetime", "height", "u", "v", "w", "ff", "dd", "sd_vvp", "gap", "eta",
    "dens", "dbz", "dbz_all", "n", "n_dbz", "n_all", "n_dbz_all", "rcs",
    "sd_vvp_threshold", "vcp", "radar_latitude", "radar_longitude", "radar_height",
    "radar_wavelength", "source_file",
)
COVERAGE_FIELDS = (
    "radar", "country", "location", "date", "unique_hours", "unique_heights",
    "unique_source_files", "records",
)
MISSING_TOKENS = frozenset({"", "NA", "NaN"})
NAN_BITS = b"\x00\x00\xc0\x7f"
EXPECTED_MEMBERS = 465
EXPECTED_RECORDS = 28_369_050
MEMBER_RE = re.compile(r"^de/(de[a-z]{3})/(\d{4})/\1_vpts_(\d{4})(\d{2})\.csv\.gz$")
DIR_RE = re.compile(r"^de(?:/de[a-z]{3}(?:/\d{4})?)?/?$")
APPLEDOUBLE_MAGIC = b"\x00\x05\x16\x07"
DATETIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")
DECIMAL_RE = re.compile(r"^(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
VERSION_RE = re.compile(r"_v(\d+-\d+-\d+)\.h5$")


class Fatal(Exception):
    pass


def load_coverage(path: Path) -> dict[tuple[str, str], dict]:
    """German radar-month coverage: records per month and per day."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = tuple(next(reader))
        if header != COVERAGE_FIELDS:
            raise Fatal(f"coverage.csv header changed: {header}")
        months: dict[tuple[str, str], dict] = {}
        for row in reader:
            if len(row) != len(COVERAGE_FIELDS):
                raise Fatal(f"coverage.csv malformed row: {row}")
            radar, country, location, date, _hours, heights, _files, records = row
            if country != "de":
                continue
            if radar not in RADARS or location != radar:
                raise Fatal(f"coverage.csv unexpected German radar row: {row}")
            if heights != str(N_HEIGHTS):
                raise Fatal(f"coverage.csv unique_heights != 25: {row}")
            dt.date.fromisoformat(date)
            entry = months.setdefault((radar, date[:7]), {"records": 0, "days": {}})
            if date in entry["days"]:
                raise Fatal(f"coverage.csv duplicate radar-date: {row}")
            entry["days"][date] = int(records)
            entry["records"] += int(records)
    if len(months) != EXPECTED_MEMBERS:
        raise Fatal(f"coverage.csv lists {len(months)} German radar-months, expected {EXPECTED_MEMBERS}")
    total = sum(entry["records"] for entry in months.values())
    if total != EXPECTED_RECORDS:
        raise Fatal(f"coverage.csv lists {total} German records, expected {EXPECTED_RECORDS}")
    return months


def iter_archive(archive: Path, counters: collections.Counter):
    """Yield (radar, 'YYYY-MM', member_name, member_bytes) for every radar-month member.

    Directories, PAX extended headers (macOS quarantine xattrs) and AppleDouble
    `._*` resource-fork members are validated and skipped.
    """
    seen: set[str] = set()
    with tarfile.open(archive, mode="r|gz") as tar:
        for info in tar:
            name = info.name
            if name in seen:
                raise Fatal(f"duplicate archive member {name}")
            seen.add(name)
            if info.isdir():
                if not DIR_RE.match(name):
                    raise Fatal(f"unexpected archive directory {name}")
                counters["directories"] += 1
                continue
            if not info.isfile():
                raise Fatal(f"unexpected non-regular archive member {name} type={info.type!r}")
            base = name.rsplit("/", 1)[-1]
            handle = tar.extractfile(info)
            if handle is None:
                raise Fatal(f"cannot read archive member {name}")
            data = handle.read()
            if len(data) != info.size:
                raise Fatal(f"short read for archive member {name}")
            if base.startswith("._"):
                if info.size > 4096 or data[:4] != APPLEDOUBLE_MAGIC:
                    raise Fatal(f"member {name} is not a small AppleDouble resource fork")
                counters["appledouble_members_skipped"] += 1
                continue
            match = MEMBER_RE.match(name)
            if not match:
                raise Fatal(f"unexpected archive member {name}")
            radar, year_dir, year, month = match.groups()
            if year_dir != year or not 1 <= int(month) <= 12:
                raise Fatal(f"inconsistent member path {name}")
            if data[:3] != b"\x1f\x8b\x08":
                raise Fatal(f"member {name} is not gzip")
            counters["vpts_members"] += 1
            yield radar, f"{year}-{month}", name, data


def inventory(args: argparse.Namespace) -> None:
    coverage = load_coverage(args.coverage)
    counters: collections.Counter = collections.Counter()
    found: dict[tuple[str, str], int] = {}
    for radar, month, _name, data in iter_archive(args.archive, counters):
        key = (radar, month)
        if key in found:
            raise Fatal(f"duplicate radar-month {key}")
        found[key] = len(data)
    missing = sorted(set(coverage) - set(found))
    extra = sorted(set(found) - set(coverage))
    if missing or extra:
        raise Fatal(f"archive/coverage mismatch: missing={missing[:10]} extra={extra[:10]}")
    print(
        f"inventory_ok members={len(found)} member_bytes={sum(found.values())} "
        f"radars={len({k[0] for k in found})} months={min(k[1] for k in found)}..{max(k[1] for k in found)} "
        f"appledouble_skipped={counters['appledouble_members_skipped']} directories={counters['directories']}"
    )


def to_f32(text: str) -> tuple[bytes, float, str, float]:
    """Round one decimal eta token to binary32 and classify its precision.

    Returns (little-endian bytes, binary32 value, class, deviation in units of
    the token's last written decimal place). Classes:
      exact   the decimal equals the binary32 value
      unique  the token is within one last-place unit of exactly one binary32
              value, so rounding recovers the source binary32 bit-exactly
      coarse  the token was published with fewer digits than binary32
              resolution; the stored value is the binary32 nearest to it
    A token farther than one last-place unit from its nearest binary32 is not a
    faithful rendering of a binary32 value and is fatal.
    """
    if not DECIMAL_RE.match(text):
        raise Fatal(f"non-decimal eta token {text!r}")
    value = float(text)
    if not math.isfinite(value):
        raise Fatal(f"non-finite eta token {text!r}")
    try:
        packed = struct.pack("<f", value)
    except OverflowError as exc:
        raise Fatal(f"eta token {text!r} overflows binary32") from exc
    stored = struct.unpack("<f", packed)[0]
    if stored == value:
        return packed, stored, "exact", 0.0
    mantissa, _, exponent = text.lower().partition("e")
    fraction_digits = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    unit = 10.0 ** (int(exponent or "0") - fraction_digits)
    deviation = abs(value - stored) / unit
    if deviation > 1.0:
        raise Fatal(f"eta token {text!r} is {deviation:.3g} last-place units from binary32 {stored!r}")
    bits = struct.unpack("<I", packed)[0]
    above = struct.unpack("<f", struct.pack("<I", bits + 1))[0]
    below = struct.unpack("<f", struct.pack("<I", bits - 1))[0] if bits else -above
    if above - value > unit and value - below > unit:
        return packed, stored, "unique", deviation
    return packed, stored, "coarse", deviation


def decode_member(data: bytes, radar: str, month: str, coverage_entry: dict) -> dict:
    text = gzip.decompress(data).decode("utf-8")
    if "\r" in text or '"' in text:
        raise Fatal("unexpected CR or quote characters in CSV text")
    reader = csv.reader(io.StringIO(text))
    header = tuple(next(reader))
    if header != FIELDS:
        raise Fatal(f"header mismatch: {header}")
    ix_radar = FIELDS.index("radar")
    ix_dt = FIELDS.index("datetime")
    ix_h = FIELDS.index("height")
    ix_eta = FIELDS.index("eta")
    ix_rcs = FIELDS.index("rcs")
    ix_thr = FIELDS.index("sd_vvp_threshold")
    ix_wl = FIELDS.index("radar_wavelength")
    ix_src = FIELDS.index("source_file")
    height_text = {h: str(h) for h in HEIGHTS}
    out = bytearray()
    level = 0
    current = previous = first = ""
    previous_time: dt.datetime | None = None
    stamps: set[str] = set()
    order_breaks = 0
    profiles = rows = nan_count = zero_count = 0
    classes: collections.Counter = collections.Counter()
    max_deviation = 0.0
    finite_min = math.inf
    finite_max = -math.inf
    distinct: set[bytes] = set()
    missing_tokens: collections.Counter = collections.Counter()
    radar_ids: set[str] = set()
    rcs_seen: set[str] = set()
    thr_seen: set[str] = set()
    wl_seen: set[str] = set()
    versions: collections.Counter = collections.Counter()
    cadence: collections.Counter = collections.Counter()
    day_rows: collections.Counter = collections.Counter()
    for row in reader:
        if len(row) != len(FIELDS):
            raise Fatal(f"row {rows + 2} has {len(row)} fields")
        stamp = row[ix_dt]
        if level == 0:
            match = DATETIME_RE.match(stamp)
            if not match:
                raise Fatal(f"bad datetime {stamp!r}")
            moment = dt.datetime(*map(int, match.groups()))
            if stamp[:7] != month:
                raise Fatal(f"datetime {stamp} outside file month {month}")
            if stamp in stamps:
                raise Fatal(f"duplicate profile datetime {stamp}")
            stamps.add(stamp)
            if previous and stamp < previous:
                order_breaks += 1
            elif previous_time is not None:
                cadence[round((moment - previous_time).total_seconds() / 60)] += 1
            previous_time = moment
            current = stamp
            first = first or stamp
            profiles += 1
            day_rows[stamp[:10]] += N_HEIGHTS
            found = VERSION_RE.search(row[ix_src])
            versions[found.group(1) if found else "unversioned_source_name"] += 1
        elif stamp != current:
            raise Fatal(f"profile at {current} has only {level} heights")
        if row[ix_h] != height_text[HEIGHTS[level]]:
            raise Fatal(f"height {row[ix_h]!r} at level {level} of profile {current}")
        token = row[ix_eta]
        if token in MISSING_TOKENS:
            out += NAN_BITS
            nan_count += 1
            missing_tokens[token] += 1
        else:
            packed, stored, kind, deviation = to_f32(token)
            if stored < 0:
                raise Fatal(f"negative eta {token!r}")
            classes[kind] += 1
            if deviation > max_deviation:
                max_deviation = deviation
            if stored == 0.0:
                zero_count += 1
            finite_min = min(finite_min, stored)
            finite_max = max(finite_max, stored)
            if len(distinct) < 100_000:
                distinct.add(packed)
            out += packed
        radar_ids.add(row[ix_radar])
        rcs_seen.add(row[ix_rcs])
        thr_seen.add(row[ix_thr])
        wl_seen.add(row[ix_wl])
        rows += 1
        level += 1
        if level == N_HEIGHTS:
            level = 0
            previous = current
    if level != 0:
        raise Fatal(f"last profile {current} has only {level} heights")
    if rows == 0:
        raise Fatal("no data rows")
    wmo_ids = sorted(x for x in radar_ids if x != radar)
    if len(wmo_ids) > 1 or any(not x.isdigit() for x in wmo_ids):
        raise Fatal(f"radar column values {sorted(radar_ids)} are not the ODIM code plus at most one WMO number")
    if {float(x) for x in rcs_seen} != {11.0}:
        raise Fatal(f"rcs values {sorted(rcs_seen)} differ from the uniform 11 cm2")
    if {float(x) for x in thr_seen} != {2.0}:
        raise Fatal(f"sd_vvp_threshold values {sorted(thr_seen)} differ from the uniform 2 m/s")
    wavelengths = sorted({round(float(x), 4) for x in wl_seen})
    if not all(5.0 < w < 5.7 for w in wavelengths):
        raise Fatal(f"radar_wavelength {sorted(wl_seen)} is not C-band")
    if rows != coverage_entry["records"]:
        raise Fatal(f"rows {rows} != coverage records {coverage_entry['records']}")
    if dict(day_rows) != coverage_entry["days"]:
        raise Fatal("per-day row counts differ from coverage.csv")
    if len(out) != rows * 4:
        raise Fatal("internal size mismatch")
    return {
        "payload": bytes(out),
        "rows": rows,
        "profiles": profiles,
        "nan_count": nan_count,
        "zero_count": zero_count,
        "finite_count": rows - nan_count,
        "distinct_finite_capped": len(distinct),
        "finite_min": None if finite_min == math.inf else finite_min,
        "finite_max": None if finite_max == -math.inf else finite_max,
        "decimal_exact": classes["exact"],
        "decimal_unique": classes["unique"],
        "decimal_coarse": classes["coarse"],
        "max_last_place_deviation": max_deviation,
        "missing_tokens": dict(missing_tokens),
        "wmo_id": wmo_ids[0] if wmo_ids else None,
        "radar_column_values": sorted(radar_ids),
        "radar_wavelengths_cm": wavelengths,
        "vol2bird_versions": dict(versions),
        "cadence_minutes": dict(sorted(cadence.items())),
        "datetime_order_breaks": order_breaks,
        "first_datetime": first,
        "last_datetime": current,
    }


def degeneracy(result: dict) -> str | None:
    if result["finite_count"] == 0:
        return "all eta values missing"
    if result["distinct_finite_capped"] < 2:
        return "eta finite values are constant"
    if result["finite_count"] == result["zero_count"]:
        return "all finite eta values are zero"
    return None


def build(args: argparse.Namespace) -> None:
    coverage = load_coverage(args.coverage)
    data_root = args.data_root.resolve()
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    counters: collections.Counter = collections.Counter()
    problems: list[str] = []
    rows_out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    totals: collections.Counter = collections.Counter()
    versions: collections.Counter = collections.Counter()
    cadence_modes: collections.Counter = collections.Counter()
    missing_tokens: collections.Counter = collections.Counter()
    radar_column_styles: collections.Counter = collections.Counter()
    wmo_by_radar: dict[str, set[str]] = collections.defaultdict(set)
    wavelengths_by_radar: dict[str, set[float]] = collections.defaultdict(set)
    coarse_samples: dict[str, int] = {}
    order_break_samples: dict[str, int] = {}
    max_deviation = 0.0
    for radar, month, name, data in iter_archive(args.archive, counters):
        key = (radar, month)
        if key in seen:
            raise Fatal(f"duplicate radar-month {key}")
        seen.add(key)
        if key not in coverage:
            problems.append(f"{name}: radar-month absent from coverage.csv")
            continue
        try:
            result = decode_member(data, radar, month, coverage[key])
        except (Fatal, ValueError, UnicodeDecodeError, EOFError, OSError) as exc:
            problems.append(f"{name}: {exc}")
            continue
        reason = degeneracy(result)
        if reason:
            problems.append(f"{name}: degenerate sample: {reason}")
        payload = result.pop("payload")
        yyyymm = month.replace("-", "")
        sample = series_dir / f"{radar}_vpts_{yyyymm}_eta.f32le.bin"
        sample.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        cadence = result["cadence_minutes"]
        mode = max(cadence, key=lambda k: (cadence[k], -k)) if cadence else None
        cadence_modes[str(mode)] += 1
        versions.update(result["vol2bird_versions"])
        missing_tokens.update(result["missing_tokens"])
        values = result["radar_column_values"]
        style = "odim_code" if values == [radar] else "wmo_number" if radar not in values else "mixed_odim_and_wmo"
        radar_column_styles[style] += 1
        if result["wmo_id"]:
            wmo_by_radar[radar].add(result["wmo_id"])
        wavelengths_by_radar[radar].update(result["radar_wavelengths_cm"])
        if result["decimal_coarse"]:
            coarse_samples[f"{radar}_{yyyymm}"] = result["decimal_coarse"]
        if result["datetime_order_breaks"]:
            order_break_samples[f"{radar}_{yyyymm}"] = result["datetime_order_breaks"]
        max_deviation = max(max_deviation, result["max_last_place_deviation"])
        for field in ("rows", "profiles", "nan_count", "zero_count", "finite_count", "decimal_exact", "decimal_unique", "decimal_coarse"):
            totals[field] += result[field]
        totals["member_bytes"] += len(data)
        rows_out.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": sample.resolve().relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": result["rows"],
                "sample_shape": [result["profiles"], N_HEIGHTS],
                "sample_axes": ["profile_datetime", "height_bin_0_to_4800_m_step_200"],
                "radar": radar,
                "year_month": month,
                "source_member": name,
                "source_member_bytes": len(data),
                "first_datetime": result["first_datetime"],
                "last_datetime": result["last_datetime"],
                "datetime_order_breaks": result["datetime_order_breaks"],
                "cadence_mode_minutes": mode,
                "nan_count": result["nan_count"],
                "zero_count": result["zero_count"],
                "decimal_exact_count": result["decimal_exact"],
                "decimal_unique_count": result["decimal_unique"],
                "decimal_coarse_count": result["decimal_coarse"],
                "finite_min": result["finite_min"],
                "finite_max": result["finite_max"],
                "radar_wavelengths_cm": result["radar_wavelengths_cm"],
                "sha256": digest,
            }
        )
        counters["samples"] += 1
        print(
            f"sample {radar} {month} profiles={result['profiles']} values={result['rows']} "
            f"nan={result['nan_count']} zero={result['zero_count']} coarse={result['decimal_coarse']} "
            f"cadence_mode={mode} order_breaks={result['datetime_order_breaks']} "
            f"max_dev={result['max_last_place_deviation']:.3f}",
            flush=True,
        )
    missing = sorted(set(coverage) - seen)
    if missing:
        problems.append(f"coverage radar-months absent from archive: {missing[:20]}")
    for radar, ids in sorted(wmo_by_radar.items()):
        if len(ids) != 1:
            problems.append(f"radar {radar} maps to several WMO numbers {sorted(ids)}")
    all_wmo = [next(iter(ids)) for ids in wmo_by_radar.values() if len(ids) == 1]
    if len(all_wmo) != len(set(all_wmo)):
        problems.append("one WMO number is used by several radars")
    rows_out.sort(key=lambda row: (row["radar"], row["year_month"]))
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    aggregate = hashlib.sha256()
    for row in rows_out:
        aggregate.update(bytes.fromhex(row["sha256"]))
    finite = totals["finite_count"]
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "archive": args.archive.name,
        "samples": len(rows_out),
        "radars": len({row["radar"] for row in rows_out}),
        "first_month": min((row["year_month"] for row in rows_out), default=None),
        "last_month": max((row["year_month"] for row in rows_out), default=None),
        "values": totals["rows"],
        "bytes": totals["rows"] * 4,
        "profiles": totals["profiles"],
        "nan_values": totals["nan_count"],
        "zero_values": totals["zero_count"],
        "finite_values": finite,
        "nan_fraction": round(totals["nan_count"] / totals["rows"], 6) if totals["rows"] else None,
        "zero_fraction_of_finite": round(totals["zero_count"] / finite, 6) if finite else None,
        "decimal_exact_values": totals["decimal_exact"],
        "decimal_unique_values": totals["decimal_unique"],
        "decimal_coarse_values": totals["decimal_coarse"],
        "bit_exact_fraction_of_finite": round((totals["decimal_exact"] + totals["decimal_unique"]) / finite, 8) if finite else None,
        "max_last_place_deviation": max_deviation,
        "coarse_value_samples": coarse_samples,
        "datetime_order_break_samples": order_break_samples,
        "missing_tokens": dict(missing_tokens),
        "radar_column_styles": dict(radar_column_styles),
        "wmo_by_radar": {radar: sorted(ids) for radar, ids in sorted(wmo_by_radar.items())},
        "radar_wavelengths_cm_by_radar": {radar: sorted(w) for radar, w in sorted(wavelengths_by_radar.items())},
        "vol2bird_versions_by_profile": dict(versions),
        "cadence_mode_minutes_by_sample": dict(cadence_modes),
        "member_bytes": totals["member_bytes"],
        "archive_counters": dict(counters),
        "aggregate_sha256_of_sample_sha256s": aggregate.hexdigest(),
        "median_sample_values": sorted(row["value_count"] for row in rows_out)[len(rows_out) // 2] if rows_out else 0,
        "problems": problems,
    }
    args.stats.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("problems", "coarse_value_samples")}, sort_keys=True))
    if problems:
        for problem in problems:
            print(f"PROBLEM {problem}", file=sys.stderr)
        raise Fatal(f"{len(problems)} problem(s); see {args.stats}")
    if len(rows_out) != EXPECTED_MEMBERS or totals["rows"] != EXPECTED_RECORDS:
        raise Fatal(f"realized {len(rows_out)} samples / {totals['rows']} values, expected {EXPECTED_MEMBERS} / {EXPECTED_RECORDS}")
    print(f"build_ok samples={len(rows_out)} values={totals['rows']} bytes={totals['rows'] * 4}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--archive", type=Path, required=True)
    inv.add_argument("--coverage", type=Path, required=True)
    bld = sub.add_parser("build")
    bld.add_argument("--archive", type=Path, required=True)
    bld.add_argument("--coverage", type=Path, required=True)
    bld.add_argument("--samples-dir", type=Path, required=True)
    bld.add_argument("--index", type=Path, required=True)
    bld.add_argument("--stats", type=Path, required=True)
    bld.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "inventory":
            inventory(args)
        else:
            build(args)
    except Fatal as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
