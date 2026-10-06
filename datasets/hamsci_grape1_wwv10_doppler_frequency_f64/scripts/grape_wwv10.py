#!/usr/bin/env python3
"""Build Grape V1 WWV10 received-carrier-frequency float64 samples.

Reads only the pinned local `.csv.gz` station-day files. One sample per kept
file: the complete `Freq` column in file row order, parsed with float() to
IEEE-754 binary64 and written little-endian. Pure standard library.
"""
from __future__ import annotations

import argparse
import array
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

DATASET_ID = "hamsci_grape1_wwv10_doppler_frequency_f64"
SERIES_ID = "grape1_wwv10_received_frequency_hz_f64"
NATURAL_RECORD_KIND = "grape_v1_station_day_wwv10_frequency_file"
MIN_ROWS = 3600  # one hour of nominal 1 Hz rows; shorter files are fragments
NOMINAL_HZ = 10_000_000.0
BAND_HZ = 100.0  # |Freq - 10 MHz| above this: re-tuned receiver / other carrier
WIDE_HZ = 10.0  # reported only
NEAR_HZ = 5.0  # reported only
EXPECTED_NODES = ("N0000007", "N0000014", "N0000015", "N0000029", "N00009", "N00010")
COLUMN_HEADER = "UTC,Freq,Vpk"
REASONS = (
    "header_mismatch",
    "reference_not_gpsdo",
    "malformed_row",
    "time_order",
    "out_of_band",
    "too_short",
    "constant",
)
HEADER_KV_RE = re.compile(r"#\s(\S.*?)\s{2,}(\S.*)")
ROW_RE = re.compile(r"(\d{4}-\d\d-\d\d)T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)Z, *(\d+\.\d{3}), *([^,\s]+)")
SOURCE_FIELDS = [
    "sample_order",
    "key",
    "node",
    "receiver",
    "grid",
    "beacon",
    "file_start_utc",
    "size_bytes",
    "md5",
    "url",
    "expected_status",
]
CLASSIFICATION_FIELDS = [
    "sample_order",
    "key",
    "node",
    "status",
    "rows",
    "malformed_rows",
    "truncated_tail_dropped",
    "time_order_violations",
    "out_of_band_values",
    "distinct_values",
    "frequency_standard",
    "first_row_utc",
    "last_row_utc",
    "missing_seconds",
    "steps_0s",
    "max_step_seconds",
    "values_beyond_10hz",
    "min",
    "max",
    "example_problem",
]


def seconds_of(text: str) -> int:
    return int(text[11:13]) * 3600 + int(text[14:16]) * 60 + int(text[17:19])


