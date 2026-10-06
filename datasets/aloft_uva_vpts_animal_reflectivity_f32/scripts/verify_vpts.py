#!/usr/bin/env python3
"""Independently re-derive and check the UVA_VPTS German eta float32 samples.

This verifier deliberately does not import scripts/vpts.py. It re-streams the
pinned archive, re-parses every CSV with plain line splitting, converts eta
with array('f') instead of struct, applies the same missing-value policy
('', 'NA', 'NaN' -> canonical binary32 quiet NaN 0x7fc00000), and byte-compares
the result with each emitted sample. It also checks the index, the manifest
totals, coverage.csv agreement, NaN bit patterns and non-degeneracy.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import tarfile
import tomllib
from array import array
from collections import Counter, defaultdict
from pathlib import Path

DATASET_ID = "aloft_uva_vpts_animal_reflectivity_f32"
SERIES_ID = "uva_vpts_eta_f32"
EXPECTED_SAMPLES = 465
EXPECTED_VALUES = 28_369_050
EXPECTED_RADARS = 18
HEIGHT_TOKENS = [str(200 * i) for i in range(25)]
MISSING = {"", "NA", "NaN"}
NAN_WORD = 0x7FC00000
INDEX_KEYS = (
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
)
NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
MEMBER = re.compile(r"de/(de[a-z]{3})/(\d{4})/(de[a-z]{3})_vpts_(\d{6})\.csv\.gz")


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def coverage_counts(path: Path) -> tuple[dict, dict]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if lines[0] != "radar,country,location,date,unique_hours,unique_heights,unique_source_files,records":
        fail("coverage.csv header changed")
    per_month: dict[tuple[str, str], int] = defaultdict(int)
    per_day: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for line in lines[1:]:
        cells = line.split(",")
        if len(cells) != 8:
            fail(f"coverage.csv malformed line {line!r}")
        if cells[1] != "de":
            continue
        if cells[5] != "25":
            fail(f"coverage.csv German row without 25 heights: {line!r}")
        key = (cells[0], cells[3][:4] + cells[3][5:7])
        per_month[key] += int(cells[7])
        per_day[key][cells[3]] = int(cells[7])
    return dict(per_month), dict(per_day)


def neighbours(stored: float) -> tuple[float, float]:
    """Adjacent binary32 values via array reinterpretation (independent of struct)."""
    word = array("I", array("f", [stored]).tobytes())[0]
    above = array("f", array("I", [word + 1]).tobytes())[0]
    below = array("f", array("I", [word - 1]).tobytes())[0] if word else -above
    return above, below


def rederive(text: str, member: str) -> tuple[array, dict[str, int], int, int, int]:
    lines = text.split("\n")
    if lines[-1] != "":
        fail(f"{member}: CSV text does not end with a newline")
    lines.pop()
    header = lines[0].split(",")
    if len(header) != 26 or header[1] != "datetime" or header[2] != "height" or header[10] != "eta":
        fail(f"{member}: unexpected header {header}")
    if (len(lines) - 1) % 25:
        fail(f"{member}: data rows not a multiple of 25")
    values = array("f")
    day_rows: dict[str, int] = Counter()
    seen: set[str] = set()
    previous = ""
    profiles = order_breaks = coarse = 0
    for start in range(1, len(lines), 25):
        block = [line.split(",") for line in lines[start:start + 25]]
        stamp = block[0][1]
        if len(stamp) != 20 or stamp[10] != "T" or not stamp.endswith("Z") or stamp in seen:
            fail(f"{member}: bad or duplicate datetime {stamp!r}")
        if previous and stamp < previous:
            order_breaks += 1
        seen.add(stamp)
        previous = stamp
        profiles += 1
        day_rows[stamp[:10]] += 25
        for level, cells in enumerate(block):
            if len(cells) != 26 or cells[1] != stamp or cells[2] != HEIGHT_TOKENS[level]:
                fail(f"{member}: profile {stamp} level {level} malformed")
            token = cells[10]
            if token in MISSING:
                values.append(math.nan)
                continue
            if not NUMBER.fullmatch(token):
                fail(f"{member}: non-decimal eta token {token!r}")
            decimal = float(token)
            values.append(decimal)
            stored = values[-1]
            if not math.isfinite(stored) or stored < 0:
                fail(f"{member}: eta {token!r} is not a finite non-negative binary32")
            if stored == decimal:
                continue
            head, _, power = token.lower().partition("e")
            places = len(head) - head.index(".") - 1 if "." in head else 0
            unit = 10.0 ** (int(power or "0") - places)
            if abs(decimal - stored) > unit:
                fail(f"{member}: eta {token!r} is not within one last-place unit of binary32 {stored!r}")
            above, below = neighbours(stored)
            if not (above - decimal > unit and decimal - below > unit):
                coarse += 1
    return values, dict(day_rows), profiles, order_breaks, coarse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if manifest.get("dataset_id") != DATASET_ID or len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest does not declare the expected primary series")
    declared = series[0]

    per_month, per_day = coverage_counts(args.coverage)
    if len(per_month) != EXPECTED_SAMPLES or sum(per_month.values()) != EXPECTED_VALUES:
        fail("coverage.csv German totals changed")

    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_member: dict[str, dict] = {}
    for row in rows:
        missing = [key for key in INDEX_KEYS if key not in row]
        if missing:
            fail(f"index row missing {missing}")
        if (row["dataset_id"], row["series_id"], row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != (
            DATASET_ID, SERIES_ID, "float", 32, "little", 4
        ):
            fail(f"index row has wrong typing: {row['sample_path']}")
        if row["sample_size_bytes"] != 4 * row["value_count"] or row["value_count"] % 25:
            fail(f"index row size inconsistent: {row['sample_path']}")
        if row["source_member"] in by_member:
            fail(f"duplicate source member in index: {row['source_member']}")
        by_member[row["source_member"]] = row
    if len(rows) != EXPECTED_SAMPLES:
        fail(f"index has {len(rows)} rows, expected {EXPECTED_SAMPLES}")
    if len({row["sample_path"] for row in rows}) != len(rows):
        fail("duplicate sample paths in index")
    total_values = sum(row["value_count"] for row in rows)
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    if total_values != EXPECTED_VALUES:
        fail(f"indexed values {total_values} != {EXPECTED_VALUES}")
    if declared.get("sample_count") != len(rows) or declared.get("total_size_bytes") != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {declared.get('sample_count')}/{declared.get('total_size_bytes')} != realized {len(rows)}/{total_bytes}")
    expected_files = {(data_root / row["sample_path"]).resolve() for row in rows}
    series_dir = data_root / declared["output_path"]
    on_disk = {path.resolve() for path in series_dir.iterdir()}
    if on_disk != expected_files:
        fail(f"sample directory has {len(on_disk)} files; index lists {len(expected_files)}")

    verified = 0
    nan_total = zero_total = coarse_total = 0
    radars: set[str] = set()
    aggregate = hashlib.sha256()
    digests: dict[str, str] = {}
    with tarfile.open(args.archive, mode="r|gz") as tar:
        for info in tar:
            if not info.isfile():
                continue
            name = info.name
            if name.rsplit("/", 1)[-1].startswith("._"):
                continue
            match = MEMBER.fullmatch(name)
            if not match or match.group(1) != match.group(3) or match.group(2) != match.group(4)[:4]:
                fail(f"unexpected archive member {name}")
            radar, yyyymm = match.group(1), match.group(4)
            row = by_member.get(name)
            if row is None:
                fail(f"archive member {name} has no index row")
            text = gzip.decompress(tar.extractfile(info).read()).decode("utf-8")
            values, day_rows, profiles, order_breaks, coarse = rederive(text, name)
            if len(values) != per_month.get((radar, yyyymm)) or day_rows != per_day.get((radar, yyyymm)):
                fail(f"{name}: realized rows disagree with coverage.csv")
            if row["value_count"] != len(values) or row.get("sample_shape") != [profiles, 25]:
                fail(f"{name}: index value_count/shape disagree with re-derivation")
            if row.get("datetime_order_breaks") != order_breaks or row.get("decimal_coarse_count") != coarse:
                fail(f"{name}: index order-break/coarse-decimal counts disagree with re-derivation")
            coarse_total += coarse
            # Same missing-value policy as build: every missing slot is the
            # canonical little-endian quiet NaN word 0x7fc00000.
            words = array("I")
            words.frombytes(values.tobytes())
            finite: list[float] = []
            nan_positions = 0
            for position, value in enumerate(values):
                if value != value:
                    words[position] = NAN_WORD
                    nan_positions += 1
                else:
                    finite.append(value)
            if sys.byteorder != "little":
                words.byteswap()
            expected = words.tobytes()
            actual = (data_root / row["sample_path"]).read_bytes()
            if actual != expected:
                fail(f"{name}: emitted sample differs from independent re-derivation")
            digest = hashlib.sha256(actual).hexdigest()
            if digest != row["sha256"]:
                fail(f"{name}: sha256 mismatch")
            zeros = sum(1 for value in finite if value == 0.0)
            if nan_positions != row["nan_count"] or zeros != row["zero_count"]:
                fail(f"{name}: nan/zero counts disagree with index")
            if not finite:
                fail(f"{name}: degenerate sample, every eta value missing")
            if len(set(finite)) < 2 or zeros == len(finite):
                fail(f"{name}: degenerate sample, finite eta values constant")
            if min(finite) != row["finite_min"] or max(finite) != row["finite_max"]:
                fail(f"{name}: finite min/max disagree with index")
            nan_total += nan_positions
            zero_total += zeros
            radars.add(radar)
            digests[name] = digest
            verified += 1
            del by_member[name]
    if by_member:
        fail(f"index rows without archive member: {sorted(by_member)[:5]}")
    if verified != EXPECTED_SAMPLES or len(radars) != EXPECTED_RADARS:
        fail(f"verified {verified} samples from {len(radars)} radars")
    for row in sorted(rows, key=lambda r: (r["radar"], r["year_month"])):
        aggregate.update(bytes.fromhex(digests[row["source_member"]]))
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if stats.get("aggregate_sha256_of_sample_sha256s") != aggregate.hexdigest():
        fail("aggregate hash disagrees with ingest stats")
    if (
        stats.get("nan_values") != nan_total
        or stats.get("zero_values") != zero_total
        or stats.get("decimal_coarse_values") != coarse_total
        or stats.get("problems")
    ):
        fail("ingest stats disagree with re-derived NaN/zero/coarse totals or record problems")
    nan_fraction = nan_total / total_values
    if nan_fraction > 0.5:
        fail(f"NaN fraction {nan_fraction:.3f} is degenerate")
    print(
        f"verify_ok samples={verified} radars={len(radars)} values={total_values} bytes={total_bytes} "
        f"nan={nan_total} ({nan_fraction:.4f}) zero={zero_total} coarse_decimals={coarse_total} "
        f"aggregate_sha256={aggregate.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
