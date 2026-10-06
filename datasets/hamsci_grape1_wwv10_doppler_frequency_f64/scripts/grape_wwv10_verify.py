#!/usr/bin/env python3
"""Independently verify the Grape V1 WWV10 float64 samples.

Re-decodes every pinned source with a separate code path (zlib member loop,
byte-level field splitting, datetime timestamps, integer milli-hertz tokens),
re-derives every keep/exclude status, and checks that each stored double
formats back to its exact source token. Pure standard library.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import os
import re
import struct
import sys
import tomllib
import zlib
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

DATASET_ID = "hamsci_grape1_wwv10_doppler_frequency_f64"
SERIES_ID = "grape1_wwv10_received_frequency_hz_f64"
MIN_ROWS = 3600
NOMINAL_MHZ = 10_000_000_000  # 10 MHz in milli-hertz
BAND_MHZ = 100_000  # 100 Hz in milli-hertz
EXPECTED_NODES = {"N0000007", "N0000014", "N0000015", "N0000029", "N00009", "N00010"}
REASON_ORDER = (
    "header_mismatch",
    "reference_not_gpsdo",
    "malformed_row",
    "time_order",
    "out_of_band",
    "too_short",
    "constant",
)
TS_RE = re.compile(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
FREQ_RE = re.compile(rb"\d+\.\d{3}")
VPK_RE = re.compile(rb"[^,\s]+")
GAP_FIELDS = (
    "first_row_utc",
    "last_row_utc",
    "span_seconds",
    "missing_seconds",
    "steps_0s",
    "steps_1s",
    "steps_2s",
    "steps_gt2s",
    "max_step_seconds",
    "values_beyond_5hz",
    "values_beyond_10hz",
)
INDEX_KEYS = (
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
)


def gunzip_members(raw: bytes) -> bytes:
    out = []
    data = raw
    while data:
        decoder = zlib.decompressobj(wbits=31)
        out.append(decoder.decompress(data))
        out.append(decoder.flush())
        if not decoder.eof:
            raise ValueError("truncated gzip member")
        data = decoder.unused_data
    return b"".join(out)


def epoch(ts: bytes) -> int:
    return int(datetime.fromisoformat(ts.decode("ascii")).replace(tzinfo=timezone.utc).timestamp())


def header_value(header: bytes, label: bytes) -> bytes | None:
    match = re.search(rb"^# " + re.escape(label) + rb" {2,}(.*?) *$", header, flags=re.MULTILINE)
    return match.group(1) if match else None


def rederive(data: bytes, source: dict) -> tuple[str, list[bytes], dict]:
    """Return (status, freq tokens, facts) for one decoded station-day file."""
    key = source["key"]
    node = source["node"].encode()
    grid = source["grid"].encode()
    start_text = source["file_start_utc"].encode()
    facts = {"truncated_tail": 0}
    split = data.split(b"\n")
    lines = [line[:-1] if line.endswith(b"\r") else line for line in split]
    first = lines[0].split(b",")
    position = 1
    while position < len(lines) and lines[position][:1] == b"#":
        position += 1
    header = b"\n".join(lines[:position])
    identity = (
        len(first) >= 6
        and first[0] == b"#"
        and first[1] == start_text
        and first[2] == node
        and first[3] == grid
        and first[-2:] == [b"G1", b"WWV10"]
    )
    block = (
        header_value(header, b"Station Node Number") == node
        and header_value(header, b"Grid Square") == grid
        and header_value(header, b"Radio1ID") == b"G1"
        and header_value(header, b"Beacon Now Decoded") == b"WWV10"
    )
    column = position < len(lines) and lines[position] == b"UTC,Freq,Vpk"
    if not (identity and block and column):
        return "exclude:header_mismatch", [], facts
    reasons = set()
    standard = header_value(header, b"Frequency Standard") or b""
    if b"GPSDO" not in standard.upper():
        reasons.add("reference_not_gpsdo")

    rows = lines[position + 1 :]
    final_raw = split[-1]
    if final_raw == b"":
        rows = rows[:-1]
    tokens: list[bytes] = []
    milli: set[int] = set()
    date = key[:10].encode()
    day_start = epoch(date + b"T00:00:00Z")
    day_end = day_start + 86400
    previous = None
    deltas: dict[int, int] = {}
    first_ts = last_ts = b""
    beyond5 = beyond10 = 0
    for number, line in enumerate(rows):
        fields = line.split(b",")
        good = len(fields) == 3 and TS_RE.fullmatch(fields[0]) is not None
        freq = fields[1].lstrip(b" ") if good else b""
        vpk = fields[2].lstrip(b" ") if good else b""
        good = good and FREQ_RE.fullmatch(freq) is not None and VPK_RE.fullmatch(vpk) is not None
        if good:
            try:
                moment = epoch(fields[0])
            except ValueError:
                good = False
        if not good:
            if number == len(rows) - 1 and final_raw != b"":
                facts["truncated_tail"] = 1  # incomplete final line without newline
                continue
            reasons.add("malformed_row")
            continue
        if fields[0][:10] != date or not day_start <= moment < day_end:
            reasons.add("time_order")
        elif previous is not None and moment < previous:
            reasons.add("time_order")  # backward clock step
        elif previous is not None:
            deltas[moment - previous] = deltas.get(moment - previous, 0) + 1
        previous = moment if previous is None else max(previous, moment)
        if not first_ts:
            first_ts = fields[0]
        last_ts = fields[0]
        value = int(freq.replace(b".", b""))
        offset = abs(value - NOMINAL_MHZ)
        if offset > BAND_MHZ:
            reasons.add("out_of_band")
        beyond5 += offset > 5_000
        beyond10 += offset > 10_000
        milli.add(value)
        tokens.append(freq)
    if len(tokens) < MIN_ROWS:
        reasons.add("too_short")
    if len(milli) < 2:
        reasons.add("constant")
    facts["distinct"] = len(milli)
    if tokens:
        span = epoch(last_ts) - epoch(first_ts) + 1
        facts.update(
            {
                "first_row_utc": first_ts.decode(),
                "last_row_utc": last_ts.decode(),
                "span_seconds": span,
                "missing_seconds": span - (len(tokens) - deltas.get(0, 0)),
                "steps_0s": deltas.get(0, 0),
                "steps_1s": deltas.get(1, 0),
                "steps_2s": deltas.get(2, 0),
                "steps_gt2s": sum(n for step, n in deltas.items() if step > 2),
                "max_step_seconds": max(deltas) if deltas else 0,
                "values_beyond_5hz": beyond5,
                "values_beyond_10hz": beyond10,
            }
        )
    status = "keep" if not reasons else "exclude:" + "+".join(r for r in REASON_ORDER if r in reasons)
    return status, tokens, facts


def check_one(job: tuple[dict, dict | None, str, str]) -> dict:
    source, index_row, download_dir, data_root = job
    raw = (Path(download_dir) / source["key"]).read_bytes()
    if len(raw) != int(source["size_bytes"]) or hashlib.md5(raw).hexdigest() != source["md5"]:
        raise RuntimeError(f"{source['key']}: source size/md5 mismatch")
    status, tokens, facts = rederive(gunzip_members(raw), source)
    result = {"key": source["key"], "status": status, "node": source["node"], "values": 0, "bytes": 0}
    if status != "keep":
        if index_row is not None:
            raise RuntimeError(f"{source['key']}: excluded ({status}) but indexed")
        return result
    if index_row is None:
        raise RuntimeError(f"{source['key']}: kept but missing from index")
    sample = Path(data_root) / index_row["sample_path"]
    blob = sample.read_bytes()
    if len(blob) != 8 * len(tokens):
        raise RuntimeError(f"{source['key']}: sample has {len(blob) // 8} values, source has {len(tokens)}")
    if hashlib.sha256(blob).hexdigest() != index_row["sha256"]:
        raise RuntimeError(f"{source['key']}: sample sha256 differs from index")
    stored = array.array("d")
    stored.frombytes(blob)
    if sys.byteorder != "little":
        stored.byteswap()
    mismatches = 0
    for value, token in zip(stored, tokens):
        if not math.isfinite(value) or b"%.3f" % value != token:
            mismatches += 1
    if mismatches:
        raise RuntimeError(f"{source['key']}: {mismatches} stored doubles do not format back to source tokens")
    low, high = min(stored), max(stored)
    if low == high:
        raise RuntimeError(f"{source['key']}: constant sample")
    if index_row["min"] != low or index_row["max"] != high:
        raise RuntimeError(f"{source['key']}: index min/max {index_row['min']}/{index_row['max']} != stored {low}/{high}")
    if int(index_row["value_count"]) != len(tokens) or int(index_row["sample_size_bytes"]) != len(blob):
        raise RuntimeError(f"{source['key']}: index value_count/sample_size_bytes mismatch")
    if int(index_row["distinct_values"]) != facts["distinct"]:
        raise RuntimeError(f"{source['key']}: index distinct_values mismatch")
    if int(index_row["truncated_tail_dropped"]) != facts["truncated_tail"]:
        raise RuntimeError(f"{source['key']}: truncated-tail bookkeeping mismatch")
    for field in GAP_FIELDS:
        if index_row.get(field) != facts[field]:
            raise RuntimeError(f"{source['key']}: index {field}={index_row.get(field)!r} != re-derived {facts[field]!r}")
    beyond_f32 = sum(1 for value in stored if struct.unpack("<f", struct.pack("<f", value))[0] != value)
    result.update({"values": len(tokens), "bytes": len(blob), "beyond_f32": beyond_f32})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--classification", required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--allow-unpinned", action="store_true")
    args = parser.parse_args()

    with Path(args.sources).open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    if len(sources) != 920 or len({row["key"] for row in sources}) != 920:
        raise SystemExit(f"expected 920 unique pinned sources, found {len(sources)}")
    with Path(args.classification).open(encoding="utf-8", newline="") as handle:
        built_status = {row["key"]: row["status"] for row in csv.DictReader(handle, delimiter="\t")}

    index_rows: dict[str, dict] = {}
    seen_paths: set[str] = set()
    for number, line in enumerate(Path(args.index).read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        missing = [key for key in INDEX_KEYS if key not in row]
        if missing:
            raise SystemExit(f"index line {number}: missing {missing}")
        if (
            row["dataset_id"] != DATASET_ID
            or row["series_id"] != SERIES_ID
            or row["numeric_kind"] != "float"
            or int(row["bit_width"]) != 64
            or row["endianness"] != "little"
            or int(row["element_size_bytes"]) != 8
            or row.get("role") != "primary"
        ):
            raise SystemExit(f"index line {number}: wrong identity/type fields")
        if row["sample_path"] in seen_paths or row["source_file"] in index_rows:
            raise SystemExit(f"index line {number}: duplicate sample or source")
        seen_paths.add(row["sample_path"])
        index_rows[row["source_file"]] = row
    unknown = set(index_rows) - {row["key"] for row in sources}
    if unknown:
        raise SystemExit(f"index references unpinned sources: {sorted(unknown)[:3]}")

    jobs = [(row, index_rows.get(row["key"]), args.download_dir, args.data_root) for row in sources]
    with Pool(processes=max(1, min(args.workers, os.cpu_count() or 1))) as pool:
        results = list(pool.imap(check_one, jobs, chunksize=4))

    unpinned = 0
    for source, result in zip(sources, results):
        if built_status.get(source["key"]) != result["status"]:
            raise SystemExit(
                f"{source['key']}: build status {built_status.get(source['key'])!r} != re-derived {result['status']!r}"
            )
        if source["expected_status"] == "unpinned":
            unpinned += 1
        elif source["expected_status"] != result["status"]:
            raise SystemExit(f"{source['key']}: pinned {source['expected_status']!r} != re-derived {result['status']!r}")
    if unpinned and not args.allow_unpinned:
        raise SystemExit(f"{unpinned} sources still have expected_status=unpinned")

    series_dir = Path(args.data_root) / "samples" / DATASET_ID / SERIES_ID
    on_disk = {str(path.relative_to(args.data_root)) for path in series_dir.rglob("*") if path.is_file()}
    if on_disk != seen_paths:
        raise SystemExit(f"sample directory mismatch: stray={len(on_disk - seen_paths)} missing={len(seen_paths - on_disk)}")

    kept = [result for result in results if result["status"] == "keep"]
    counts = sorted(result["values"] for result in kept)
    total_values = sum(counts)
    total_bytes = sum(result["bytes"] for result in kept)
    middle = len(counts) // 2
    median = (counts[middle] if len(counts) % 2 else (counts[middle - 1] + counts[middle]) / 2) if counts else 0
    nodes = {result["node"] for result in kept}
    if nodes != EXPECTED_NODES:
        raise SystemExit(f"kept nodes {sorted(nodes)} != expected {sorted(EXPECTED_NODES)}")
    if median < 1000 or total_values < 10_000:
        raise SystemExit(f"below floor: values={total_values} median={median}")
    if total_bytes > 1_000_000_000:
        raise SystemExit(f"primary bytes {total_bytes} exceed cap")
    beyond_f32 = sum(result["beyond_f32"] for result in kept)
    if beyond_f32 < 0.99 * total_values:
        raise SystemExit(f"only {beyond_f32}/{total_values} values need float64; check width honesty")

    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        raise SystemExit("manifest dataset_id mismatch")
    series = [entry for entry in manifest.get("series", []) if entry.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest.get("series", [])) != 1:
        raise SystemExit("manifest must declare exactly the one primary series")
    entry = series[0]
    if int(entry["sample_count"]) != len(kept) or int(entry["total_size_bytes"]) != total_bytes:
        raise SystemExit(
            f"manifest sample_count/total_size_bytes {entry['sample_count']}/{entry['total_size_bytes']} "
            f"!= realized {len(kept)}/{total_bytes}"
        )
    print(
        json.dumps(
            {
                "verify": "ok",
                "pinned_sources": len(sources),
                "kept_samples": len(kept),
                "excluded": len(sources) - len(kept),
                "values": total_values,
                "bytes": total_bytes,
                "median_values": median,
                "values_not_float32_exact": beyond_f32,
                "nodes": sorted(nodes),
                "unpinned_statuses": unpinned,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