def parse_station_day(text: str, key: str, node: str, grid: str, file_start_utc: str) -> tuple[dict, list[float]]:
    """Classify one decoded station-day CSV and return (meta, Freq values)."""
    lines = text.split("\n")
    meta: dict = {
        "rows": 0,
        "malformed_rows": 0,
        "truncated_tail_dropped": 0,
        "time_order_violations": 0,
        "out_of_band_values": 0,
        "values_beyond_5hz": 0,
        "values_beyond_10hz": 0,
        "distinct_values": 0,
        "frequency_standard": "",
        "first_row_utc": "",
        "last_row_utc": "",
        "span_seconds": 0,
        "missing_seconds": 0,
        "steps_0s": 0,
        "steps_1s": 0,
        "steps_2s": 0,
        "steps_gt2s": 0,
        "max_step_seconds": 0,
        "min": None,
        "max": None,
        "example_problem": "",
    }
    reasons: list[str] = []
    values: list[float] = []

    first = lines[0].rstrip("\r").split(",")
    identity_ok = (
        len(first) >= 6
        and first[0] == "#"
        and first[1] == file_start_utc
        and first[2] == node
        and first[3] == grid
        and first[-2] == "G1"
        and first[-1] == "WWV10"
    )
    header: dict[str, str] = {}
    index = 1
    while index < len(lines) and lines[index].startswith("#"):
        match = HEADER_KV_RE.fullmatch(lines[index].rstrip("\r").rstrip())
        if match:
            header[match.group(1)] = match.group(2).strip()
        index += 1
    column_ok = index < len(lines) and lines[index].rstrip("\r") == COLUMN_HEADER
    block_ok = (
        header.get("Station Node Number") == node
        and header.get("Grid Square") == grid
        and header.get("Radio1ID") == "G1"
        and header.get("Beacon Now Decoded") == "WWV10"
    )
    meta["frequency_standard"] = header.get("Frequency Standard", "")
    if not (identity_ok and block_ok and column_ok):
        meta["example_problem"] = "identity/header/column-header mismatch"
        meta["status"] = "exclude:header_mismatch"
        return meta, values
    if "GPSDO" not in meta["frequency_standard"].upper():
        reasons.append("reference_not_gpsdo")

    body = lines[index + 1 :]
    tail = body.pop() if body else ""
    if tail:
        # Final line without a newline: keep only if it is a complete row.
        if ROW_RE.fullmatch(tail.rstrip("\r")):
            body.append(tail)
        else:
            meta["truncated_tail_dropped"] = 1
    date = key[:10]
    previous = -1
    steps: Counter = Counter()
    append = values.append
    for line in body:
        match = ROW_RE.fullmatch(line[:-1] if line.endswith("\r") else line)
        if match is None:
            meta["malformed_rows"] += 1
            if not meta["example_problem"]:
                meta["example_problem"] = f"malformed row {line[:60]!r}"
            continue
        row_date, hh, mm, ss, freq_token, _vpk = match.groups()
        seconds = int(hh) * 3600 + int(mm) * 60 + int(ss)
        # Repeated seconds (logger jitter) are allowed and counted as 0 s
        # steps; a backward step (clock reset after a reboot) or a row on
        # another UTC date is a time_order violation.
        if row_date != date or seconds < previous:
            meta["time_order_violations"] += 1
            if not meta["example_problem"]:
                meta["example_problem"] = f"time order at {line[:20]!r}"
        elif previous >= 0:
            steps[seconds - previous] += 1
        if seconds > previous:
            previous = seconds
        value = float(freq_token)
        deviation = abs(value - NOMINAL_HZ)
        if deviation > BAND_HZ:
            meta["out_of_band_values"] += 1
        if deviation > WIDE_HZ:
            meta["values_beyond_10hz"] += 1
        if deviation > NEAR_HZ:
            meta["values_beyond_5hz"] += 1
        append(value)

    meta["rows"] = len(values)
    if values:
        first_match = ROW_RE.fullmatch(body[0].rstrip("\r")) if body else None
        last_line = next((line for line in reversed(body) if ROW_RE.fullmatch(line.rstrip("\r"))), "")
        if first_match:
            meta["first_row_utc"] = body[0][:20]
        meta["last_row_utc"] = last_line[:20]
        meta["min"] = min(values)
        meta["max"] = max(values)
        meta["distinct_values"] = len(set(values))
        if meta["first_row_utc"] and meta["last_row_utc"]:
            span = seconds_of(meta["last_row_utc"]) - seconds_of(meta["first_row_utc"]) + 1
            meta["span_seconds"] = span
            meta["missing_seconds"] = span - (len(values) - steps.get(0, 0))
    meta["steps_0s"] = steps.get(0, 0)
    meta["steps_1s"] = steps.get(1, 0)
    meta["steps_2s"] = steps.get(2, 0)
    meta["steps_gt2s"] = sum(count for step, count in steps.items() if step > 2)
    meta["max_step_seconds"] = max(steps) if steps else 0

    if meta["malformed_rows"]:
        reasons.append("malformed_row")
    if meta["time_order_violations"]:
        reasons.append("time_order")
    if meta["out_of_band_values"]:
        reasons.append("out_of_band")
    if len(values) < MIN_ROWS:
        reasons.append("too_short")
    if meta["distinct_values"] < 2:
        reasons.append("constant")
    meta["status"] = "keep" if not reasons else "exclude:" + "+".join(r for r in REASONS if r in reasons)
    return meta, values


