#!/usr/bin/env python3
"""Independent verification of the JPL COSMIC-1 L1 excess-phase samples.

This re-derives every sample from the downloaded NetCDF4 files without the
build's decode function: variables are resolved through the root group's
creation-order link index (build uses the name index), the L1 row, fill
policy and 50 Hz check are re-implemented here with ``array``-based decoding,
and the result is byte-compared with each emitted sample.  It also reads every
sample file on its own and rejects fill, NaN/inf, sentinel-sized magnitudes,
short, constant or low-diversity series and exact duplicates, and checks the
index, ingest stats and manifest totals against the realized output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import struct
import sys
import tomllib
from array import array
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
import gnssro  # noqa: E402  (pinned source list, constants and paths only)

FILL = -9.99e20
MIN_VALUES = 1000
MAX_ABS = 1.0e9
REQUIRED_INDEX_FIELDS = (
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
)


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def doubles(data: bytes) -> array:
    values = array("d")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    return values


class Drop(Exception):
    pass


def raw_extent(h5: h5lite.H5File, info: dict) -> bytes:
    if info["layout_class"] != 1:
        raise Drop("layout_not_contiguous")
    if info["filters"]:
        raise Drop("filter_pipeline_present")
    return h5.raw[info["data_addr"]:info["data_addr"] + info["data_size"]]


def rederive(raw: bytes, row: dict) -> tuple[str, object]:
    try:
        return _rederive(raw, row)
    except Drop as drop:
        return "drop", str(drop)


def _rederive(raw: bytes, row: dict) -> tuple[str, object]:
    """('keep', payload) or ('drop', reason); raises on wrong product identity."""
    h5 = h5lite.H5File(raw)
    links = h5.links(h5.root_addr, "creation_order")
    g = h5.attributes(h5.root_addr)
    identity = (
        g.get("mission") == "cosmic1"
        and g.get("institution") == "jpl"
        and g.get("institution_version") == "v2.6"
        and g.get("VersionID") == "2.0"
        and g.get("ShortName") == "gnssro_cosmic1_jpl_l1b"
        and g.get("data_use_license") == "http://creativecommons.org/licenses/by/4.0/"
        and g.get("GranuleID") == row["granule"]
    )
    if not identity:
        raise ValueError(f"{row['key']}: not the pinned JPL COSMIC-1 v2.6 L1b product")
    ep = h5.dataset(links["excess_phase"])
    if ep["datatype"] != gnssro.F64_LE:
        return "drop", "excess_phase_not_f64_le"
    nsig, n = ep["shape"]
    data = raw_extent(h5, ep)
    poc = raw_extent(h5, h5.dataset(links["phase_observation_code"]))
    codes = [poc[i * 3:i * 3 + 3] for i in range(nsig)]
    rows = [i for i, c in enumerate(codes) if c[:2] == b"L1"]
    if len(rows) != 1:
        return "drop", "no_unique_l1_row"
    r = rows[0]
    freq = doubles(raw_extent(h5, h5.dataset(links["carrier_frequency"])))
    if freq[r] != 1575.42e6:
        return "drop", "l1_row_not_1575_42_mhz"
    line = doubles(data[8 * r * n:8 * (r + 1) * n])

    def bad(x: float) -> bool:
        return x == FILL or x != x or x in (math.inf, -math.inf)

    lo = 0
    while lo < n and bad(line[lo]):
        lo += 1
    if lo == n:
        return "drop", "l1_all_fill"
    hi = n
    while bad(line[hi - 1]):
        hi -= 1
    if any(bad(line[i]) for i in range(lo, hi)):
        return "drop", "l1_interior_fill"
    if hi - lo < MIN_VALUES:
        return "drop", "l1_span_below_1000"
    if max(line[lo:hi]) == min(line[lo:hi]):
        return "drop", "l1_constant"
    t = doubles(raw_extent(h5, h5.dataset(links["time"])))
    diffs = sorted(t[i + 1] - t[i] for i in range(lo, hi - 1))
    mid = len(diffs) // 2
    median = diffs[mid] if len(diffs) % 2 else (diffs[mid - 1] + diffs[mid]) / 2
    if diffs[0] <= 0 or not 0.0199 <= median <= 0.0201:
        return "drop", "not_50hz_monotonic"
    return "keep", (data[8 * (r * n + lo):8 * (r * n + hi)], codes[r].decode("ascii"), r, lo, hi)


def check_sample_bytes(path: Path, entry: dict) -> list[float]:
    data = path.read_bytes()
    if len(data) != entry["sample_size_bytes"] or len(data) % 8:
        fail(f"{path}: size {len(data)} disagrees with index")
    values = doubles(data)
    if len(values) != entry["value_count"] or len(values) < MIN_VALUES:
        fail(f"{path}: value count {len(values)}")
    for x in values:
        if x == FILL or not math.isfinite(x) or abs(x) >= MAX_ABS:
            fail(f"{path}: fill, non-finite or sentinel-sized value {x!r}")
    lo, hi = min(values), max(values)
    if lo == hi:
        fail(f"{path}: constant series")
    if len(set(values)) < len(values) // 2:
        fail(f"{path}: degenerate series ({len(set(values))} distinct of {len(values)})")
    if entry.get("min") != lo or entry.get("max") != hi:
        fail(f"{path}: index min/max disagree with stored float64 values")
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        fail(f"{path}: sha256 disagrees with index")
    return [lo, hi]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    import selftest_gnssro

    selftest_gnssro.main(quiet=True)

    did, sid = gnssro.DATASET_ID, gnssro.SERIES_ID
    index_path = args.data_root / "index" / did / "samples.jsonl"
    stats_path = args.data_root / "filtered" / did / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        fail("missing index or ingest stats; run build.sh first")
    entries = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = gnssro.load_sources(args.sources)

    position = 0
    drops: Counter = Counter()
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    aggregate = hashlib.sha256()
    lengths: list[int] = []
    total = 0
    for number, row in enumerate(rows, 1):
        src = gnssro.source_path(args.downloads, row)
        raw = src.read_bytes() if src.is_file() else b""
        if len(raw) != row["size"] or hashlib.md5(raw).hexdigest() != row["md5"]:
            fail(f"{src}: missing or size/MD5 mismatch with the pinned source list")
        verdict, result = rederive(raw, row)
        if verdict == "drop":
            drops[result] += 1
            continue
        payload, code, l1_row, lo, hi = result
        if position >= len(entries):
            fail("index has fewer rows than the re-derived sample set")
        entry = entries[position]
        position += 1
        for field in REQUIRED_INDEX_FIELDS:
            if field not in entry:
                fail(f"index row lacks {field}")
        expected_rel = f"samples/{did}/{sid}/{row['month'][:4]}/{row['granule']}_L1.f64le.bin"
        fixed = {
            "dataset_id": did, "series_id": sid, "role": "primary", "sample_path": expected_rel,
            "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8,
            "sample_size_bytes": len(payload), "value_count": len(payload) // 8,
            "source_key": row["key"], "source_md5": row["md5"], "phase_observation_code": code,
            "l1_row": l1_row, "span_start": lo, "span_end": hi,
        }
        for field, value in fixed.items():
            if entry.get(field) != value:
                fail(f"{row['granule']}: index {field}={entry.get(field)!r}, re-derived {value!r}")
        sample = args.data_root / entry["sample_path"]
        if not sample.is_file() or sample.read_bytes() != payload:
            fail(f"{sample}: differs from the independent re-derivation")
        check_sample_bytes(sample, entry)
        digest = entry["sha256"]
        if digest in seen_hashes:
            fail(f"{sample}: exact duplicate of another sample")
        seen_hashes.add(digest)
        seen_paths.add(sample.resolve())
        aggregate.update(payload)
        lengths.append(len(payload) // 8)
        total += len(payload)
        if number % 500 == 0:
            print(f"verified={number}/{len(rows)} kept={len(lengths)}", flush=True)
    if position != len(entries):
        fail(f"index has {len(entries) - position} extra rows")
    on_disk = {p.resolve() for p in (args.data_root / "samples" / did).rglob("*") if p.is_file()}
    if on_disk != seen_paths:
        fail(f"sample tree has {len(on_disk - seen_paths)} stale and {len(seen_paths - on_disk)} missing files")

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    recomputed = {
        "sample_count": len(lengths),
        "value_count": sum(lengths),
        "total_size_bytes": total,
        "dropped": dict(sorted(drops.items())),
        "aggregate_sha256": aggregate.hexdigest(),
        "median_values_per_sample": statistics.median(lengths),
    }
    for key, value in recomputed.items():
        if stats.get(key) != value:
            fail(f"ingest stats {key}={stats.get(key)!r}, recomputed {value!r}")
    if sum(lengths) < 10_000 and total < 100_000:
        fail("aggregate primary floor not met")
    if statistics.median(lengths) < 1000:
        fail("median primary sample below 1000 values")
    if len(stats.get("samples_per_year", {})) != gnssro.LAST_YEAR - gnssro.FIRST_YEAR + 1:
        fail("realized output does not cover every year 2007-2016")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == sid]
    if len(series) != 1:
        fail("manifest series missing")
    if series[0].get("sample_count") != len(lengths) or series[0].get("total_size_bytes") != total:
        fail(
            f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/"
            f"{series[0].get('total_size_bytes')} != realized {len(lengths)}/{total}"
        )
    print(
        f"verify=ok samples={len(lengths)} values={sum(lengths)} bytes={total} "
        f"median_values={statistics.median(lengths)} dropped={dict(sorted(drops.items()))} "
        f"aggregate_sha256={aggregate.hexdigest()}"
    )


if __name__ == "__main__":
    main()
