#!/usr/bin/env python3
"""Independent verification of the BATSE CONT COUNTS samples.

Shares no code with batse_cont.py: it has its own FITS card parser and HDU
walker, derives the COUNTS byte offset from the TFORM list, and re-decodes
every row with struct ('>128h' -> '<128h'), comparing byte-for-byte against
the emitted sample. It then recomputes every index statistic, the sample
inventory, the manifest totals, and the degenerate-output checks.

Missing-value policy (same as build): none. COUNTS has no TNULL; every value,
including rare telemetry glitches (negative or very large words), is emitted
unchanged. Nothing is masked, clipped, imputed, or dropped.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import re
import statistics
import struct
import tomllib
from pathlib import Path

DATASET_ID = "nasa_heasarc_batse_cont_counts_i16"
SERIES_ID = "batse_lad_cont_counts_i16"
BLOCK = 2880
CARD = re.compile(r"^([A-Z0-9_-]{1,8})\s*= ?(.*)$")
STRING = re.compile(r"^\s*'((?:[^']|'')*)'")
TFORM = re.compile(r"^\s*(\d*)([A-Z])\s*$")
WIDTH = {"L": 1, "X": 0, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}
BE_ROW = struct.Struct(">128h")
LE_ROW = struct.Struct("<128h")
ROW_FLOOR = 20_000
MIN_DISTINCT = 256
MAX_REPEATED_ROW_FRACTION = 0.05
SPIKE = 4096


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def header_cards(stream) -> dict[str, str] | None:
    cards: dict[str, str] = {}
    first = True
    while True:
        block = stream.read(BLOCK)
        if first and block == b"":
            return None
        first = False
        if len(block) != BLOCK:
            fail("truncated FITS header")
        for i in range(36):
            text = block[80 * i:80 * i + 80].decode("ascii")
            if text.startswith("END     ") or text.rstrip() == "END":
                return cards
            if text.startswith("COMMENT"):
                cards["COMMENT"] = cards.get("COMMENT", "") + text[8:].strip() + "\n"
                continue
            match = CARD.match(text)
            if match and text[8] == "=":
                cards[match.group(1)] = match.group(2)


def text_value(cards: dict[str, str], key: str) -> str | None:
    raw = cards.get(key)
    if raw is None:
        return None
    match = STRING.match(raw)
    if match:
        return match.group(1).replace("''", "'").rstrip()
    return raw.split("/")[0].strip()


def int_value(cards: dict[str, str], key: str, default: int | None = None) -> int:
    value = text_value(cards, key)
    if value is None:
        if default is None:
            fail(f"missing keyword {key}")
        return default
    return int(value)


def data_size(cards: dict[str, str]) -> int:
    naxis = int_value(cards, "NAXIS")
    if naxis == 0:
        return 0
    n = 1
    for i in range(1, naxis + 1):
        n *= int_value(cards, f"NAXIS{i}")
    size = abs(int_value(cards, "BITPIX")) // 8 * int_value(cards, "GCOUNT", 1) * (n + int_value(cards, "PCOUNT", 0))
    return -(-size // BLOCK) * BLOCK


def open_counts(path: Path, tjd: int):
    stream = gzip.open(path, "rb")
    primary = header_cards(stream)
    if primary is None:
        fail(f"{path.name}: empty")
    if (text_value(primary, "TELESCOP"), text_value(primary, "INSTRUME"), text_value(primary, "FILETYPE")) != (
        "COMPTON GRO", "BATSE", "BATSE_CONT"
    ):
        fail(f"{path.name}: not a BATSE CONT file")
    if int_value(primary, "TJD") != tjd:
        fail(f"{path.name}: primary TJD mismatch")
    stream.read(data_size(primary))
    while True:
        cards = header_cards(stream)
        if cards is None:
            fail(f"{path.name}: BATSE_CNTS not found")
        if text_value(cards, "EXTNAME") != "BATSE_CNTS":
            stream.read(data_size(cards))
            continue
        fields = int_value(cards, "TFIELDS")
        offset = 0
        counts_index = counts_offset = None
        for i in range(1, fields + 1):
            match = TFORM.match(text_value(cards, f"TFORM{i}") or "")
            if not match:
                fail(f"{path.name}: unparsable TFORM{i}")
            repeat = int(match.group(1) or 1)
            width = (repeat + 7) // 8 if match.group(2) == "X" else repeat * WIDTH[match.group(2)]
            if text_value(cards, f"TTYPE{i}") == "COUNTS":
                if (repeat, match.group(2)) != (128, "I"):
                    fail(f"{path.name}: COUNTS is not 128I")
                counts_index, counts_offset = i, offset
            offset += width
        row_bytes = int_value(cards, "NAXIS1")
        if counts_index is None or offset != row_bytes or row_bytes != 336 or counts_offset != 28:
            fail(f"{path.name}: BATSE_CNTS layout changed")
        if (text_value(cards, f"TDIM{counts_index}") or "").replace(" ", "") != "(8,16)":
            fail(f"{path.name}: COUNTS TDIM changed")
        if any(f"{key}{counts_index}" in cards for key in ("TZERO", "TSCAL", "TNULL")):
            fail(f"{path.name}: COUNTS has scaling or null keywords")
        return stream, int_value(cards, "NAXIS2"), row_bytes, counts_offset


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sample(source: Path, tjd: int, sample: Path) -> dict[str, object]:
    stream, rows, row_bytes, counts_offset = open_counts(source, tjd)
    if sample.stat().st_size != rows * 256:
        fail(f"{sample.name}: size {sample.stat().st_size} != rows*256 ({rows})")
    histogram: collections.Counter = collections.Counter()
    repeated = 0
    previous = None
    digest = hashlib.sha256()
    with stream, sample.open("rb") as out:
        for _ in range(rows):
            row = stream.read(row_bytes)
            if len(row) != row_bytes:
                fail(f"{source.name}: truncated table")
            values = BE_ROW.unpack_from(row, counts_offset)
            emitted = out.read(256)
            if emitted != LE_ROW.pack(*values):
                fail(f"{sample.name}: bytes differ from source COUNTS")
            digest.update(emitted)
            histogram.update(values)
            if values == previous:
                repeated += 1
            previous = values
        if out.read(1):
            fail(f"{sample.name}: trailing bytes")
        pad = (-rows * row_bytes) % BLOCK
        padding = stream.read(pad)
        if len(padding) != pad or padding.count(0) != pad:
            fail(f"{source.name}: BATSE_CNTS padding not zero")
        # Only header-only RUN_LOG extensions (writer log) may follow; their
        # logged CONTINUOUS row count must agree with NAXIS2.
        while (extra := header_cards(stream)) is not None:
            if text_value(extra, "EXTNAME") != "RUN_LOG" or data_size(extra) != 0:
                fail(f"{source.name}: unexpected HDU {text_value(extra, 'EXTNAME')!r} after BATSE_CNTS")
            logged = re.findall(r"(\d+) rows of CONTINUOUS data written", extra.get("COMMENT", ""))
            if logged and [int(n) for n in logged] != [rows]:
                fail(f"{source.name}: RUN_LOG row count {logged} != NAXIS2 {rows}")
    if rows < ROW_FLOOR:
        fail(f"{sample.name}: {rows} rows below floor")
    if min(histogram) >= max(histogram) or len(histogram) < MIN_DISTINCT:
        fail(f"{sample.name}: degenerate COUNTS ({len(histogram)} distinct)")
    if repeated > MAX_REPEATED_ROW_FRACTION * rows:
        fail(f"{sample.name}: {repeated} repeated rows")
    return {
        "rows": rows,
        "value_count": rows * 128,
        "minimum": min(histogram),
        "maximum": max(histogram),
        "distinct_values": len(histogram),
        "negative_count": sum(c for v, c in histogram.items() if v < 0),
        "zero_count": histogram[0],
        "spike_count": sum(c for v, c in histogram.items() if v >= SPIKE),
        "sha256": digest.hexdigest(),
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
    if len(series) != 1 or series[0]["role"] != "primary":
        fail("manifest primary series missing")
    with args.sources.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    inventory = json.loads((args.download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    inv = {int(r["tjd"]): r for r in inventory["records"]}
    index = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in index}
    if len(by_path) != len(index):
        fail("duplicate sample paths in index")

    expected_names = set()
    seen_hashes = set()
    for src in sources:
        tjd = int(src["tjd"])
        source = args.download_dir / Path(src["key"]).name
        if source.stat().st_size != int(src["bytes"]):
            fail(f"TJD {tjd}: source size changed")
        source_sha = sha256_file(source)
        if source_sha != inv[tjd]["sha256"] or (src.get("sha256") and source_sha != src["sha256"]):
            fail(f"TJD {tjd}: source SHA-256 mismatch")
        name = f"cont_{tjd:05d}_counts.bin"
        expected_names.add(name)
        sample = args.samples_dir / name
        rel = sample.relative_to(args.data_root).as_posix()
        if rel not in by_path:
            fail(f"{rel} missing from index")
        entry = by_path[rel]
        result = verify_sample(source, tjd, sample)
        if result["rows"] != int(src["rows"]):
            fail(f"TJD {tjd}: rows differ from pinned sources.tsv")
        if sha256_file(sample) != result["sha256"]:
            fail(f"{name}: file hash changed during verification")
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": result["value_count"] * 2,
            "sample_shape": [result["rows"], 16, 8],
            "tjd": tjd,
            "source_sha256": source_sha,
        }
        for key in ("value_count", "minimum", "maximum", "distinct_values", "negative_count",
                    "zero_count", "spike_count", "sha256"):
            fixed[key] = result[key]
        for key, value in fixed.items():
            if entry.get(key) != value:
                fail(f"{name}: index {key}={entry.get(key)!r}, recomputed {value!r}")
        if result["sha256"] in seen_hashes:
            fail(f"{name}: duplicate sample content")
        seen_hashes.add(result["sha256"])
        print(f"verified tjd={tjd} rows={result['rows']} range={result['minimum']}..{result['maximum']} "
              f"neg={result['negative_count']} spikes={result['spike_count']}")

    actual_names = {p.name for p in args.samples_dir.iterdir()}
    if actual_names != expected_names:
        fail(f"sample directory differs from pinned days: extra={sorted(actual_names - expected_names)} "
             f"missing={sorted(expected_names - actual_names)}")
    if len(index) != len(sources):
        fail("index has rows for unpinned samples")
    counts = [int(row["value_count"]) for row in index]
    total_bytes = sum(int(row["sample_size_bytes"]) for row in index)
    if series[0]["sample_count"] != len(index) or series[0]["total_size_bytes"] != total_bytes:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} != realized {len(index)}/{total_bytes}")
    if sum(counts) < 10_000 or statistics.median(counts) < 1_000 or total_bytes > 1_000_000_000:
        fail("acceptance floor or cap violated")
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if (stats["samples"], stats["primary_values"], stats["primary_bytes"]) != (len(index), sum(counts), total_bytes):
        fail("ingest stats disagree with verified output")
    print(f"verify ok samples={len(index)} primary_values={sum(counts)} primary_bytes={total_bytes} "
          f"median_values={statistics.median(counts)}")


if __name__ == "__main__":
    main()
