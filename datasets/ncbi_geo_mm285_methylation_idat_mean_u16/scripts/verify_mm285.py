#!/usr/bin/env python3
"""Independent verifier for ncbi_geo_mm285_methylation_idat_mean_u16.

Does not import the build module. It re-reads every pinned IDAT.gz with its
own field-table walk, re-extracts field 104 (Mean), and requires the emitted
sample to be byte-identical; it recomputes the per-sample statistics with a
sort (the build uses a histogram), re-applies the same degenerate-array
policy, and checks the index, the sample directory and the manifest totals.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "ncbi_geo_mm285_methylation_idat_mean_u16"
N = 361_821
SERIES_BY_CHANNEL = {"Grn": "mm285_grn_bead_type_mean_u16", "Red": "mm285_red_bead_type_mean_u16"}
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
# Same degenerate-array policy as scripts/mm285_idat.py.
MIN_DISTINCT = 2_000
MAX_ZERO_FRACTION = 0.001
MAX_P01 = 1_500
MIN_P50 = 200
MIN_P99 = 3_000
MIN_MAX = 10_000
MAX_NBEADS_ZERO_FRACTION = 0.01


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def u(buf: memoryview, offset: int, width: int, signed: bool = False) -> int:
    if offset < 0 or offset + width > len(buf):
        fail(f"read of {width} bytes at {offset} outside buffer of {len(buf)}")
    return int.from_bytes(buf[offset : offset + width], "little", signed=signed)


def net_string(buf: memoryview, offset: int) -> str:
    length, shift, pos = 0, 0, offset
    while True:
        byte = u(buf, pos, 1)
        pos += 1
        length += (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
        if shift > 28:
            fail("string length prefix too long")
    return bytes(buf[pos : pos + length]).decode("ascii")


def read_fields(raw: bytes) -> tuple[memoryview, dict[int, int]]:
    buf = memoryview(raw)
    if bytes(buf[:4]) != b"IDAT":
        fail("bad IDAT magic")
    if u(buf, 4, 8, signed=True) != 3:
        fail("IDAT version is not 3")
    count = u(buf, 12, 4, signed=True)
    fields: dict[int, int] = {}
    for i in range(count):
        base = 16 + 10 * i
        fields[u(buf, base, 2)] = u(buf, base + 2, 8, signed=True)
    return buf, fields


def le_values(code: str, data: bytes) -> array:
    values = array(code, data)
    if sys.byteorder == "big":
        values.byteswap()
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("--idat-dir", "--pins", "--manifest", "--samples-dir", "--index", "--stats", "--data-root"):
        parser.add_argument(name, required=True)
    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()
    idat_dir = Path(args.idat_dir)
    samples_dir = Path(args.samples_dir).resolve()

    pins = list(csv.DictReader(open(args.pins, encoding="ascii"), delimiter="\t"))
    if len(pins) != 150:
        fail(f"expected 150 pinned IDATs, found {len(pins)}")
    pin_by_name = {pin["file_name"]: pin for pin in pins}

    rows = [json.loads(line) for line in open(args.index, encoding="utf-8") if line.strip()]
    if len(rows) != len(pins):
        fail(f"index rows {len(rows)} != pinned files {len(pins)}")
    seen: set[str] = set()
    pair_hash: dict[tuple[str, str], str] = {}
    totals: dict[str, dict] = {sid: {"count": 0, "bytes": 0, "min": 65535, "max": 0} for sid in SERIES_BY_CHANNEL.values()}
    id_hashes: set[str] = set()
    expected_paths: set[Path] = set()

    for row in rows:
        missing = [key for key in INDEX_KEYS if key not in row]
        if missing:
            fail(f"index row missing {missing}: {row.get('sample_path')}")
        name = row.get("source_file")
        pin = pin_by_name.get(name)
        if pin is None or name in seen:
            fail(f"index row for unpinned or duplicate source {name!r}")
        seen.add(name)
        series_id = SERIES_BY_CHANNEL[pin["channel"]]
        if row["dataset_id"] != DATASET_ID or row["series_id"] != series_id:
            fail(f"{name}: dataset/series mismatch {row['dataset_id']}/{row['series_id']}")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("uint", 16, "little", 2):
            fail(f"{name}: wrong numeric declaration")
        if row["value_count"] != N or row["sample_size_bytes"] != 2 * N:
            fail(f"{name}: value_count/sample_size_bytes {row['value_count']}/{row['sample_size_bytes']}")
        stem = name[: -len(".idat.gz")]
        sample_path = (data_root / row["sample_path"]).resolve()
        if sample_path != samples_dir / series_id / f"{stem}.bin":
            fail(f"{name}: unexpected sample path {row['sample_path']}")
        expected_paths.add(sample_path)
        sample = sample_path.read_bytes()
        if len(sample) != 2 * N:
            fail(f"{name}: sample file has {len(sample)} bytes")

        source = idat_dir / name
        compressed = source.read_bytes()
        if len(compressed) != int(pin["size_bytes"]):
            fail(f"{name}: source size differs from pin")
        source_digest = hashlib.sha256(compressed).hexdigest()
        if row.get("source_gz_sha256") != source_digest:
            fail(f"{name}: index source_gz_sha256 differs from the local file")
        pinned_digest = (pin.get("sha256") or "").strip().lower()
        if pinned_digest and pinned_digest != source_digest:
            fail(f"{name}: local file sha256 differs from the pinned value")
        raw = gzip.decompress(compressed)
        buf, fields = read_fields(raw)
        for code in (1000, 102, 104, 107, 402, 404):
            if code not in fields:
                fail(f"{name}: field {code} missing")
        if u(buf, fields[1000], 4, signed=True) != N:
            fail(f"{name}: nSNPsRead != {N}")
        if net_string(buf, fields[402]) != pin["chip_barcode"] or net_string(buf, fields[404]) != pin["array_position"]:
            fail(f"{name}: barcode/position fields disagree with the file name")
        mean_src = bytes(buf[fields[104] : fields[104] + 2 * N])
        if mean_src != sample:
            fail(f"{name}: sample bytes differ from IDAT field 104")
        id_hashes.add(hashlib.sha256(buf[fields[102] : fields[102] + 4 * N]).hexdigest())
        nbeads_zero = bytes(buf[fields[107] : fields[107] + N]).count(b"\x00")

        digest = hashlib.sha256(sample).hexdigest()
        if row.get("sample_sha256") != digest:
            fail(f"{name}: sample_sha256 mismatch")
        ordered = sorted(le_values("H", sample))
        stats = {
            "min": ordered[0],
            "max": ordered[-1],
            "median": ordered[N // 2],
            "distinct_values": len(set(ordered)),
            "zero_count": ordered.count(0),
            "nbeads_zero_count": nbeads_zero,
        }
        for key, value in stats.items():
            if row.get(key) != value:
                fail(f"{name}: index {key}={row.get(key)} but recomputed {value}")
        p01, p99 = ordered[int(N * 0.01)], ordered[int(N * 0.99)]
        problems = []
        if stats["distinct_values"] < MIN_DISTINCT:
            problems.append("too few distinct values")
        if stats["zero_count"] > MAX_ZERO_FRACTION * N:
            problems.append("too many zero Means")
        if p01 > MAX_P01:
            problems.append(f"p01 {p01} lacks a background floor")
        if stats["median"] < MIN_P50:
            problems.append(f"median {stats['median']} (dead array)")
        if p99 < MIN_P99 or stats["max"] < MIN_MAX:
            problems.append(f"p99 {p99} / max {stats['max']} lacks bright probes")
        if nbeads_zero > MAX_NBEADS_ZERO_FRACTION * N:
            problems.append("too many bead types without beads")
        if problems:
            fail(f"{name}: degenerate array: {'; '.join(problems)}")
        pair_hash[(pin["gsm"], pin["channel"])] = digest
        entry = totals[series_id]
        entry["count"] += 1
        entry["bytes"] += len(sample)
        entry["min"] = min(entry["min"], stats["min"])
        entry["max"] = max(entry["max"], stats["max"])

    if seen != set(pin_by_name):
        fail(f"pinned IDATs without samples: {sorted(set(pin_by_name) - seen)[:5]}")
    if len(id_hashes) != 1:
        fail(f"IlluminaID order differs across samples ({len(id_hashes)} variants)")
    for gsm in sorted({pin["gsm"] for pin in pins}):
        if pair_hash[(gsm, "Grn")] == pair_hash[(gsm, "Red")]:
            fail(f"{gsm}: Grn and Red samples are identical")

    on_disk = {path.resolve() for path in samples_dir.rglob("*") if path.is_file()}
    if on_disk != expected_paths:
        extra = sorted(str(p) for p in on_disk - expected_paths)[:5]
        fail(f"sample directory holds unindexed files: {extra}")

    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    declared = {series["id"]: series for series in manifest.get("series", [])}
    for series_id, entry in totals.items():
        series = declared.get(series_id)
        if series is None or series.get("role") != "primary":
            fail(f"manifest lacks primary series {series_id}")
        if series.get("sample_count") != entry["count"] or series.get("total_size_bytes") != entry["bytes"]:
            fail(
                f"{series_id}: manifest sample_count/total_size_bytes {series.get('sample_count')}/"
                f"{series.get('total_size_bytes')} != realized {entry['count']}/{entry['bytes']}"
            )
        if entry["count"] != 75:
            fail(f"{series_id}: expected 75 samples, found {entry['count']}")
        if entry["min"] >= 1_000 or entry["max"] < 10_000:
            fail(f"{series_id}: series range {entry['min']}..{entry['max']} does not span background to bright probes")

    build_stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if build_stats.get("emitted_samples") != len(rows) or build_stats.get("illumina_id_order_sha256") not in id_hashes:
        fail("ingest_stats.json disagrees with the verified output")

    total_bytes = sum(entry["bytes"] for entry in totals.values())
    print(f"verify_ok=1 samples={len(rows)} total_bytes={total_bytes} values={len(rows) * N}")
    for series_id, entry in totals.items():
        print(f"  {series_id}: samples={entry['count']} bytes={entry['bytes']} range={entry['min']}..{entry['max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
