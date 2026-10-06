#!/usr/bin/env python3
"""Independent verification of the GBM TTE TIME samples.

Shares no code with gbm_tte.py: it has its own FITS card parser and HDU
walker, derives the TIME byte offset from the TFORM list, re-checks the
EVENTS DATASUM with its own word sum, and re-decodes every row with
struct.iter_unpack('>dh'), packing TIME as '<d' and comparing byte-for-byte
against the emitted sample. It then checks time ordering and span,
recomputes every index statistic, the sample inventory, the manifest totals,
and the degenerate-output rules.

Missing-value policy (same as build): none. TIME has no TNULL; every stored
double is emitted unchanged, in stored row order (TZERO1 is not applied).
Non-finite values or PHA codes outside 0..127 are fatal; decreasing steps are
tolerated only up to MAX_BACKSTEPS per file of at most MAX_BACKSTEP_S each
(the rare early-mission interleaved runs) and are recorded; nothing is
masked, clipped, imputed, sorted, or dropped.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import struct
import tomllib
from pathlib import Path

DATASET_ID = "fermi_gbm_tte_nai_photon_arrival_times_f64"
SERIES_ID = "gbm_nai_tte_photon_time_f64"
BLOCK = 2880
CARD = re.compile(r"^([A-Z0-9_-]{1,8})\s*= ?(.*)$")
STRING = re.compile(r"^\s*'((?:[^']|'')*)'")
TFORM = re.compile(r"^\s*(\d*)([A-Z])\s*$")
WIDTH = {"L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}
ROW_FLOOR = 100_000
MIN_CHANGES = 10_000
MAX_BACKSTEPS = 4      # same source-order tolerance as build: rare ~0.1 s
MAX_BACKSTEP_S = 1.0   # backward steps are kept as stored, never sorted
FIRST_RANGE = (-400.0, 0.0)
LAST_RANGE = (0.0, 2000.0)
LE_DOUBLE = struct.Struct("<d")
DET_CODES = "0123456789ab"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def header_cards(data: bytes, offset: int) -> tuple[dict[str, str], int]:
    cards: dict[str, str] = {}
    while True:
        block = data[offset:offset + BLOCK]
        if len(block) != BLOCK:
            fail("truncated FITS header")
        offset += BLOCK
        for i in range(36):
            text = block[80 * i:80 * i + 80].decode("ascii")
            if text.rstrip() == "END":
                return cards, offset
            match = CARD.match(text)
            if match and text[8] == "=":
                cards[match.group(1)] = match.group(2)


def value(cards: dict[str, str], key: str) -> str | None:
    raw = cards.get(key)
    if raw is None:
        return None
    match = STRING.match(raw)
    if match:
        return match.group(1).replace("''", "'").rstrip()
    return raw.split("/")[0].strip()


def int_value(cards: dict[str, str], key: str, default: int | None = None) -> int:
    raw = value(cards, key)
    if raw is None:
        if default is None:
            fail(f"missing keyword {key}")
        return default
    return int(raw)


def float_value(cards: dict[str, str], key: str) -> float:
    raw = value(cards, key)
    if raw is None:
        fail(f"missing keyword {key}")
    return float(raw.replace("D", "E"))


def data_bytes(cards: dict[str, str]) -> int:
    naxis = int_value(cards, "NAXIS")
    if naxis == 0:
        return 0
    n = 1
    for i in range(1, naxis + 1):
        n *= int_value(cards, f"NAXIS{i}")
    return abs(int_value(cards, "BITPIX")) // 8 * int_value(cards, "GCOUNT", 1) * (n + int_value(cards, "PCOUNT", 0))


def word_sum(unit: bytes) -> int:
    total = 0
    for (word,) in struct.iter_unpack(">I", unit):
        total += word
    while total > 0xFFFFFFFF:
        total = (total >> 32) + (total & 0xFFFFFFFF)
    return total


def find_events(data: bytes, filename: str, detector: str) -> dict[str, object]:
    primary, offset = header_cards(data, 0)
    identity = (value(primary, "TELESCOP"), value(primary, "INSTRUME"), value(primary, "DATATYPE"),
                value(primary, "DETNAM"), value(primary, "FILENAME"))
    expected = ("GLAST", "GBM", "TTE", f"NAI_{DET_CODES.index(detector[1]):02d}", filename)
    if identity != expected:
        fail(f"{filename}: primary identity {identity} != {expected}")
    trigtime = float_value(primary, "TRIGTIME")
    offset += -(-data_bytes(primary) // BLOCK) * BLOCK
    hdus = ["PRIMARY"]
    found = None
    while offset < len(data):
        cards, start = header_cards(data, offset)
        name = value(cards, "EXTNAME")
        hdus.append(name)
        size = data_bytes(cards)
        if name == "EVENTS":
            if found is not None:
                fail(f"{filename}: duplicate EVENTS")
            fields = int_value(cards, "TFIELDS")
            columns = {}
            position = 0
            for i in range(1, fields + 1):
                match = TFORM.match(value(cards, f"TFORM{i}") or "")
                if not match:
                    fail(f"{filename}: bad TFORM{i}")
                columns[value(cards, f"TTYPE{i}")] = (position, match.group(1) or "1", match.group(2))
                position += int(match.group(1) or 1) * WIDTH[match.group(2)]
            row_bytes = int_value(cards, "NAXIS1")
            if columns != {"TIME": (0, "1", "D"), "PHA": (8, "1", "I")} or position != row_bytes or row_bytes != 10:
                fail(f"{filename}: EVENTS layout changed: {columns} row={row_bytes}")
            if value(cards, "TUNIT1") != "s" or float_value(cards, "TZERO1") != trigtime:
                fail(f"{filename}: TIME unit/TZERO1 mismatch")
            if any(key in cards for key in ("TSCAL1", "TNULL1")):
                fail(f"{filename}: TIME has scaling/null keywords")
            unit = data[start:start + -(-size // BLOCK) * BLOCK]
            if len(unit) != -(-size // BLOCK) * BLOCK:
                fail(f"{filename}: truncated EVENTS")
            if value(cards, "DATASUM") is None or int(value(cards, "DATASUM")) != word_sum(unit):
                fail(f"{filename}: EVENTS DATASUM does not match")
            if unit[size:].count(0) != len(unit) - size:
                fail(f"{filename}: EVENTS padding not zero")
            found = {
                "rows": int_value(cards, "NAXIS2"),
                "table": data[start:start + size],
                "tzero1": float_value(cards, "TZERO1"),
                "tstart_rel": float_value(cards, "TSTART") - trigtime,
                "tstop_rel": float_value(cards, "TSTOP") - trigtime,
                "object": value(primary, "OBJECT"),
            }
        offset = start + -(-size // BLOCK) * BLOCK
    if hdus != ["PRIMARY", "EBOUNDS", "EVENTS", "GTI"] or offset != len(data):
        fail(f"{filename}: HDU layout {hdus} end={offset} size={len(data)}")
    if found is None:
        fail(f"{filename}: no EVENTS")
    return found


def sha256_bytes_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sample(source: Path, filename: str, detector: str, sample: Path) -> dict[str, object]:
    data = source.read_bytes()
    events = find_events(data, filename, detector)
    rows = int(events["rows"])
    emitted = sample.read_bytes()
    if len(emitted) != rows * 8:
        fail(f"{sample.name}: size {len(emitted)} != rows*8 ({rows})")
    expected = bytearray()
    previous = None
    equal = 0
    backsteps = 0
    max_backstep = 0.0
    min_step = math.inf
    low = math.inf
    high = -math.inf
    for time_value, pha in struct.iter_unpack(">dh", events["table"]):
        if not math.isfinite(time_value):
            fail(f"{filename}: non-finite TIME")
        if not 0 <= pha <= 127:
            fail(f"{filename}: PHA {pha} out of range")
        if previous is not None:
            if time_value < previous:
                backsteps += 1
                max_backstep = max(max_backstep, previous - time_value)
            elif time_value == previous:
                equal += 1
            elif time_value - previous < min_step:
                min_step = time_value - previous
        previous = time_value
        low = min(low, time_value)
        high = max(high, time_value)
        expected += LE_DOUBLE.pack(time_value)
    if bytes(expected) != emitted:
        fail(f"{sample.name}: bytes differ from source EVENTS.TIME")
    first = LE_DOUBLE.unpack_from(emitted, 0)[0]
    last = LE_DOUBLE.unpack_from(emitted, len(emitted) - 8)[0]
    if rows < ROW_FLOOR:
        fail(f"{sample.name}: {rows} events below floor")
    if backsteps > MAX_BACKSTEPS or max_backstep > MAX_BACKSTEP_S:
        fail(f"{filename}: {backsteps} decreasing TIME steps (largest {max_backstep} s) beyond tolerance")
    if not (FIRST_RANGE[0] <= low <= first < FIRST_RANGE[1] and LAST_RANGE[0] < last <= high <= LAST_RANGE[1]):
        fail(f"{sample.name}: implausible span {first}..{last} (min {low}, max {high})")
    if rows - equal < MIN_CHANGES or first >= last:
        fail(f"{sample.name}: degenerate TIME column")
    return {
        "rows": rows,
        "value_count": rows,
        "minimum": low,
        "maximum": high,
        "first_time": first,
        "last_time": last,
        "equal_steps": equal,
        "value_changes": rows - equal,
        "backsteps": backsteps,
        "max_backstep_s": max_backstep,
        "min_positive_step": min_step,
        "tzero1_trigtime_met": events["tzero1"],
        "tstart_rel": events["tstart_rel"],
        "tstop_rel": events["tstop_rel"],
        "object": events["object"],
        "sha256": hashlib.sha256(emitted).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary" or len(manifest["series"]) != 1:
        fail("manifest must declare exactly the one primary series")
    with args.sources.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    inventory = json.loads((args.download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    inv = {r["burst"]: r for r in inventory["records"]}
    index = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in index}
    if len(by_path) != len(index):
        fail("duplicate sample paths in index")

    expected_names = set()
    seen_hashes = set()
    for src in sources:
        burst = src["burst"]
        filename = Path(src["key"]).name
        source = args.download_dir / filename
        if source.stat().st_size != int(src["bytes"]):
            fail(f"{burst}: source size changed")
        source_sha = sha256_bytes_file(source)
        if source_sha != inv[burst]["sha256"]:
            fail(f"{burst}: source SHA-256 differs from download inventory")
        name = f"{burst}_{src['detector']}_v{int(src['version']):02d}_time.bin"
        expected_names.add(name)
        sample = args.samples_dir / name
        rel = sample.relative_to(args.data_root).as_posix()
        if rel not in by_path:
            fail(f"{rel} missing from index")
        entry = by_path[rel]
        result = verify_sample(source, filename, src["detector"], sample)
        if result["rows"] != int(src["rows"]):
            fail(f"{burst}: rows differ from pinned sources.tsv")
        if repr(result["tzero1_trigtime_met"]) != src["tzero1"]:
            fail(f"{burst}: TZERO1 differs from pinned sources.tsv")
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": result["value_count"] * 8,
            "sample_shape": [result["value_count"]],
            "burst": burst,
            "detector": src["detector"],
            "source_file": filename,
            "source_sha256": source_sha,
        }
        for key in ("value_count", "minimum", "maximum", "first_time", "last_time", "equal_steps", "value_changes",
                    "backsteps", "max_backstep_s", "min_positive_step",
                    "tzero1_trigtime_met", "tstart_rel", "tstop_rel", "object", "sha256"):
            fixed[key] = result[key]
        for key, expected_value in fixed.items():
            if entry.get(key) != expected_value:
                fail(f"{name}: index {key}={entry.get(key)!r}, recomputed {expected_value!r}")
        if result["sha256"] in seen_hashes:
            fail(f"{name}: duplicate sample content")
        seen_hashes.add(result["sha256"])
        print(f"verified {burst} {src['detector']} rows={result['rows']} span={result['minimum']:.6f}.."
              f"{result['maximum']:.6f} equal_steps={result['equal_steps']} backsteps={result['backsteps']}")

    actual_names = {p.name for p in args.samples_dir.iterdir()}
    if actual_names != expected_names:
        fail(f"sample directory differs from pinned bursts: extra={sorted(actual_names - expected_names)} "
             f"missing={sorted(expected_names - actual_names)}")
    if len(index) != len(sources):
        fail("index has rows for unpinned samples")
    counts = [int(row["value_count"]) for row in index]
    total_bytes = sum(int(row["sample_size_bytes"]) for row in index)
    if series[0]["sample_count"] != len(index) or series[0]["total_size_bytes"] != total_bytes:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} != realized "
             f"{len(index)}/{total_bytes}")
    if sum(counts) < 10_000 or statistics.median(counts) < 1_000 or total_bytes > 1_000_000_000:
        fail("acceptance floor or cap violated")
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if (stats["samples"], stats["primary_values"], stats["primary_bytes"]) != (len(index), sum(counts), total_bytes):
        fail("ingest stats disagree with verified output")
    print(f"verify ok samples={len(index)} primary_values={sum(counts)} primary_bytes={total_bytes} "
          f"median_values={statistics.median(counts)}")


if __name__ == "__main__":
    main()