def sample_relpath(row: dict) -> str:
    stem = row["key"][: -len(".csv.gz")]
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['node']}/{stem}.f64"


def process(job: tuple[dict, str, str]) -> dict:
    row, download_dir, data_root = job
    path = Path(download_dir) / row["key"]
    raw = path.read_bytes()
    if len(raw) != int(row["size_bytes"]):
        raise RuntimeError(f"{row['key']}: size {len(raw)} != pinned {row['size_bytes']}")
    if hashlib.md5(raw).hexdigest() != row["md5"]:
        raise RuntimeError(f"{row['key']}: md5 mismatch")
    text = gzip.decompress(raw).decode("ascii")
    meta, values = parse_station_day(text, row["key"], row["node"], row["grid"], row["file_start_utc"])
    meta.update({key: row[key] for key in ("sample_order", "key", "node", "grid", "file_start_utc", "md5", "url")})
    if meta["status"] == "keep":
        payload = array.array("d", values)
        if sys.byteorder != "little":
            payload.byteswap()
        blob = payload.tobytes()
        relpath = sample_relpath(row)
        target = Path(data_root) / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        temporary.write_bytes(blob)
        os.replace(temporary, target)
        meta["sample_path"] = relpath
        meta["sample_size_bytes"] = len(blob)
        meta["sha256"] = hashlib.sha256(blob).hexdigest()
    return meta


def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != SOURCE_FIELDS:
            raise SystemExit(f"unexpected sources.tsv columns {reader.fieldnames}")
        rows = list(reader)
    for order, row in enumerate(rows):
        if int(row["sample_order"]) != order:
            raise SystemExit(f"sources.tsv sample_order gap at {row['key']}")
    return rows


