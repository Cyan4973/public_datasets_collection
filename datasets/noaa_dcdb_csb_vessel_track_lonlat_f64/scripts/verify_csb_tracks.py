#!/usr/bin/env python3
"""Independent verification for noaa_dcdb_csb_vessel_track_lonlat_f64.

This does not import the build code. It re-reads every kept source CSV with
byte-level line splitting (not the csv module), converts LON/LAT text to
integer micro-degrees by string arithmetic, applies the same missing-value
and lattice policy as build, and then checks that every stored float64 equals
the micro-degree integer divided by 1e6 exactly. It also re-derives the index
rows, the exclusion list, per-vessel non-overlap, payload uniqueness, the
ingest summary, and the manifest totals.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import statistics
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "noaa_dcdb_csb_vessel_track_lonlat_f64"
SERIES_ID = "csb_vessel_track_lonlat_f64"
HEADER = b"UNIQUE_ID,FILE_UUID,LON,LAT,DEPTH,TIME,PLATFORM_NAME,PROVIDER"
SELECTION_SHA256 = "725be897a641e4b85213188fe90101c4f0b692dd4633cf15961f933a77f30536"
EXPECTED_KEEP_FILES = 900
EXPECTED_KEEP_BYTES = 1_172_429_139
PART = 5 * 1024 * 1024
MICRO_TOKEN = re.compile(rb"(-?)([0-9]{1,3})(?:\.([0-9]{1,6}))?")
LON_LIMIT = 180_000_000
LAT_LIMIT = 90_000_000


def quantum_of(magnitudes: set[int]) -> str:
    """Effective quantum from integer micro-degree magnitudes.

    3-decimal NMEA minutes (1/60,000 deg) leave n mod 50 in {0, 17, 33};
    4-decimal minutes (1/600,000 deg) leave n mod 5 in {0, 2, 3}.
    """
    total = len(magnitudes)
    if total < 50:
        return "unclassified_lt50_distinct"
    if 10 * sum(1 for n in magnitudes if n % 50 in (0, 17, 33)) >= 9 * total:
        return "1/60000_deg"
    if all(n % 5 in (0, 2, 3) for n in magnitudes):
        return "1/600000_deg"
    return "1e-6_deg"


def fail(message: str) -> None:
    raise SystemExit(f"verify failed: {message}")


def root_of(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def selection(recipe_dir: Path) -> list[dict[str, str]]:
    raw = (recipe_dir / "selection.tsv").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SELECTION_SHA256:
        fail("selection.tsv hash changed")
    lines = raw.decode("utf-8").splitlines()
    columns = lines[0].split("\t")
    rows = [dict(zip(columns, line.split("\t"))) for line in lines[1:]]
    keep = [row for row in rows if row["decision"] == "keep"]
    if len(keep) != EXPECTED_KEEP_FILES or sum(int(row["size_bytes"]) for row in keep) != EXPECTED_KEEP_BYTES:
        fail("kept selection totals changed")
    return keep


def etag_of(path: Path) -> str:
    digests = []
    with path.open("rb") as handle:
        while True:
            block = handle.read(PART)
            if not block:
                break
            digests.append(hashlib.md5(block).digest())
    return hashlib.md5(b"".join(digests)).hexdigest() + "-" + str(len(digests))


def micro(token: bytes) -> tuple[str, int | float | None]:
    match = MICRO_TOKEN.fullmatch(token)
    if match:
        sign, whole, fraction = match.groups()
        value = int(whole) * 1_000_000 + (int(fraction.ljust(6, b"0")) if fraction else 0)
        return "lattice", -value if sign else value
    try:
        number = float(token)
    except ValueError:
        return "invalid", None
    return ("off_lattice", number) if math.isfinite(number) else ("invalid", None)


def when(text: bytes) -> dt.datetime | None:
    try:
        moment = dt.datetime.fromisoformat(text.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def expected_from_source(path: Path, row: dict[str, str]) -> dict:
    stem = path.name[: -len("_pointData.csv")].encode()
    provider = row["provider"].encode()
    unique_id = row["unique_id"].encode()
    pairs = array("q")
    source_rows = invalid = out_of_range = null_island = off_lattice = 0
    t_min = t_max = None
    first_pair = None
    moving = False
    magnitudes: set[int] = set()
    with path.open("rb") as handle:
        if handle.readline().rstrip(b"\r\n") != HEADER:
            fail(f"{path.name}: header")
        for number, line in enumerate(handle, 2):
            line = line.rstrip(b"\r\n")
            if not line:
                fail(f"{path.name}:{number}: blank line")
            parts = line.split(b",", 6)
            if len(parts) != 7 or b"," not in parts[6]:
                fail(f"{path.name}:{number}: too few fields")
            if parts[0] != unique_id or parts[1] != stem or parts[6].rsplit(b",", 1)[1] != provider:
                fail(f"{path.name}:{number}: identity columns changed")
            source_rows += 1
            lon_kind, lon = micro(parts[2])
            lat_kind, lat = micro(parts[3])
            if lon_kind == "invalid" or lat_kind == "invalid":
                invalid += 1
                continue
            lon_ok = abs(lon) <= LON_LIMIT if lon_kind == "lattice" else abs(lon) <= 180.0
            lat_ok = abs(lat) <= LAT_LIMIT if lat_kind == "lattice" else abs(lat) <= 90.0
            if not (lon_ok and lat_ok):
                out_of_range += 1
                continue
            if lon == 0 and lat == 0:
                null_island += 1
                continue
            if lon_kind == "off_lattice" or lat_kind == "off_lattice":
                # The whole file is excluded; the row still counts as kept
                # (not dropped), matching build's per-file accounting.
                off_lattice += (lon_kind == "off_lattice") + (lat_kind == "off_lattice")
                pairs.append(0)
                pairs.append(0)
                continue
            pairs.append(lon)
            pairs.append(lat)
            magnitudes.add(abs(lon))
            magnitudes.add(abs(lat))
            if first_pair is None:
                first_pair = (lon, lat)
            elif not moving and (lon, lat) != first_pair:
                moving = True
            moment = when(parts[5])
            if moment is not None:
                t_min = moment if t_min is None or moment < t_min else t_min
                t_max = moment if t_max is None or moment > t_max else t_max
    kept = len(pairs) // 2
    quantum = quantum_of(magnitudes)
    if off_lattice:
        reason = "off_lattice_coordinate_text"
    elif kept == 0:
        reason = "no_valid_fixes"
    elif not moving:
        reason = "fewer_than_two_distinct_fixes"
    elif quantum == "1/60000_deg":
        reason = "coarse_1_60000_degree_sublattice"
    else:
        reason = ""
    return {
        "quantum": quantum, "distinct": len(magnitudes),
        "pairs": pairs, "source_rows": source_rows, "kept_rows": kept, "reason": reason,
        "dropped": {"invalid": invalid, "out_of_range": out_of_range, "null_island": null_island},
        "t_min": t_min, "t_max": t_max,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    root = root_of(args.repo_root, args.data_dir)
    keep = selection(args.recipe_dir)
    csv_dir = root / "downloads" / DATASET_ID / "csv"
    sample_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    summary_path = root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not summary_path.is_file():
        fail("build outputs missing")
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key = {record["source_key"]: record for record in index}
    if len(by_key) != len(index):
        fail("duplicate source_key in index")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    excluded = []
    hashes: set[str] = set()
    spans: dict[str, list[tuple]] = {}
    expected_paths = set()
    lengths = []
    total_bytes = 0
    distinct_lon: set[float] = set()
    distinct_lat: set[float] = set()
    dropped_total = 0
    source_total = 0
    quanta: dict[str, dict[str, int]] = {}
    for number, row in enumerate(keep, 1):
        name = row["key"].rsplit("/", 1)[1]
        path = csv_dir / name
        if not path.is_file() or path.stat().st_size != int(row["size_bytes"]) or etag_of(path) != row["etag"]:
            fail(f"{name}: source missing or size/ETag mismatch")
        expected = expected_from_source(path, row)
        source_total += expected["source_rows"]
        dropped_total += expected["source_rows"] - expected["kept_rows"]
        record = by_key.get(row["key"])
        if expected["reason"]:
            if record is not None:
                fail(f"{name}: should be excluded ({expected['reason']}) but has a sample")
            excluded.append({
                "key": row["key"], "provider": row["provider"], "reason": expected["reason"],
                "source_rows": expected["source_rows"], "kept_rows": expected["kept_rows"],
                "coordinate_quantum": expected["quantum"],
            })
            continue
        if record is None:
            fail(f"{name}: expected a sample")
        relative = f"samples/{DATASET_ID}/{SERIES_ID}/{name[:-len('_pointData.csv')]}.bin"
        if record["sample_path"] != relative:
            fail(f"{name}: sample_path {record['sample_path']}")
        expected_paths.add(relative)
        raw = (root / relative).read_bytes()
        pairs = expected["pairs"]
        if len(raw) != 8 * len(pairs):
            fail(f"{name}: sample length {len(raw)} != {8 * len(pairs)}")
        stored = array("d")
        stored.frombytes(raw)
        if sys.byteorder != "little":
            stored.byteswap()
        for position, (value, micro_value) in enumerate(zip(stored, pairs)):
            if value != micro_value / 1e6:
                fail(f"{name}: value {position} = {value!r}, source micro-degrees {micro_value}")
        lons, lats = stored[0::2], stored[1::2]
        if max(map(abs, lons)) > 180.0 or max(map(abs, lats)) > 90.0:
            fail(f"{name}: stored coordinate out of range")
        digest = hashlib.sha256(raw).hexdigest()
        if digest in hashes:
            fail(f"{name}: duplicate payload")
        hashes.add(digest)
        derived = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8,
            "sample_size_bytes": len(raw), "value_count": len(pairs),
            "sample_shape": [len(pairs) // 2, 2], "source_etag": row["etag"],
            "source_size_bytes": int(row["size_bytes"]), "provider": row["provider"],
            "source_rows": expected["source_rows"],
            "dropped_rows": expected["source_rows"] - expected["kept_rows"],
            "lon_min": min(lons), "lon_max": max(lons), "lat_min": min(lats), "lat_max": max(lats),
            "min_value": min(stored), "max_value": max(stored), "sha256": digest,
            "coordinate_quantum": expected["quantum"],
            "distinct_micro_degree_magnitudes": expected["distinct"],
        }
        for key, value in derived.items():
            if record.get(key) != value:
                fail(f"{name}: index field {key}={record.get(key)!r} != re-derived {value!r}")
        if expected["t_min"] is not None:
            spans.setdefault(row["unique_id"], []).append((expected["t_min"], expected["t_max"], name))
        lengths.append(len(pairs))
        total_bytes += len(raw)
        bucket = quanta.setdefault(expected["quantum"], {"samples": 0, "values": 0, "bytes": 0})
        bucket["samples"] += 1
        bucket["values"] += len(pairs)
        bucket["bytes"] += len(raw)
        if len(distinct_lon) < 100_000:
            distinct_lon.update(lons[:1000])
            distinct_lat.update(lats[:1000])
        if number % 100 == 0:
            print(f"verified {number}/{len(keep)} objects")

    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in sample_dir.iterdir()}
    if on_disk != expected_paths or len(index) != len(expected_paths):
        fail("sample directory or index contains unexpected entries")
    for unique_id, items in spans.items():
        items.sort()
        latest = None
        for start, end, name in items:
            if latest is not None and start < latest:
                fail(f"{name}: overlaps an earlier kept submission of {unique_id}")
            latest = end if latest is None or end > latest else latest
    if len(distinct_lon) < 100 or len(distinct_lat) < 100:
        fail("series is degenerate (too few distinct coordinates)")
    if dropped_total > 0.01 * source_total:
        fail("more than 1% of source rows dropped")

    lengths.sort()
    checks = {
        "sample_count": len(lengths), "value_count": sum(lengths), "total_size_bytes": total_bytes,
        "median_sample_values": statistics.median(lengths), "excluded_objects": excluded,
        "coordinate_quanta": quanta,
    }
    for key, value in checks.items():
        if summary.get(key) != value:
            fail(f"ingest summary {key}={summary.get(key)!r} != re-derived {value!r}")
    if statistics.median(lengths) < 1000 or sum(lengths) < 10_000:
        fail("below acceptance floor")
    if "1/60000_deg" in quanta:
        fail("a coarse 1/60,000-degree file reached the output")

    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [entry for entry in manifest["series"] if entry["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    if series[0]["sample_count"] != len(lengths) or series[0]["total_size_bytes"] != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
            f"!= realized {len(lengths)}/{total_bytes}"
        )
    print(
        f"verified samples={len(lengths)} values={sum(lengths)} bytes={total_bytes} "
        f"median_values={statistics.median(lengths)} excluded={len(excluded)} dropped_rows={dropped_total}"
    )


if __name__ == "__main__":
    main()
