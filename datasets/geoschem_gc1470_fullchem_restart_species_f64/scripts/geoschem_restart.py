#!/usr/bin/env python3
"""Build and verify GEOS-Chem 14.7.0 fullchem restart species samples.

Source: GEOSChem.Restart.fullchem.20190101_0000z.nc4 (NetCDF4 / HDF5,
superblock v2, dense root-group links).  Every ``SpeciesRst_<name>`` variable
is a (time=1, lev=72, lat=46, lon=72) IEEE float64 little-endian array of dry
mixing ratios, chunked one vertical level per chunk (1, 1, 46, 72) with the
filter pipeline shuffle(8) + deflate.  One species variable becomes one
sample: the decoded values in C order (time, lev, lat, lon), written as raw
little-endian float64 without any rescaling.

Sub-commands:

* ``build``  : decode every species, compute per-species statistics, drop the
  single-value-dominated species under the fixed rule ``degenerate_reason``,
  write samples, ``samples.jsonl`` and the per-species statistics table.
* ``verify`` : re-resolve the variables through the *creation-order* link
  index, re-decode every species, byte-compare against the samples,
  recompute every statistic from the sample files themselves, re-apply the
  drop rule in both directions, and check the index and the manifest totals.

Pure standard library (``mmap``, ``zlib``, ``struct``, ``array``).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import mmap
import os
import struct
import sys
import tomllib
from array import array
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import H5Error, H5File  # noqa: E402

DATASET_ID = "geoschem_gc1470_fullchem_restart_species_f64"
SERIES_ID = "species_dry_mixing_ratio_f64"
SOURCE_RESOURCE = "gc1470_fullchem_restart_20190101"
SPECIES_PREFIX = "SpeciesRst_"

# H5T_IEEE_F64LE exactly as netCDF-4 writes it (class 1 v1, LE, sign bit 63,
# exponent 52..62 bias 1023, mantissa 0..51).
F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
NC_FILL_DOUBLE_BITS = struct.unpack("<Q", struct.pack("<d", 9.969209968386869e36))[0]

REAL_SPEC = {
    "file_size": 589_309_764,
    "shape": (1, 72, 46, 72),
    "chunk_dims": (1, 1, 46, 72, 8),
    "root_links": 417,
    "species": 390,
    "global_attrs": {
        "title": "GEOS-Chem diagnostic collection: Restart",
        "simulation_end_date_and_time": "2019-01-01 00:00:00z",
        "simulation_start_date_and_time": "2018-12-01 00:00:00z",
        "contact": "GEOS-Chem Support Team (geos-chem-support@g.harvard.edu)",
        "format": "NetCDF-4",
    },
}

# Drop rule (fixed before the build; identical in build and verify).
MAX_TOP_VALUE_FRACTION = 0.5  # one bit pattern may cover at most half the field
MIN_DISTINCT_VALUES = 1000    # and the field must hold >= 1000 distinct values
MIN_FIELD_MAX = 1e-28         # and must rise above the ~1e-30 numerical floor somewhere


# Fixed semantic exclusions (identical in build and verify, applied before the
# degeneracy rule).  The series is one quantity: constituent dry mixing ratios.
# Evidence: GEOS-Chem species_database.yml at tag 14.7.0-rc.0
# (run/shared/species_database.yml) FullName fields, and
# KPP/fullchem/CHANGELOG_fullchem.md for the SO4 production trackers.
CLOCK_TRACER = {"CLOCK"}
KPP_PROD_LOSS_TRACKERS = {
    "LBRO2H", "LBRO2N", "LCH4", "LCO", "LISOPNO3", "LISOPOH", "LOx", "LTRO2H", "LTRO2N",
    "LXRO2H", "LXRO2N", "PCO", "PH2O2", "POx", "PSO4", "PH2SO4", "LNRO2H", "LNRO2N", "PSO4AQ",
}
PROPORTIONAL_DUPLICATE = {"O2"}
SEMANTIC_CLASSES = {
    "clock_tracer": (CLOCK_TRACER,
                     "age-of-air clock tracer ('Clock tracer for diagnosing age of air', placeholder MW 1.0); "
                     "values are elapsed time, not a mixing ratio"),
    "kpp_prod_loss_tracker": (KPP_PROD_LOSS_TRACKERS,
                              "KPP prod/loss tracking species ('Dummy species to track ...' or the SO4-production "
                              "trackers PH2SO4/PSO4AQ); reaction amounts accumulated for diagnostics, not a constituent"),
    "proportional_duplicate": (PROPORTIONAL_DUPLICATE,
                               "O2 equals N2 / 3.72696890394 at every non-floor cell; N2 is kept"),
}
O2_N2_RATIO = 3.72696890394


def semantic_exclusions(spec: dict) -> dict[str, tuple[str, str]]:
    """species short name -> (class, reason)."""
    classes = spec.get("semantic_classes", SEMANTIC_CLASSES)
    out: dict[str, tuple[str, str]] = {}
    for klass, (names, reason) in classes.items():
        for name in names:
            require(name not in out, f"species {name} listed in two exclusion classes")
            out[name] = (klass, reason)
    return out


class RecipeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeError(message)


# ----------------------------------------------------------------- source
def open_source(path: Path, spec: dict):
    require(path.is_file(), f"missing source file {path}")
    size = path.stat().st_size
    require(size == spec["file_size"], f"source size {size} != pinned {spec['file_size']}")
    handle = path.open("rb")
    mm = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
    return handle, mm, H5File(mm)


def check_identity(f: H5File, spec: dict) -> dict:
    attrs = f.attributes(f.root_addr)
    for key, expected in spec["global_attrs"].items():
        require(attrs.get(key) == expected, f"global attribute {key}={attrs.get(key)!r} != {expected!r}")
    return attrs


def species_links(f: H5File, spec: dict, index: str) -> list[tuple[str, int]]:
    links = f.links(f.root_addr, index=index)
    require(len(links) == spec["root_links"], f"root group has {len(links)} links, expected {spec['root_links']}")
    species = sorted((name, addr) for name, addr in links.items() if name.startswith(SPECIES_PREFIX))
    require(len(species) == spec["species"], f"found {len(species)} species variables, expected {spec['species']}")
    lowered = {name.lower() for name, _ in species}
    require(len(lowered) == len(species), "species names collide case-insensitively")
    for name, _ in species:
        short = name[len(SPECIES_PREFIX):]
        require(short and all(ch.isalnum() for ch in short), f"unexpected species name {name!r}")
    return species


def check_species_header(f: H5File, name: str, addr: int, spec: dict) -> dict:
    messages = f.messages(addr)
    info = f.dataset(addr, messages)
    require(info["shape"] == spec["shape"], f"{name}: shape {info['shape']} != {spec['shape']}")
    require(bytes(info["datatype"]) == F64LE, f"{name}: datatype {bytes(info['datatype']).hex()} is not IEEE f64 LE")
    require(info["layout_class"] == 2, f"{name}: layout class {info['layout_class']} is not chunked")
    require(tuple(info["chunk_dims"]) == spec["chunk_dims"], f"{name}: chunk dims {info['chunk_dims']} != {spec['chunk_dims']}")
    filters = [(fid, values) for fid, _flags, values in info["filters"]]
    pipeline_ok = (
        len(filters) == 2
        and filters[0] == (h5lite.FILTER_SHUFFLE, (8,))
        and filters[1][0] == h5lite.FILTER_DEFLATE
        and len(filters[1][1]) == 1
        and 0 <= filters[1][1][0] <= 9
    )
    require(pipeline_ok, f"{name}: filter pipeline {info['filters']} is not exactly shuffle(8)+deflate "
            "(fletcher32 and any other filter are rejected)")
    fill = info["fill_value_raw"]
    require(fill is not None and len(fill) >= 2 and fill[0] in (2, 3), f"{name}: unexpected fill value message")
    if fill[0] == 3:
        require(not fill[1] & 0x20, f"{name}: a fill value is defined (out of policy)")
    attrs = f.attributes(addr, messages)
    short = name[len(SPECIES_PREFIX):]
    require(attrs.get("units") == "mol mol-1 dry", f"{name}: units {attrs.get('units')!r}")
    require(attrs.get("long_name") == f"Dry mixing ratio of species {short}", f"{name}: long_name {attrs.get('long_name')!r}")
    require(attrs.get("averaging_method") == "instantaneous", f"{name}: averaging_method {attrs.get('averaging_method')!r}")
    for banned in ("_FillValue", "missing_value", "scale_factor", "add_offset"):
        require(banned not in attrs, f"{name}: attribute {banned} present (out of policy)")
    return {"info": info, "attrs": attrs}


def chunk_plan(f: H5File, name: str, info: dict, spec: dict) -> list[tuple[int, int]]:
    """(address, stored size) per vertical level, in level order."""
    rank = len(spec["chunk_dims"])
    entries, _final = f.chunk_index(info["chunk_btree"], rank)
    levels = spec["shape"][1]
    require(len(entries) == levels, f"{name}: {len(entries)} chunks, expected {levels}")
    by_level: dict[int, tuple[int, int]] = {}
    for size, mask, offsets, chunk_addr in entries:
        require(mask == 0, f"{name}: chunk filter mask {mask:#x}")
        require(offsets[0] == 0 and offsets[2:] == (0,) * (rank - 2), f"{name}: unexpected chunk offsets {offsets}")
        level = offsets[1]
        require(0 <= level < levels and level not in by_level, f"{name}: bad or repeated chunk level {level}")
        require(size > 0 and chunk_addr + size <= len(f.raw), f"{name}: chunk at level {level} outside file")
        by_level[level] = (chunk_addr, size)
    return [by_level[level] for level in range(levels)]


def decode_species(f: H5File, name: str, addr: int, spec: dict, extents: list | None = None) -> tuple[bytes, dict]:
    header = check_species_header(f, name, addr, spec)
    info = header["info"]
    plan = chunk_plan(f, name, info, spec)
    level_bytes = spec["shape"][2] * spec["shape"][3] * 8
    out = bytearray()
    for chunk_addr, size in plan:
        out += h5lite.decode_chunk(f.raw[chunk_addr:chunk_addr + size], info["filters"], 0, 8, level_bytes)
        if extents is not None:
            extents.append((chunk_addr, size, name))
    expected = math.prod(spec["shape"]) * 8
    require(len(out) == expected, f"{name}: decoded {len(out)} bytes, expected {expected}")
    return bytes(out), header["attrs"]


def check_extents(extents: list) -> None:
    extents.sort()
    for (a, sa, na), (b, _sb, nb) in zip(extents, extents[1:]):
        require(a + sa <= b, f"chunk extents overlap: {na}@{a}+{sa} and {nb}@{b}")


# -------------------------------------------------------------- statistics
def field_stats(raw: bytes) -> dict:
    """Statistics of one field, computed from its stored float64 bit patterns."""
    require(len(raw) % 8 == 0 and raw, "field is empty or not a whole number of float64 values")
    words = array("Q")
    words.frombytes(raw)
    if sys.byteorder != "little":
        words.byteswap()
    counts = collections.Counter(words)
    keys = array("Q", counts.keys())
    values = array("d")
    values.frombytes(keys.tobytes())
    if sys.byteorder != "little":
        values.byteswap()
    nonfinite = sum(counts[k] for k in keys if (k >> 52) & 0x7FF == 0x7FF)
    nc_fill = counts.get(NC_FILL_DOUBLE_BITS, 0)
    finite = [v for v in values if math.isfinite(v)]
    top_bits, top_count = counts.most_common(1)[0]
    n = len(words)
    return {
        "value_count": n,
        "distinct_values": len(counts),
        "distinct_fraction": round(len(counts) / n, 6),
        "top_value": struct.unpack("<d", struct.pack("<Q", top_bits))[0],
        "top_value_fraction": round(top_count / n, 6),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "zero_values": counts.get(0, 0) + counts.get(1 << 63, 0),
        "negative_values": sum(counts[k] for k in keys if k >> 63 and k != 1 << 63 and (k >> 52) & 0x7FF != 0x7FF),
        "nonfinite_values": nonfinite,
        "nc_fill_values": nc_fill,
    }


def degenerate_reason(stats: dict, min_distinct: int = MIN_DISTINCT_VALUES) -> str:
    if stats["distinct_values"] == 1:
        return "constant"
    if stats["top_value_fraction"] > MAX_TOP_VALUE_FRACTION:
        return f"single-value-dominated (top value {stats['top_value']!r} covers {stats['top_value_fraction']:.4f})"
    if stats["max"] is None or stats["max"] < MIN_FIELD_MAX:
        return f"never above the numerical floor (max {stats['max']!r} < {MIN_FIELD_MAX!r})"
    if stats["distinct_values"] < min_distinct:
        return f"low diversity ({stats['distinct_values']} distinct values)"
    return ""


def check_missing_policy(name: str, stats: dict) -> None:
    require(stats["nonfinite_values"] == 0, f"{name}: {stats['nonfinite_values']} NaN/inf values (fatal)")
    require(stats["nc_fill_values"] == 0, f"{name}: {stats['nc_fill_values']} netCDF default-fill values (fatal)")


# -------------------------------------------------------------------- build
def sample_rel_path(name: str) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{name}.bin"


def build(source: Path, data_root: Path, spec: dict, index_path: Path, stats_dir: Path, log=print) -> dict:
    handle, mm, f = open_source(source, spec)
    try:
        attrs = check_identity(f, spec)
        species = species_links(f, spec, "name")
        sample_dir = data_root / f"samples/{DATASET_ID}/{SERIES_ID}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        for stale in sample_dir.glob("*.bin"):
            stale.unlink()
        exclusions = semantic_exclusions(spec)
        names = {name[len(SPECIES_PREFIX):] for name, _ in species}
        missing = sorted(set(exclusions) - names)
        require(not missing, f"excluded species not present in the file: {missing}")
        rows, table, dropped, excluded = [], [], [], []
        extents: list = []
        for name, addr in species:
            raw, var_attrs = decode_species(f, name, addr, spec, extents)
            stats = field_stats(raw)
            check_missing_policy(name, stats)
            short = name[len(SPECIES_PREFIX):]
            if short in exclusions:
                klass, reason = exclusions[short]
                decision = "excluded_semantic"
                excluded.append({"variable": name, "class": klass, "reason": reason})
            else:
                reason = degenerate_reason(stats, spec.get("min_distinct_values", MIN_DISTINCT_VALUES))
                klass = "degenerate" if reason else ""
                decision = "dropped_degenerate" if reason else "kept"
                if reason:
                    dropped.append({"variable": name, "reason": reason})
            table.append({"variable": name, **stats, "decision": decision, "class": klass, "reason": reason})
            log(f"{name} min={stats['min']!r} max={stats['max']!r} distinct={stats['distinct_values']} "
                f"({stats['distinct_fraction']:.4f}) top_frac={stats['top_value_fraction']:.4f} "
                f"{decision}{' (' + klass + ')' if klass else ''}")
            if decision != "kept":
                continue
            rel = sample_rel_path(name)
            tmp = data_root / (rel + ".part")
            tmp.write_bytes(raw)
            os.replace(tmp, data_root / rel)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": rel,
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(raw),
                "value_count": len(raw) // 8,
                "variable": name,
                "species": name[len(SPECIES_PREFIX):],
                "long_name": var_attrs["long_name"],
                "units": var_attrs["units"],
                "shape": list(spec["shape"]),
                "axes": ["time", "lev", "lat", "lon"],
                "order": "C",
                "model_time": "2019-01-01T00:00:00Z",
                "min": stats["min"],
                "max": stats["max"],
                "distinct_values": stats["distinct_values"],
                "top_value_fraction": stats["top_value_fraction"],
                "zero_values": stats["zero_values"],
                "negative_values": stats["negative_values"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_resource": SOURCE_RESOURCE,
            })
        check_extents(extents)
        require(rows, "no species survived the drop rule")
        index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = index_path.with_suffix(".jsonl.part")
        with tmp.open("w", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, sort_keys=True) + "\n")
        os.replace(tmp, index_path)
        stats_dir.mkdir(parents=True, exist_ok=True)
        columns = ["variable", "decision", "class", "value_count", "distinct_values", "distinct_fraction", "top_value",
                   "top_value_fraction", "min", "max", "zero_values", "negative_values", "nonfinite_values",
                   "nc_fill_values", "reason"]
        with (stats_dir / "species_stats.tsv").open("w", encoding="utf-8") as out:
            out.write("\t".join(columns) + "\n")
            for entry in table:
                out.write("\t".join(repr(entry[c]) if isinstance(entry[c], float) else str(entry[c]) for c in columns) + "\n")
        summary = {
            "dataset_id": DATASET_ID,
            "source": str(source.name),
            "global_attributes": {k: attrs.get(k) for k in spec["global_attrs"]},
            "species_in_file": len(species),
            "samples": len(rows),
            "excluded_semantic": excluded,
            "dropped_degenerate": dropped,
            "total_size_bytes": sum(r["sample_size_bytes"] for r in rows),
            "total_values": sum(r["value_count"] for r in rows),
            "drop_rule": {"max_top_value_fraction": MAX_TOP_VALUE_FRACTION, "min_distinct_values": spec.get("min_distinct_values", MIN_DISTINCT_VALUES), "min_field_max": MIN_FIELD_MAX},
            "checked_metadata_blocks": f.checked_blocks,
        }
        (stats_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log(f"build summary: species={len(species)} samples={len(rows)} excluded={len(excluded)} dropped={len(dropped)} "
            f"bytes={summary['total_size_bytes']} values={summary['total_values']}")
        return summary
    finally:
        del f
        mm.close()
        handle.close()


# ------------------------------------------------------------------- verify
def verify_unshuffle(data: bytes, element_size: int) -> bytes:
    """Independent byte-plane interleave (memoryview based)."""
    count = len(data) // element_size
    require(count * element_size == len(data), "shuffled chunk is not a whole number of elements")
    view = memoryview(data)
    out = bytearray(len(data))
    for plane in range(element_size):
        out[plane::element_size] = view[plane * count:(plane + 1) * count]
    return bytes(out)


def verify_decode(f: H5File, name: str, addr: int, spec: dict) -> bytes:
    import zlib

    header = check_species_header(f, name, addr, spec)
    plan = chunk_plan(f, name, header["info"], spec)
    level_bytes = spec["shape"][2] * spec["shape"][3] * 8
    parts = []
    for chunk_addr, size in plan:
        d = zlib.decompressobj()
        inflated = d.decompress(f.raw[chunk_addr:chunk_addr + size]) + d.flush()
        require(d.eof and not d.unused_data and len(inflated) == level_bytes, f"{name}: bad deflate chunk at {chunk_addr}")
        parts.append(verify_unshuffle(inflated, 8))
    return b"".join(parts)


def verify(source: Path, data_root: Path, spec: dict, index_path: Path, stats_dir: Path,
           manifest_path: Path | None, log=print) -> dict:
    require(index_path.is_file(), f"missing index {index_path}")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(rows, "index is empty")
    by_variable = {}
    for row in rows:
        require(row["dataset_id"] == DATASET_ID and row["series_id"] == SERIES_ID, f"bad ids in row {row.get('variable')}")
        require((row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) == ("float", 64, "little", 8),
                f"bad dtype fields in row {row.get('variable')}")
        require(row["variable"] not in by_variable, f"duplicate index row {row['variable']}")
        require(row["sample_path"] == sample_rel_path(row["variable"]), f"unexpected sample path {row['sample_path']}")
        by_variable[row["variable"]] = row
    exclusions = semantic_exclusions(spec)
    for variable in by_variable:
        require(variable[len(SPECIES_PREFIX):] not in exclusions,
                f"semantically excluded species {variable} appears in the index")
    sample_dir = data_root / f"samples/{DATASET_ID}/{SERIES_ID}"
    on_disk = {p.name for p in sample_dir.iterdir()}
    expected_files = {Path(r["sample_path"]).name for r in rows}
    require(on_disk == expected_files, f"sample directory holds unexpected files: {sorted(on_disk ^ expected_files)[:5]}")
    for short in exclusions:
        require(f"{SPECIES_PREFIX}{short}.bin" not in on_disk, f"excluded species {short} has a sample file")

    handle, mm, f = open_source(source, spec)
    try:
        check_identity(f, spec)
        species = species_links(f, spec, "creation_order")
        require(species == species_links(f, spec, "name"), "name and creation-order link indexes disagree")
        names = {name[len(SPECIES_PREFIX):] for name, _ in species}
        missing = sorted(set(exclusions) - names)
        require(not missing, f"excluded species not present in the file: {missing}")
        hashes = set()
        kept = dropped = excluded = 0
        expected_values = math.prod(spec["shape"])
        ratio_fields: dict[str, bytes] = {}
        for name, addr in species:
            decoded = verify_decode(f, name, addr, spec)
            row = by_variable.get(name)
            short = name[len(SPECIES_PREFIX):]
            if short in ("O2", "N2"):
                ratio_fields[short] = decoded
            if short in exclusions:
                require(row is None, f"excluded species {name} has an index row")
                check_missing_policy(name, field_stats(decoded))
                excluded += 1
                continue
            if row is None:
                stats = field_stats(decoded)
                check_missing_policy(name, stats)
                require(degenerate_reason(stats, spec.get("min_distinct_values", MIN_DISTINCT_VALUES)) != "", f"{name}: dropped but passes the drop rule")
                dropped += 1
                continue
            sample = (data_root / row["sample_path"]).read_bytes()
            require(sample == decoded, f"{name}: sample bytes differ from the re-decoded field")
            require(len(sample) == row["sample_size_bytes"] == expected_values * 8 and row["value_count"] == expected_values,
                    f"{name}: size fields mismatch")
            digest = hashlib.sha256(sample).hexdigest()
            require(digest == row["sha256"], f"{name}: sha256 mismatch")
            require(digest not in hashes, f"{name}: duplicate sample content")
            hashes.add(digest)
            # Recompute statistics from the sample file itself with plain arrays.
            vals = array("d")
            vals.frombytes(sample)
            if sys.byteorder != "little":
                vals.byteswap()
            require(all(math.isfinite(v) for v in vals), f"{name}: non-finite value in sample")
            require(9.969209968386869e36 not in vals, f"{name}: netCDF default fill in sample")
            lo, hi = min(vals), max(vals)
            require(lo == row["min"] and hi == row["max"], f"{name}: min/max {lo!r}/{hi!r} != index {row['min']!r}/{row['max']!r}")
            require(lo != hi, f"{name}: constant sample")
            words = array("Q")
            words.frombytes(sample)
            counts = collections.Counter(words)
            top = max(counts.values())
            require(len(counts) == row["distinct_values"], f"{name}: distinct count mismatch")
            require(round(top / len(words), 6) == row["top_value_fraction"], f"{name}: top fraction mismatch")
            require(hi >= MIN_FIELD_MAX, f"{name}: kept sample never rises above the numerical floor")
            require(top / len(words) <= MAX_TOP_VALUE_FRACTION and len(counts) >= spec.get("min_distinct_values", MIN_DISTINCT_VALUES),
                    f"{name}: kept sample violates the drop rule")
            kept += 1
        require(kept == len(rows), f"index has {len(rows)} rows but {kept} species matched")
        if "O2" in exclusions and spec.get("check_o2_ratio", True):
            check_o2_n2_ratio(ratio_fields)
    finally:
        del f
        mm.close()
        handle.close()

    total = sum(r["sample_size_bytes"] for r in rows)
    counts_sorted = sorted(r["value_count"] for r in rows)
    median = counts_sorted[len(counts_sorted) // 2]
    require(total <= 1_000_000_000, f"primary bytes {total} exceed the 1 GB cap")
    if spec.get("check_floor", True):
        require(median >= 1000 and sum(counts_sorted) >= 10_000, "below the acceptance floor")
    stats_path = stats_dir / "ingest_stats.json"
    require(stats_path.is_file(), f"missing {stats_path}")
    summary = json.loads(stats_path.read_text(encoding="utf-8"))
    require(summary["samples"] == kept and len(summary["dropped_degenerate"]) == dropped
            and len(summary["excluded_semantic"]) == excluded, "ingest_stats.json disagrees with verify")
    if manifest_path is not None:
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
        require(len(series) == 1, "manifest must declare the species series exactly once")
        require(series[0]["sample_count"] == kept, f"manifest sample_count {series[0]['sample_count']} != {kept}")
        require(series[0]["total_size_bytes"] == total, f"manifest total_size_bytes {series[0]['total_size_bytes']} != {total}")
    log(f"verify ok: samples={kept} excluded={excluded} dropped={dropped} bytes={total} median_values={median}")
    return {"samples": kept, "excluded": excluded, "dropped": dropped, "bytes": total}


def check_o2_n2_ratio(fields: dict[str, bytes]) -> None:
    """Re-establish the evidence for excluding O2: N2/O2 is one constant off the floor."""
    require("O2" in fields and "N2" in fields, "O2/N2 fields missing for the proportionality check")
    o2, n2 = array("d"), array("d")
    o2.frombytes(fields["O2"])
    n2.frombytes(fields["N2"])
    if sys.byteorder != "little":
        o2.byteswap()
        n2.byteswap()
    ratios = [b / a for a, b in zip(o2, n2) if a > 1e-20 and b > 1e-20]
    require(len(ratios) > len(o2) // 2, "too few non-floor cells for the O2/N2 check")
    lo, hi = min(ratios), max(ratios)
    require(abs(lo / O2_N2_RATIO - 1) < 1e-9 and abs(hi / O2_N2_RATIO - 1) < 1e-9,
            f"N2/O2 ratio range {lo!r}..{hi!r} is not the constant {O2_N2_RATIO}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_dir = args.data_root / "filtered" / DATASET_ID
    try:
        if args.command == "build":
            build(args.source, args.data_root, REAL_SPEC, index_path, stats_dir)
        else:
            verify(args.source, args.data_root, REAL_SPEC, index_path, stats_dir, args.manifest)
    except (RecipeError, H5Error) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
