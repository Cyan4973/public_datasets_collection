#!/usr/bin/env python3
"""Independent verifier for icon_ivm_a_l27_ion_drift_velocity_f64.

Re-derives every sample from the cached HDF5 metadata blocks and chunk spans
with separate code paths from the build:

* datasets are located through the root group's creation-order link index
  (the build uses the name index);
* chunks are inflated with one-shot ``zlib.decompress`` and unshuffled by
  zipping byte planes (the build uses a streaming inflater and strided
  slice assignment);
* the missing-value policy is re-applied with ``struct.iter_unpack``.

Then it byte-compares every sample, recomputes every index field, rejects
NaN/inf, constant, low-diversity, short and duplicate samples, checks that
exactly the (day, component) pairs with fewer than 1,000 finite values are
absent, decodes the complete control file the same independent way and
compares it with the range decode, and checks the manifest totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import icon_ivm  # noqa: E402  (constants and pinned source list only)
from h5lite import BlockStore, H5File  # noqa: E402

INDEX_KEYS = {
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count", "date", "component",
    "source_variable", "source_key", "source_version", "data_version", "source_records",
    "nan_fill_dropped", "outside_valid_range_kept", "min", "max", "sha256",
}
MIN_DISTINCT_FRACTION = 0.5


def fail(message: str) -> None:
    raise SystemExit(f"verify FAILED: {message}")


def unshuffle_planes(data: bytes, size: int) -> bytes:
    count = len(data) // size
    planes = [data[i * count:(i + 1) * count] for i in range(size)]
    return b"".join(bytes(element) for element in zip(*planes)) + data[count * size:]


def decode_chunk_independent(stored: bytes, size: int, expected: int) -> bytes:
    inflated = zlib.decompress(stored)
    if len(inflated) != expected:
        fail(f"chunk inflates to {len(inflated)} bytes, expected {expected}")
    return unshuffle_planes(inflated, size)


def decode_span_independent(span: bytes, span_start: int, chunks: list[tuple[int, int]], records: int,
                            chunk_elements: int) -> bytes:
    parts = []
    for size, addr in chunks:
        lo = addr - span_start
        if lo < 0 or lo + size > len(span):
            fail("chunk outside its span")
        parts.append(decode_chunk_independent(span[lo:lo + size], 8, chunk_elements * 8))
    return b"".join(parts)[:records * 8]


def policy_independent(decoded: bytes) -> bytes:
    kept = []
    for (value,) in struct.iter_unpack("<d", decoded):
        if value != value:
            continue
        if value in (math.inf, -math.inf):
            fail("infinite value in source")
        kept.append(value)
    return struct.pack(f"<{len(kept)}d", *kept)


def walk(raw, row: dict) -> dict:
    """Locate the three datasets via the creation-order index; return chunk lists."""
    f = H5File(raw)
    links = f.links(f.root_addr, index="creation_order")
    ga = f.attributes(f.root_addr)
    if ga.get("Instrument") != "IVM-A" or ga.get("LogicalSource") != "ICON_L2-7_IVM-A":
        fail(f"{row['date']}: not an IVM-A L2-7 file")
    out = {}
    for component, var in icon_ivm.COMPONENTS:
        info = f.dataset(links[var])
        if info["datatype"] != icon_ivm.F64LE or len(info["shape"]) != 1:
            fail(f"{row['date']} {var}: dtype/shape")
        records = info["shape"][0]
        entries, _final = f.chunk_index(info["chunk_btree"], 2)
        entries.sort(key=lambda e: e[2][0])
        chunk_elements = info["chunk_dims"][0]
        if info["chunk_dims"][1] != 8 or chunk_elements < 1:
            fail(f"{row['date']} {var}: chunk dims")
        nchunks = -(-records // chunk_elements)
        if [e[2][0] for e in entries] != [i * chunk_elements for i in range(nchunks)]:
            fail(f"{row['date']} {var}: chunk grid")
        if any(e[1] for e in entries):
            fail(f"{row['date']} {var}: filter mask")
        chunks = [(e[0], e[3]) for e in entries]
        out[component] = {
            "variable": var,
            "records": records,
            "chunk_elements": chunk_elements,
            "chunks": chunks,
            "span_start": min(a for _s, a in chunks),
            "span_end": max(a + s for s, a in chunks),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", required=True)
    parser.add_argument("--recipe-dir", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    downloads = Path(args.downloads)
    recipe_dir = Path(args.recipe_dir)
    data_root = Path(args.data_root)
    rows = icon_ivm.load_sources(recipe_dir)
    dataset_id, series_id = icon_ivm.DATASET_ID, icon_ivm.SERIES_ID

    index_path = data_root / "index" / dataset_id / "samples.jsonl"
    index = {}
    for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
        entry = json.loads(line)
        if set(entry) != INDEX_KEYS:
            fail(f"index line {line_number}: keys {sorted(set(entry) ^ INDEX_KEYS)}")
        key = (entry["date"], entry["component"])
        if key in index:
            fail(f"duplicate index entry {key}")
        index[key] = entry

    digests = {}
    total_bytes = total_values = 0
    expected_keys = set()
    control_decoded = {}
    years = set()
    for row in rows:
        store = BlockStore(downloads / "days" / row["date"] / "meta", row["size_bytes"], icon_ivm.BLOCK_SIZE)
        comps = walk(store, row)
        for component, var in icon_ivm.COMPONENTS:
            comp = comps[component]
            span_file = downloads / "days" / row["date"] / f"span_{component}.bin"
            span = span_file.read_bytes()
            if len(span) != comp["span_end"] - comp["span_start"]:
                fail(f"{span_file}: size does not match its chunk span")
            decoded = decode_span_independent(span, comp["span_start"], comp["chunks"], comp["records"],
                                              comp["chunk_elements"])
            if row["date"] == icon_ivm.CONTROL_DATE:
                control_decoded[component] = (decoded, comp)
            kept = policy_independent(decoded)
            count = len(kept) // 8
            if count < icon_ivm.MIN_SAMPLE_VALUES:
                if (row["date"], component) in index:
                    fail(f"{row['date']} {component}: below 1,000 finite values but emitted")
                continue
            expected_keys.add((row["date"], component))
            entry = index.get((row["date"], component))
            if entry is None:
                fail(f"{row['date']} {component}: sample missing from index")
            path = data_root / entry["sample_path"]
            sample = path.read_bytes()
            if sample != kept:
                fail(f"{path}: bytes differ from the independent re-derivation")
            values = [v for (v,) in struct.iter_unpack("<d", sample)]
            if any(not math.isfinite(v) for v in values):
                fail(f"{path}: non-finite value")
            distinct = len(set(values))
            if distinct < 2:
                fail(f"{path}: constant sample")
            if distinct < MIN_DISTINCT_FRACTION * count:
                fail(f"{path}: only {distinct} distinct of {count} values")
            digest = hashlib.sha256(sample).hexdigest()
            if digest in digests:
                fail(f"{path}: duplicate of {digests[digest]}")
            digests[digest] = str(path)
            expected_entry = {
                "dataset_id": dataset_id,
                "series_id": series_id,
                "sample_path": str(path.relative_to(data_root)),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(sample),
                "value_count": count,
                "source_variable": var,
                "source_key": row["key"],
                "source_version": row["version"],
                "source_records": comp["records"],
                "nan_fill_dropped": comp["records"] - count,
                "outside_valid_range_kept": sum(1 for v in values if v < -500.0 or v > 500.0),
                "min": min(values),
                "max": max(values),
                "sha256": digest,
            }
            for key, want in expected_entry.items():
                if entry[key] != want:
                    fail(f"{path}: index field {key}={entry[key]!r}, recomputed {want!r}")
            if not entry["sample_path"].startswith(f"samples/{dataset_id}/{series_id}/{row['date'][:4]}/"):
                fail(f"{path}: unexpected sample location")
            total_bytes += len(sample)
            total_values += count
            years.add(row["date"][:4])
    if set(index) != expected_keys:
        fail(f"index has {len(set(index) - expected_keys)} unexpected entries")
    on_disk = {str(p.relative_to(data_root)) for p in (data_root / "samples" / dataset_id).rglob("*") if p.is_file()}
    if on_disk != {e["sample_path"] for e in index.values()}:
        fail("sample directory holds files not in the index (or vice versa)")
    if years != {"2019", "2020", "2021", "2022"}:
        fail(f"years covered {sorted(years)}")

    # Control: independent whole-file decode equals the range decode.
    control = next(r for r in rows if r["date"] == icon_ivm.CONTROL_DATE)
    raw = (downloads / "control" / Path(control["key"]).name).read_bytes()
    if len(raw) != control["size_bytes"]:
        fail("control file size")
    full = walk(raw, control)
    for component, _var in icon_ivm.COMPONENTS:
        comp = full[component]
        whole = decode_span_independent(raw[comp["span_start"]:comp["span_end"]], comp["span_start"],
                                        comp["chunks"], comp["records"], comp["chunk_elements"])
        if whole != control_decoded[component][0]:
            fail(f"control {component}: whole-file decode differs from range decode")

    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == series_id]
    if len(series) != 1:
        fail("manifest must declare the series exactly once")
    if series[0]["sample_count"] != len(index) or series[0]["total_size_bytes"] != total_bytes:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} != "
             f"realized {len(index)}/{total_bytes}")
    print(f"verify_ok samples={len(index)} bytes={total_bytes} values={total_values} "
          f"years={sorted(years)} control_identical=3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
