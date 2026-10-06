#!/usr/bin/env python3
"""Download validation and sample build for noaa_dcdb_csb_vessel_track_lonlat_f64.

Subcommands:
  check-object FILE KEY        validate one downloaded object (size, S3 ETag,
                               exact header, first-row FILE_UUID/PROVIDER)
                               against its selection.tsv row
  check-downloads              validate every kept object and write
                               downloads/<id>/download_manifest.tsv
  build                        parse every kept CSV and emit one interleaved
                               LON,LAT float64 sample per file

Standard library only. Network I/O is done by download.sh with curl.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import statistics
import sys
from array import array
from pathlib import Path
from typing import Any

DATASET_ID = "noaa_dcdb_csb_vessel_track_lonlat_f64"
SERIES_ID = "csb_vessel_track_lonlat_f64"
HEADER = ["UNIQUE_ID", "FILE_UUID", "LON", "LAT", "DEPTH", "TIME", "PLATFORM_NAME", "PROVIDER"]
SELECTION_SHA256 = "725be897a641e4b85213188fe90101c4f0b692dd4633cf15961f933a77f30536"
EXPECTED_LISTED_FILES = 2125
EXPECTED_LISTED_BYTES = 1_583_536_283
EXPECTED_KEEP_FILES = 900
EXPECTED_KEEP_BYTES = 1_172_429_139
KEEP_PROVIDERS = {"Rosepoint", "GLOS", "COMIT USF"}
S3_PART_SIZE = 5 * 1024 * 1024
# Filled in from the first successful build; enforced when set.
EXPECTED_SAMPLE_COUNT: int | None = 895
EXPECTED_TOTAL_BYTES: int | None = 81_457_776
EXPECTED_AGGREGATE_SHA256: str | None = "f17f68579da75162f88b3af234c9be8bdca11cee60a171652f1e63a8fab11c4f"

# Plain decimal with at most six fractional digits: the 1e-6 degree lattice.
LATTICE_TOKEN = re.compile(r"-?[0-9]{1,3}(?:\.[0-9]{1,6})?")
# Effective sub-lattices inside the printed 1e-6 lattice, from micro-degree
# magnitudes n = |value| * 1e6:
# - degrees converted from NMEA minutes with 3 decimals (1/60,000 degree)
#   give n = round(50k/3), so n mod 50 is always 0, 17 or 33;
# - minutes with 4 decimals (1/600,000 degree) give n = round(5k/3), so
#   n mod 5 is always 0, 2 or 3.
COARSE_RESIDUES_MOD50 = frozenset({0, 17, 33})
NMEA4_RESIDUES_MOD5 = frozenset({0, 2, 3})
MIN_DISTINCT_FOR_QUANTUM = 50
COARSE_EXCLUDE_FRACTION = 0.9


def data_root(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def s3_etag(path: Path) -> str:
    """Composite multipart ETag with 5 MiB parts, as used by this bucket."""
    part_digests = []
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(S3_PART_SIZE), b""):
            part_digests.append(hashlib.md5(block).digest())
    if not part_digests:
        part_digests.append(hashlib.md5(b"").digest())
    return hashlib.md5(b"".join(part_digests)).hexdigest() + f"-{len(part_digests)}"


def read_selection(recipe_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    path = recipe_dir / "selection.tsv"
    if file_sha256(path) != SELECTION_SHA256:
        raise SystemExit("selection.tsv SHA-256 differs from the pinned value")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_LISTED_FILES or sum(int(r["size_bytes"]) for r in rows) != EXPECTED_LISTED_BYTES:
        raise SystemExit("selection.tsv listed totals changed")
    keep = [row for row in rows if row["decision"] == "keep"]
    if len(keep) != EXPECTED_KEEP_FILES or sum(int(r["size_bytes"]) for r in keep) != EXPECTED_KEEP_BYTES:
        raise SystemExit("selection.tsv keep totals changed")
    if any(row["provider"] not in KEEP_PROVIDERS for row in keep):
        raise SystemExit("selection.tsv keeps an unreviewed provider")
    names = [row["key"].rsplit("/", 1)[1] for row in keep]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate kept object basename")
    return rows, keep


def object_name(row: dict[str, str]) -> str:
    return row["key"].rsplit("/", 1)[1]


def file_uuid(row: dict[str, str]) -> str:
    name = object_name(row)
    if not name.endswith("_pointData.csv"):
        raise SystemExit(f"unexpected object name {name}")
    return name[: -len("_pointData.csv")]


def check_object(path: Path, row: dict[str, str]) -> None:
    size = path.stat().st_size
    if size != int(row["size_bytes"]):
        raise SystemExit(f"{path.name}: size {size} != pinned {row['size_bytes']}")
    etag = s3_etag(path)
    if etag != row["etag"]:
        raise SystemExit(f"{path.name}: ETag {etag} != pinned {row['etag']}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        first = next(reader, None)
    if header != HEADER:
        raise SystemExit(f"{path.name}: unexpected header {header}")
    if first is None or len(first) != 8:
        raise SystemExit(f"{path.name}: no well-formed first data row")
    if first[1] != file_uuid(row) or first[7] != row["provider"] or first[0] != row["unique_id"]:
        raise SystemExit(f"{path.name}: first row FILE_UUID/PROVIDER/UNIQUE_ID disagree with selection")


def parse_time(text: str) -> dt.datetime | None:
    try:
        value = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value


def classify_token(token: str) -> tuple[str, float | None]:
    """Return (class, value) with class in lattice/off_lattice/invalid."""
    if LATTICE_TOKEN.fullmatch(token):
        return "lattice", float(token)
    try:
        value = float(token)
    except ValueError:
        return "invalid", None
    if not math.isfinite(value):
        return "invalid", None
    return "off_lattice", value


def parse_csv(path: Path, row: dict[str, str]) -> dict[str, Any]:
    """Parse one CSB CSV and apply the missing-value and lattice policies."""
    expected_uuid = file_uuid(row)
    values = array("d")
    stats = {
        "source_rows": 0,
        "kept_rows": 0,
        "dropped_invalid_coordinate": 0,
        "dropped_out_of_range": 0,
        "dropped_null_island": 0,
        "off_lattice_tokens": 0,
        "unparsed_time_rows": 0,
        "fraction_digits": [0] * 7,
    }
    first_pair: tuple[float, float] | None = None
    distinct_fixes = False
    magnitudes: set[int] = set()
    time_min: dt.datetime | None = None
    time_max: dt.datetime | None = None
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != HEADER:
            raise SystemExit(f"{path.name}: unexpected header")
        for line_number, fields in enumerate(reader, 2):
            if len(fields) != 8:
                raise SystemExit(f"{path.name}:{line_number}: expected 8 fields, got {len(fields)}")
            unique_id, uuid, lon_text, lat_text, _depth, time_text, _platform, provider = fields
            if uuid != expected_uuid or provider != row["provider"] or unique_id != row["unique_id"]:
                raise SystemExit(f"{path.name}:{line_number}: FILE_UUID/PROVIDER/UNIQUE_ID changed within file")
            stats["source_rows"] += 1
            lon_class, lon = classify_token(lon_text)
            lat_class, lat = classify_token(lat_text)
            if lon_class == "invalid" or lat_class == "invalid":
                stats["dropped_invalid_coordinate"] += 1
                continue
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                stats["dropped_out_of_range"] += 1
                continue
            if lon == 0.0 and lat == 0.0:
                stats["dropped_null_island"] += 1
                continue
            for token, token_class in ((lon_text, lon_class), (lat_text, lat_class)):
                if token_class == "off_lattice":
                    stats["off_lattice_tokens"] += 1
                else:
                    point = token.find(".")
                    stats["fraction_digits"][0 if point < 0 else len(token) - point - 1] += 1
            values.append(lon)
            values.append(lat)
            magnitudes.add(round(abs(lon) * 1e6))
            magnitudes.add(round(abs(lat) * 1e6))
            stats["kept_rows"] += 1
            if first_pair is None:
                first_pair = (lon, lat)
            elif not distinct_fixes and (lon, lat) != first_pair:
                distinct_fixes = True
            moment = parse_time(time_text)
            if moment is None:
                stats["unparsed_time_rows"] += 1
            else:
                if time_min is None or moment < time_min:
                    time_min = moment
                if time_max is None or moment > time_max:
                    time_max = moment
    quantum = coordinate_quantum(magnitudes)
    if stats["off_lattice_tokens"]:
        exclusion = "off_lattice_coordinate_text"
    elif stats["kept_rows"] == 0:
        exclusion = "no_valid_fixes"
    elif not distinct_fixes:
        exclusion = "fewer_than_two_distinct_fixes"
    elif quantum == "1/60000_deg":
        exclusion = "coarse_1_60000_degree_sublattice"
    else:
        exclusion = ""
    return {
        "coordinate_quantum": quantum,
        "distinct_micro_degree_magnitudes": len(magnitudes),
        "values": values,
        "stats": stats,
        "exclusion": exclusion,
        "time_min": time_min,
        "time_max": time_max,
    }


def coordinate_quantum(magnitudes: set[int]) -> str:
    """Classify the effective coordinate quantum of one file."""
    if len(magnitudes) < MIN_DISTINCT_FOR_QUANTUM:
        return "unclassified_lt50_distinct"
    coarse = sum(1 for n in magnitudes if n % 50 in COARSE_RESIDUES_MOD50)
    if coarse >= COARSE_EXCLUDE_FRACTION * len(magnitudes):
        return "1/60000_deg"
    if all(n % 5 in NMEA4_RESIDUES_MOD5 for n in magnitudes):
        return "1/600000_deg"
    return "1e-6_deg"


def to_le_bytes(values: array) -> bytes:
    if values.itemsize != 8:
        raise SystemExit("platform double is not 8 bytes")
    if sys.byteorder != "little":
        values = array("d", values)
        values.byteswap()
    return values.tobytes()


def cmd_check_object(args: argparse.Namespace) -> None:
    _, keep = read_selection(args.recipe_dir)
    matches = [row for row in keep if row["key"] == args.key]
    if len(matches) != 1:
        raise SystemExit(f"key not in kept selection: {args.key}")
    check_object(args.file, matches[0])


def cmd_check_downloads(args: argparse.Namespace) -> None:
    root = data_root(args.repo_root, args.data_dir)
    csv_dir = root / "downloads" / DATASET_ID / "csv"
    _, keep = read_selection(args.recipe_dir)
    lines = ["key\tsize_bytes\tetag\tsha256\n"]
    total = 0
    for row in keep:
        path = csv_dir / object_name(row)
        if not path.is_file():
            raise SystemExit(f"missing download {path}")
        check_object(path, row)
        total += path.stat().st_size
        lines.append(f"{row['key']}\t{row['size_bytes']}\t{row['etag']}\t{file_sha256(path)}\n")
    (root / "downloads" / DATASET_ID / "download_manifest.tsv").write_text("".join(lines), encoding="utf-8")
    print(f"validated_objects={len(keep)} bytes={total}")


def cmd_build(args: argparse.Namespace) -> None:
    root = data_root(args.repo_root, args.data_dir)
    csv_dir = root / "downloads" / DATASET_ID / "csv"
    sample_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_dir = root / "index" / DATASET_ID
    filtered_dir = root / "filtered" / DATASET_ID
    _, keep = read_selection(args.recipe_dir)

    shutil.rmtree(root / "samples" / DATASET_ID, ignore_errors=True)
    sample_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    totals = {
        "source_rows": 0, "kept_rows": 0, "dropped_invalid_coordinate": 0,
        "dropped_out_of_range": 0, "dropped_null_island": 0, "unparsed_time_rows": 0,
    }
    fraction_digits = [0] * 7
    payload_hashes: dict[str, str] = {}
    intervals: dict[str, list[tuple[dt.datetime, dt.datetime, str]]] = {}
    aggregate = hashlib.sha256()
    provider_counts: dict[str, dict[str, int]] = {}
    quantum_counts: dict[str, dict[str, int]] = {}

    for number, row in enumerate(keep, 1):
        path = csv_dir / object_name(row)
        if not path.is_file():
            raise SystemExit(f"missing download {path}")
        if path.stat().st_size != int(row["size_bytes"]) or s3_etag(path) != row["etag"]:
            raise SystemExit(f"{path.name}: local object does not match pinned size/ETag")
        parsed = parse_csv(path, row)
        stats = parsed["stats"]
        for key in totals:
            totals[key] += stats[key]
        if parsed["exclusion"]:
            excluded.append({
                "key": row["key"], "provider": row["provider"], "reason": parsed["exclusion"],
                "source_rows": stats["source_rows"], "kept_rows": stats["kept_rows"],
                "coordinate_quantum": parsed["coordinate_quantum"],
            })
            continue
        for digits, count in enumerate(stats["fraction_digits"]):
            fraction_digits[digits] += count
        payload = to_le_bytes(parsed["values"])
        digest = hashlib.sha256(payload).hexdigest()
        if digest in payload_hashes:
            raise SystemExit(f"duplicate payload: {row['key']} == {payload_hashes[digest]}")
        payload_hashes[digest] = row["key"]
        if parsed["time_min"] is not None:
            intervals.setdefault(row["unique_id"], []).append((parsed["time_min"], parsed["time_max"], row["key"]))
        aggregate.update(payload)
        relative = Path("samples") / DATASET_ID / SERIES_ID / f"{file_uuid(row)}.bin"
        (root / relative).write_bytes(payload)
        stored = parsed["values"]
        lons, lats = stored[0::2], stored[1::2]
        rows_kept = stats["kept_rows"]
        records.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": relative.as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(payload),
            "value_count": 2 * rows_kept,
            "sample_format": "raw little-endian float64 interleaved LON,LAT degree pairs",
            "sample_rank": 2,
            "sample_shape": [rows_kept, 2],
            "sample_axes": ["sounding_fix_in_file_order", "lon_lat"],
            "natural_record_kind": "dcdb_csb_trusted_node_submission_file",
            "coordinate_quantum": parsed["coordinate_quantum"],
            "distinct_micro_degree_magnitudes": parsed["distinct_micro_degree_magnitudes"],
            "source_key": row["key"],
            "source_etag": row["etag"],
            "source_size_bytes": int(row["size_bytes"]),
            "provider": row["provider"],
            "source_rows": stats["source_rows"],
            "dropped_rows": stats["source_rows"] - rows_kept,
            "lon_min": min(lons), "lon_max": max(lons),
            "lat_min": min(lats), "lat_max": max(lats),
            "min_value": min(stored), "max_value": max(stored),
            "sha256": digest,
        })
        for table, name in ((provider_counts, row["provider"]), (quantum_counts, parsed["coordinate_quantum"])):
            counts = table.setdefault(name, {"samples": 0, "values": 0, "bytes": 0})
            counts["samples"] += 1
            counts["values"] += 2 * rows_kept
            counts["bytes"] += len(payload)
        if number % 100 == 0:
            print(f"parsed {number}/{len(keep)} objects")

    overlaps = []
    for unique_id, spans in intervals.items():
        spans.sort()
        latest_end, latest_key = None, ""
        for start, end, key in spans:
            if latest_end is not None and start < latest_end:
                overlaps.append(f"{key} overlaps {latest_key}")
            if latest_end is None or end > latest_end:
                latest_end, latest_key = end, key
    if overlaps:
        raise SystemExit("overlapping kept submissions of one vessel: " + "; ".join(overlaps[:5]))

    lengths = sorted(record["value_count"] for record in records)
    sampled_keys = set(payload_hashes.values())
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "selection_sha256": SELECTION_SHA256,
        "kept_objects": len(keep),
        "kept_object_bytes": sum(int(row["size_bytes"]) for row in keep),
        "sample_count": len(records),
        "value_count": sum(lengths),
        "total_size_bytes": sum(record["sample_size_bytes"] for record in records),
        "min_sample_values": lengths[0] if lengths else 0,
        "median_sample_values": statistics.median(lengths) if lengths else 0,
        "max_sample_values": lengths[-1] if lengths else 0,
        "vessels": len({row["unique_id"] for row in keep if row["key"] in sampled_keys}),
        "row_totals": totals,
        "kept_fraction_digit_histogram": fraction_digits,
        "excluded_objects": excluded,
        "providers": provider_counts,
        "coordinate_quanta": quantum_counts,
        "aggregate_sha256": aggregate.hexdigest(),
    }
    if not records:
        raise SystemExit("no samples produced")
    if totals["source_rows"] and (totals["source_rows"] - totals["kept_rows"]) > 0.01 * totals["source_rows"]:
        raise SystemExit(f"more than 1% of rows dropped: {totals}")
    if EXPECTED_SAMPLE_COUNT is not None and summary["sample_count"] != EXPECTED_SAMPLE_COUNT:
        raise SystemExit(f"sample count {summary['sample_count']} != expected {EXPECTED_SAMPLE_COUNT}")
    if EXPECTED_TOTAL_BYTES is not None and summary["total_size_bytes"] != EXPECTED_TOTAL_BYTES:
        raise SystemExit(f"total bytes {summary['total_size_bytes']} != expected {EXPECTED_TOTAL_BYTES}")
    if EXPECTED_AGGREGATE_SHA256 is not None and summary["aggregate_sha256"] != EXPECTED_AGGREGATE_SHA256:
        raise SystemExit("aggregate output SHA-256 changed")

    (index_dir / "samples.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8"
    )
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={summary['sample_count']} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']} median_values={summary['median_sample_values']} "
        f"excluded={len(excluded)} rows={totals}"
    )
    print(f"aggregate_sha256={summary['aggregate_sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    parser.add_argument("--recipe-dir", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check-object")
    one.add_argument("file", type=Path)
    one.add_argument("key")
    sub.add_parser("check-downloads")
    sub.add_parser("build")
    args = parser.parse_args()
    {"check-object": cmd_check_object, "check-downloads": cmd_check_downloads, "build": cmd_build}[args.command](args)


if __name__ == "__main__":
    main()
