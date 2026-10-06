#!/usr/bin/env python3
"""Preflight and build for cesnet_ts24_institution_traffic_bytes_u64.

Subcommands:
  preflight  validate the Zenodo record metadata, the 10-minute time grid and
             the structure of institutions.tar.gz (called by download.sh)
  build      stream institutions.tar.gz and emit one little-endian uint64
             n_bytes sample (primary) plus one uint32 id_time sample
             (auxiliary) per institution 10-minute CSV

Pure standard library. The archive is read once, sequentially, with tarfile
stream mode ('r|gz'); member order is never assumed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import statistics
import struct
import sys
import tarfile
from pathlib import Path

DATASET_ID = "cesnet_ts24_institution_traffic_bytes_u64"
PRIMARY_SERIES = "institution_n_bytes_u64"
AUX_SERIES = "institution_id_time_u32"
IDENTIFIERS_MEMBER = "institutions/identifiers.csv"
TEN_MIN_RE = re.compile(r"^institutions/agg_10_minutes/([0-9]+)\.csv$")
TIMES_MEMBER = "times/times_10_minutes.csv"
DIGITS = re.compile(rb"^[0-9]+\Z")
U64_MAX = (1 << 64) - 1
U32_MAX = (1 << 32) - 1
STREAM_BUFSIZE = 1 << 20

PINNED_FILES = {
    "institutions.tar.gz": (479428489, "ab3e15fb8dc9b7120ddb2318795b6812"),
    "times.tar.gz": (211467, "a03813763e07646ca38f17ffd53e549e"),
}


class BuildError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise BuildError(message)


def log(message: str) -> None:
    print(message, flush=True)


# ---------------------------------------------------------------- metadata --

def check_record(record_path: Path) -> dict:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    license_id = (metadata.get("license") or {}).get("id")
    if license_id != "cc-by-4.0":
        fail(f"record license is {license_id!r}, expected 'cc-by-4.0'")
    if metadata.get("access_right") != "open":
        fail(f"record access_right is {metadata.get('access_right')!r}, expected 'open'")
    if record.get("doi") != "10.5281/zenodo.13382427":
        fail(f"record doi is {record.get('doi')!r}")
    if "CESNET-TimeSeries24" not in str(metadata.get("title", "")):
        fail(f"record title {metadata.get('title')!r} does not name CESNET-TimeSeries24")
    files = {entry.get("key"): entry for entry in record.get("files", [])}
    for key, (size, md5) in PINNED_FILES.items():
        entry = files.get(key)
        if entry is None:
            fail(f"record does not list {key}")
        if int(entry.get("size", -1)) != size or entry.get("checksum") != f"md5:{md5}":
            fail(f"record entry for {key} is size={entry.get('size')} checksum={entry.get('checksum')}, expected {size} md5:{md5}")
    log(f"record_ok doi={record['doi']} license={license_id} files_pinned={len(PINNED_FILES)}")
    return {"doi": record["doi"], "license": license_id, "title": metadata.get("title")}


def load_time_grid(times_path: Path, expected_windows: int) -> int:
    with tarfile.open(times_path, mode="r:gz") as archive:
        member = archive.getmember(TIMES_MEMBER)
        handle = archive.extractfile(member)
        if handle is None:
            fail(f"{TIMES_MEMBER} is not a regular file")
        raw = handle.read()
    text = raw.decode("ascii")
    lines = text.split("\n")
    if lines[0] != "id_time,time":
        fail(f"unexpected time-grid header {lines[0]!r}")
    if lines[-1] != "":
        fail("time grid does not end with a newline")
    body = lines[1:-1]
    for position, line in enumerate(body):
        id_text, _, stamp = line.partition(",")
        if id_text != str(position) or not re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[+-]\d\d:\d\d$", stamp):
            fail(f"time grid row {position} malformed: {line!r}")
    if len(body) != expected_windows:
        fail(f"time grid has {len(body)} windows, expected {expected_windows}")
    log(f"time_grid_ok windows={len(body)} first={body[0]} last={body[-1]}")
    return len(body)


def parse_identifiers(raw: bytes) -> list[int]:
    lines = raw.decode("ascii").split("\n")
    if lines[0] != "id_institution":
        fail(f"unexpected identifiers header {lines[0]!r}")
    if lines[-1] == "":
        lines = lines[:-1]
    ids: list[int] = []
    for line in lines[1:]:
        if not DIGITS.match(line.encode("ascii")):
            fail(f"malformed institution id {line!r}")
        ids.append(int(line))
    if len(ids) != len(set(ids)):
        fail("duplicate institution ids in identifiers.csv")
    return ids


def iter_archive(archive_path: Path):
    with tarfile.open(archive_path, mode="r|gz", bufsize=STREAM_BUFSIZE) as archive:
        for member in archive:
            yield archive, member


# ------------------------------------------------------------------- parse --

def parse_ten_minute_csv(raw: bytes, label: str, window_count: int) -> tuple[list[int], list[int]]:
    """Return (id_time list, n_bytes list) for the present windows, in order.

    A header-only member returns two empty lists; the caller decides whether
    that institution is one of the pinned empty upstream records.
    """
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as exc:
        fail(f"{label}: non-ASCII content ({exc})")
    if b"\r" in raw:
        fail(f"{label}: carriage return found; expected LF-only CSV")
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        fail(f"{label}: empty file")
    header = lines[0].split(b",")
    if header.count(b"id_time") != 1 or header.count(b"n_bytes") != 1:
        fail(f"{label}: header must contain id_time and n_bytes exactly once: {lines[0][:200]!r}")
    time_col = header.index(b"id_time")
    bytes_col = header.index(b"n_bytes")
    width = len(header)
    times: list[int] = []
    values: list[int] = []
    previous = -1
    for line_number, line in enumerate(lines[1:], 2):
        fields = line.split(b",")
        if len(fields) != width:
            fail(f"{label}:{line_number}: {len(fields)} fields, header has {width}")
        time_text = fields[time_col]
        value_text = fields[bytes_col]
        if not DIGITS.match(time_text):
            fail(f"{label}:{line_number}: id_time {time_text!r} is not a non-negative decimal integer")
        if not DIGITS.match(value_text):
            fail(f"{label}:{line_number}: n_bytes {value_text!r} is not a non-negative decimal integer")
        time_id = int(time_text)
        value = int(value_text)
        if time_id <= previous:
            fail(f"{label}:{line_number}: id_time {time_id} not strictly increasing (previous {previous})")
        if time_id >= window_count:
            fail(f"{label}:{line_number}: id_time {time_id} outside the {window_count}-window grid")
        if value > U64_MAX:
            fail(f"{label}:{line_number}: n_bytes {value} exceeds uint64")
        previous = time_id
        times.append(time_id)
        values.append(value)
    return times, values


# --------------------------------------------------------------- preflight --

def cmd_preflight(args: argparse.Namespace) -> None:
    record = check_record(args.record)
    windows = load_time_grid(args.times, args.expected_windows)
    identifiers: list[int] | None = None
    ten_minute: dict[int, int] = {}
    other_counts: dict[str, int] = {}
    headers: dict[bytes, int] = {}
    for archive, member in iter_archive(args.archive):
        name = member.name
        if name == IDENTIFIERS_MEMBER:
            handle = archive.extractfile(member)
            identifiers = parse_identifiers(handle.read())
            continue
        match = TEN_MIN_RE.match(name)
        if match and member.isfile():
            institution = int(match.group(1))
            if institution in ten_minute:
                fail(f"duplicate archive member {name}")
            handle = archive.extractfile(member)
            first_line = handle.readline().rstrip(b"\n")
            fields = first_line.split(b",")
            if fields.count(b"id_time") != 1 or fields.count(b"n_bytes") != 1:
                fail(f"{name}: header lacks id_time/n_bytes: {first_line[:200]!r}")
            headers[first_line] = headers.get(first_line, 0) + 1
            ten_minute[institution] = member.size
            continue
        bucket = name.split("/")[1] if name.count("/") >= 1 else name
        other_counts[bucket] = other_counts.get(bucket, 0) + 1
    if identifiers is None:
        fail(f"{IDENTIFIERS_MEMBER} missing from archive")
    if len(identifiers) != args.expected_institutions:
        fail(f"identifiers.csv lists {len(identifiers)} institutions, expected {args.expected_institutions}")
    if set(ten_minute) != set(identifiers):
        missing = sorted(set(identifiers) - set(ten_minute))[:10]
        extra = sorted(set(ten_minute) - set(identifiers))[:10]
        fail(f"agg_10_minutes members disagree with identifiers.csv: missing={missing} extra={extra}")
    profile = {
        "dataset_id": DATASET_ID,
        "record": record,
        "time_grid_windows": windows,
        "institutions": len(identifiers),
        "ten_minute_members": len(ten_minute),
        "ten_minute_member_bytes": sum(ten_minute.values()),
        "ten_minute_headers": {key.decode("ascii"): count for key, count in headers.items()},
        "other_member_counts": other_counts,
    }
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(profile, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log(f"archive_structure_ok institutions={len(identifiers)} ten_minute_members={len(ten_minute)} "
        f"ten_minute_bytes={profile['ten_minute_member_bytes']} distinct_headers={len(headers)}")
    for key, count in headers.items():
        log(f"ten_minute_header count={count} header={key.decode('ascii')}")
    log(f"other_members={json.dumps(other_counts, sort_keys=True)}")


# ------------------------------------------------------------------- build --

def parse_id_list(text: str) -> list[int]:
    return sorted(int(part) for part in text.split(",") if part.strip())


def sample_name(institution: int) -> str:
    return f"institution_{institution:03d}.bin"


def cmd_build(args: argparse.Namespace) -> None:
    check_record(args.record)
    windows = load_time_grid(args.times, args.expected_windows)
    if args.archive.stat().st_size != args.archive_bytes:
        fail(f"{args.archive} has {args.archive.stat().st_size} bytes, expected {args.archive_bytes}")
    data_root: Path = args.data_root
    samples_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    expected_path = data_root / "filtered" / DATASET_ID / "expected_samples.tsv"
    if samples_root.exists():
        shutil.rmtree(samples_root)
    for path in (index_path, stats_path, expected_path):
        if path.exists():
            path.unlink()
    primary_dir = samples_root / PRIMARY_SERIES
    aux_dir = samples_root / AUX_SERIES
    primary_dir.mkdir(parents=True)
    aux_dir.mkdir(parents=True)

    expected_empty = parse_id_list(args.expected_empty)
    identifiers: list[int] | None = None
    per_institution: dict[int, dict] = {}
    empty_institutions: list[int] = []
    for archive, member in iter_archive(args.archive):
        if member.name == IDENTIFIERS_MEMBER:
            identifiers = parse_identifiers(archive.extractfile(member).read())
            continue
        match = TEN_MIN_RE.match(member.name)
        if not (match and member.isfile()):
            continue
        institution = int(match.group(1))
        if institution in per_institution or institution in empty_institutions:
            fail(f"duplicate archive member {member.name}")
        raw = archive.extractfile(member).read()
        times, values = parse_ten_minute_csv(raw, member.name, windows)
        if not values:
            # Header-only upstream member: no observations, so no sample.
            empty_institutions.append(institution)
            log(f"empty_source_member {member.name} (header only; no sample emitted)")
            continue
        if len(set(values)) < 2:
            fail(f"{member.name}: n_bytes series is constant")
        primary_bytes = struct.pack(f"<{len(values)}Q", *values)
        aux_bytes = struct.pack(f"<{len(times)}I", *times)
        (primary_dir / sample_name(institution)).write_bytes(primary_bytes)
        (aux_dir / sample_name(institution)).write_bytes(aux_bytes)
        per_institution[institution] = {
            "institution_id": institution,
            "source_member": member.name,
            "value_count": len(values),
            "first_id_time": times[0],
            "last_id_time": times[-1],
            "missing_windows": windows - len(values),
            "min": min(values),
            "max": max(values),
            "zero_values": sum(1 for value in values if value == 0),
            "values_ge_2_32": sum(1 for value in values if value > U32_MAX),
            "distinct_values": len(set(values)),
            "primary_sha256": hashlib.sha256(primary_bytes).hexdigest(),
            "aux_sha256": hashlib.sha256(aux_bytes).hexdigest(),
        }
        if len(per_institution) % 25 == 0:
            log(f"progress institutions={len(per_institution)} last={member.name}")

    if identifiers is None:
        fail(f"{IDENTIFIERS_MEMBER} missing from archive")
    if len(identifiers) != args.expected_institutions:
        fail(f"identifiers.csv lists {len(identifiers)} institutions, expected {args.expected_institutions}")
    if sorted(empty_institutions) != expected_empty:
        fail(f"header-only institutions {sorted(empty_institutions)} differ from pinned {expected_empty}")
    if set(per_institution) | set(empty_institutions) != set(identifiers):
        fail("emitted plus empty institutions disagree with identifiers.csv")

    rows: list[dict] = []
    for series, element, kind, width, digest_key in (
        (PRIMARY_SERIES, 8, "uint", 64, "primary_sha256"),
        (AUX_SERIES, 4, "uint", 32, "aux_sha256"),
    ):
        for institution in sorted(per_institution):
            info = per_institution[institution]
            row = {
                "dataset_id": DATASET_ID,
                "series_id": series,
                "role": "primary" if series == PRIMARY_SERIES else "auxiliary",
                "sample_path": f"samples/{DATASET_ID}/{series}/{sample_name(institution)}",
                "numeric_kind": kind,
                "bit_width": width,
                "endianness": "little",
                "element_size_bytes": element,
                "sample_size_bytes": info["value_count"] * element,
                "value_count": info["value_count"],
                "institution_id": institution,
                "source_member": info["source_member"],
                "first_id_time": info["first_id_time"],
                "last_id_time": info["last_id_time"],
                "sha256": info[digest_key],
            }
            if series == PRIMARY_SERIES:
                row["min"] = info["min"]
                row["max"] = info["max"]
            rows.append(row)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    infos = [per_institution[key] for key in sorted(per_institution)]
    total_values = sum(info["value_count"] for info in infos)
    ge32 = sum(info["values_ge_2_32"] for info in infos)
    maxima = sorted(info["max"] for info in infos)
    bit_buckets = {"le_16": 0, "17_24": 0, "25_32": 0, "33_40": 0, "gt_40": 0}
    for institution in sorted(per_institution):
        path = primary_dir / sample_name(institution)
        raw_values = path.read_bytes()
        for (value,) in struct.iter_unpack("<Q", raw_values):
            bits = value.bit_length()
            if bits <= 16:
                bit_buckets["le_16"] += 1
            elif bits <= 24:
                bit_buckets["17_24"] += 1
            elif bits <= 32:
                bit_buckets["25_32"] += 1
            elif bits <= 40:
                bit_buckets["33_40"] += 1
            else:
                bit_buckets["gt_40"] += 1
    stats = {
        "dataset_id": DATASET_ID,
        "institutions": len(infos),
        "identifiers": len(identifiers),
        "empty_source_institutions": sorted(empty_institutions),
        "value_bit_length_histogram": bit_buckets,
        "time_grid_windows": windows,
        "primary_values": total_values,
        "primary_bytes": total_values * 8,
        "aux_bytes": total_values * 4,
        "median_values_per_sample": statistics.median(info["value_count"] for info in infos),
        "min_values_per_sample": min(info["value_count"] for info in infos),
        "max_values_per_sample": max(info["value_count"] for info in infos),
        "total_missing_windows": sum(info["missing_windows"] for info in infos),
        "zero_values": sum(info["zero_values"] for info in infos),
        "values_ge_2_32": ge32,
        "fraction_ge_2_32": ge32 / total_values,
        "institutions_with_max_ge_2_32": sum(1 for value in maxima if value > U32_MAX),
        "global_min": min(info["min"] for info in infos),
        "global_max": maxima[-1],
        "per_institution_max_quantiles": {
            "p0": maxima[0],
            "p25": maxima[len(maxima) // 4],
            "p50": maxima[len(maxima) // 2],
            "p75": maxima[(3 * len(maxima)) // 4],
            "p100": maxima[-1],
        },
        "per_institution": infos,
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    columns = ["institution_id", "value_count", "first_id_time", "last_id_time", "min", "max",
               "values_ge_2_32", "distinct_values", "primary_sha256", "aux_sha256"]
    with expected_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for info in infos:
            handle.write("\t".join(str(info[column]) for column in columns) + "\n")
    log(f"value_bit_length_histogram={json.dumps(bit_buckets)}")
    log(f"build_ok institutions={len(infos)} empty_source_institutions={sorted(empty_institutions)} primary_values={total_values} primary_bytes={total_values * 8} "
        f"aux_bytes={total_values * 4} fraction_ge_2_32={ge32 / total_values:.6f} "
        f"institutions_max_ge_2_32={stats['institutions_with_max_ge_2_32']} global_max={maxima[-1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "build"):
        command = sub.add_parser(name)
        command.add_argument("--record", type=Path, required=True)
        command.add_argument("--times", type=Path, required=True)
        command.add_argument("--archive", type=Path, required=True)
        command.add_argument("--expected-institutions", type=int, default=283)
        command.add_argument("--expected-windows", type=int, default=40298)
        command.add_argument("--archive-bytes", type=int, default=PINNED_FILES["institutions.tar.gz"][0])
        if name == "preflight":
            command.add_argument("--profile", type=Path, required=True)
        else:
            command.add_argument("--data-root", type=Path, required=True)
            command.add_argument("--expected-empty", default="148,260,267,279,283",
                                 help="institutions whose upstream 10-minute CSV is header-only")
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            cmd_preflight(args)
        else:
            cmd_build(args)
    except BuildError as exc:
        print(f"FATAL: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