def build(args: argparse.Namespace) -> None:
    sources = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    jobs = [(row, args.download_dir, str(data_root)) for row in sources]
    with Pool(processes=max(1, min(args.workers, os.cpu_count() or 1))) as pool:
        metas = list(pool.imap(process, jobs, chunksize=4))

    pinned_mismatch = [
        (row["key"], row["expected_status"], meta["status"])
        for row, meta in zip(sources, metas)
        if row["expected_status"] != "unpinned" and row["expected_status"] != meta["status"]
    ]
    unpinned = sum(1 for row in sources if row["expected_status"] == "unpinned")

    filtered_dir = Path(args.filtered_dir)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    with (filtered_dir / "file_classification.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CLASSIFICATION_FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for meta in metas:
            writer.writerow({key: ("" if meta.get(key) is None else meta.get(key)) for key in CLASSIFICATION_FIELDS})

    kept = [meta for meta in metas if meta["status"] == "keep"]
    index_path = Path(args.index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for meta in kept:
            row = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": meta["sample_path"],
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": meta["sample_size_bytes"],
                "value_count": meta["rows"],
                "role": "primary",
                "natural_record_kind": NATURAL_RECORD_KIND,
                "sample_order": int(meta["sample_order"]),
                "source_file": meta["key"],
                "source_md5": meta["md5"],
                "source_url": meta["url"],
                "node": meta["node"],
                "grid": meta["grid"],
                "receiver": "G1",
                "beacon": "WWV10",
                "utc_date": meta["key"][:10],
                "file_start_utc": meta["file_start_utc"],
                "first_row_utc": meta["first_row_utc"],
                "last_row_utc": meta["last_row_utc"],
                "span_seconds": meta["span_seconds"],
                "missing_seconds": meta["missing_seconds"],
                "steps_0s": meta["steps_0s"],
                "steps_1s": meta["steps_1s"],
                "steps_2s": meta["steps_2s"],
                "steps_gt2s": meta["steps_gt2s"],
                "max_step_seconds": meta["max_step_seconds"],
                "truncated_tail_dropped": meta["truncated_tail_dropped"],
                "frequency_standard": meta["frequency_standard"],
                "values_beyond_5hz": meta["values_beyond_5hz"],
                "values_beyond_10hz": meta["values_beyond_10hz"],
                "distinct_values": meta["distinct_values"],
                "min": meta["min"],
                "max": meta["max"],
                "sha256": meta["sha256"],
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    counts = sorted(meta["rows"] for meta in kept)
    middle = len(counts) // 2
    median = (counts[middle] if len(counts) % 2 else (counts[middle - 1] + counts[middle]) / 2) if counts else 0
    status_counts = Counter(meta["status"] for meta in metas)
    per_node = {
        node: {
            "pinned_files": sum(1 for meta in metas if meta["node"] == node),
            "kept_files": sum(1 for meta in kept if meta["node"] == node),
            "kept_values": sum(meta["rows"] for meta in kept if meta["node"] == node),
        }
        for node in EXPECTED_NODES
    }
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "pinned_files": len(metas),
        "kept_files": len(kept),
        "excluded_files": len(metas) - len(kept),
        "status_counts": dict(sorted(status_counts.items())),
        "unpinned_statuses": unpinned,
        "per_node": per_node,
        "kept_values": sum(counts),
        "kept_bytes": sum(meta["sample_size_bytes"] for meta in kept),
        "median_sample_values": median,
        "min_sample_values": counts[0] if counts else 0,
        "max_sample_values": counts[-1] if counts else 0,
        "global_min_hz": min((meta["min"] for meta in kept), default=None),
        "global_max_hz": max((meta["max"] for meta in kept), default=None),
        "kept_missing_seconds": sum(meta["missing_seconds"] for meta in kept),
        "kept_steps_0s": sum(meta["steps_0s"] for meta in kept),
        "kept_steps_1s": sum(meta["steps_1s"] for meta in kept),
        "kept_steps_2s": sum(meta["steps_2s"] for meta in kept),
        "kept_steps_gt2s": sum(meta["steps_gt2s"] for meta in kept),
        "kept_truncated_tails_dropped": sum(meta["truncated_tail_dropped"] for meta in kept),
        "kept_values_beyond_5hz": sum(meta["values_beyond_5hz"] for meta in kept),
        "kept_values_beyond_10hz": sum(meta["values_beyond_10hz"] for meta in kept),
        "frequency_standards": dict(Counter(meta["frequency_standard"] for meta in metas)),
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: stats[key] for key in ("pinned_files", "kept_files", "status_counts", "kept_values", "kept_bytes", "median_sample_values", "global_min_hz", "global_max_hz")}, sort_keys=True))
    for node, entry in per_node.items():
        print(f"node={node} pinned={entry['pinned_files']} kept={entry['kept_files']} values={entry['kept_values']}")

    if pinned_mismatch:
        for key, expected, realized in pinned_mismatch[:20]:
            print(f"status drift {key}: pinned={expected} realized={realized}", file=sys.stderr)
        raise SystemExit(f"{len(pinned_mismatch)} file statuses differ from sources.tsv expected_status")
    missing_nodes = [node for node, entry in per_node.items() if entry["kept_files"] == 0]
    if missing_nodes:
        raise SystemExit(f"no kept station-days for nodes {missing_nodes}")
    if not kept or median < 1000:
        raise SystemExit(f"degenerate output: kept={len(kept)} median={median}")
    if stats["kept_bytes"] > 1_000_000_000:
        raise SystemExit(f"primary bytes {stats['kept_bytes']} exceed the 1 GB cap")
    if unpinned:
        print(f"WARNING: {unpinned} sources have expected_status=unpinned; pin realized statuses in sources.tsv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--filtered-dir", required=True)
    parser.add_argument("--workers", type=int, default=16)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
