#!/usr/bin/env python3
"""Build / verify the CESM2 CMIP6 historical daily precipitation flux samples.

Source: one pinned NetCDF4 file from the anonymous ``esgf-world`` S3 bucket,
``pr_day_CESM2_historical_r1i1p1f1_gn_19400101-19491231.nc`` (v20190401).

Each of the 3650 time steps of the ``pr`` variable (time, lat, lon) =
(3650, 192, 288), little-endian float32, is stored as one HDF5 chunk
(1, 192, 288) with shuffle(4) + deflate.  Build inflates and unshuffles every
chunk and writes the stored float32 values unchanged, one raw little-endian
file per daily field, in (lat, lon) row-major order.

Subcommands:
  check-source  structural validation used by download.sh (no output files)
  build         decode all fields, write samples + index + summary
  verify        independently re-derive every sample and check the index,
                statistics, missing-value policy and manifest totals

Pure standard library; works from local files only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import mmap
import os
import struct
import sys
from array import array
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import H5Error  # noqa: E402

DATASET_ID = "cmip6_cesm2_historical_daily_precip_f32"
SERIES_ID = "pr_day_f32"
F32LE = bytes.fromhex("11201f000400000000002000170800177f000000")
F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
FILL_F32_BYTES = struct.pack("<f", 1e20)
FILL_F32 = struct.unpack("<f", FILL_F32_BYTES)[0]
NOLEAP_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

SPEC = {
    "file_size": 663390696,
    "n_time": 3650,
    "n_lat": 192,
    "n_lon": 288,
    "time_first": 707735.0,          # days since 0001-01-01, noleap -> 1940-01-01
    "date_first": "19400101",
    "date_last": "19491231",
    "min_distinct_values": 1000,
    "check_coords": True,
    "global_attrs": {
        "source_id": "CESM2",
        "institution_id": "NCAR",
        "experiment_id": "historical",
        "activity_id": "CMIP",
        "variant_label": "r1i1p1f1",
        "variable_id": "pr",
        "table_id": "day",
        "frequency": "day",
        "grid_label": "gn",
        "mip_era": "CMIP6",
        "tracking_id": "hdl:21.14100/c9b7ee29-8ac2-46d4-9e5c-b309b1ef0999",
    },
    "license_needle": "licensed under a Creative Commons Attribution-",
}


class RecipeError(ValueError):
    """Semantic problem with the source or the derived output."""


def require(condition: bool, what: str) -> None:
    if not condition:
        raise RecipeError(what)


# ------------------------------------------------------------ calendar
def noleap_date(days: float) -> str:
    """YYYYMMDD of an integral 'days since 0001-01-01' value, noleap calendar."""
    require(days == int(days) and days >= 0, f"time value {days!r} is not a non-negative integer")
    n = int(days)
    year = 1 + n // 365
    doy = n % 365
    month = 0
    while doy >= NOLEAP_MONTH_DAYS[month]:
        doy -= NOLEAP_MONTH_DAYS[month]
        month += 1
    return f"{year:04d}{month + 1:02d}{doy + 1:02d}"


# ------------------------------------------------------------ HDF5 helpers
def open_raw(path: Path):
    fh = path.open("rb")
    size = os.fstat(fh.fileno()).st_size
    if size == 0:
        raise RecipeError(f"{path} is empty")
    return fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)


def attr_scalar(value):
    if isinstance(value, list):
        require(len(value) == 1, f"attribute holds {len(value)} values, expected 1")
        return value[0]
    return value


def read_leading_chunked(f: h5lite.H5File, info: dict, element_size: int) -> bytes:
    """Whole dataset (C order) when only the leading axis is split into chunks."""
    shape = info["shape"]
    require(info["layout_class"] == 2, "dataset is not chunked")
    cd = info["chunk_dims"]
    require(len(cd) == len(shape) + 1 and cd[-1] == element_size, f"chunk dims {cd} vs element size {element_size}")
    require(tuple(cd[1:-1]) == tuple(shape[1:]), f"chunk dims {cd} split a non-leading axis of {shape}")
    entries, _final = f.chunk_index(info["chunk_btree"], len(shape) + 1)
    per_chunk = element_size
    for dim in cd[:-1]:
        per_chunk *= dim
    by_offset = {}
    for size, mask, offsets, addr in entries:
        require(all(o == 0 for o in offsets[1:]), f"unexpected chunk offsets {offsets}")
        require(offsets[0] % cd[0] == 0, f"misaligned chunk offset {offsets}")
        require(offsets[0] not in by_offset, f"duplicate chunk {offsets}")
        by_offset[offsets[0]] = (size, mask, addr)
    require(sorted(by_offset) == list(range(0, shape[0], cd[0])), "chunk index is incomplete")
    out = bytearray()
    for start in sorted(by_offset):
        size, mask, addr = by_offset[start]
        out += h5lite.decode_chunk(f.raw[addr:addr + size], info["filters"], mask, element_size, per_chunk)
    total = element_size
    for dim in shape:
        total *= dim
    return bytes(out[:total])


def check_filters(filters, element_size: int) -> None:
    ids = [fid for fid, _flags, _values in filters]
    require(ids == [h5lite.FILTER_SHUFFLE, h5lite.FILTER_DEFLATE], f"filter pipeline {filters} is not shuffle+deflate")
    require(tuple(filters[0][2]) == (element_size,), f"shuffle element size {filters[0][2]} != {element_size}")


def open_source(path: Path, spec: dict, link_index: str = "name", log=print) -> dict:
    """Open and validate the source file; return handles and decoded metadata."""
    fh, raw = open_raw(path)
    require(len(raw) == spec["file_size"], f"file size {len(raw)} != pinned {spec['file_size']}")
    f = h5lite.H5File(raw)
    links = f.links(f.root_addr, link_index)
    for name in ("pr", "time", "time_bnds", "lat", "lon"):
        require(name in links, f"root group lacks {name!r}")
    gattrs = f.attributes(f.root_addr)
    for key, want in spec["global_attrs"].items():
        require(gattrs.get(key) == want, f"global attribute {key}={gattrs.get(key)!r}, expected {want!r}")
    license_text = gattrs.get("license", "")
    require(isinstance(license_text, str) and spec["license_needle"] in license_text,
            f"global license attribute unexpected: {license_text!r}")

    nt, ny, nx = spec["n_time"], spec["n_lat"], spec["n_lon"]
    pr_msgs = f.messages(links["pr"])
    pr = f.dataset(links["pr"], pr_msgs)
    require(pr["shape"] == (nt, ny, nx), f"pr shape {pr['shape']} != {(nt, ny, nx)}")
    require(pr["datatype"] == F32LE, f"pr datatype {pr['datatype'].hex()} is not little-endian IEEE float32")
    require(pr["layout_class"] == 2 and tuple(pr["chunk_dims"]) == (1, ny, nx, 4),
            f"pr chunking {pr.get('chunk_dims')} is not one (1,{ny},{nx}) chunk per day")
    check_filters(pr["filters"], 4)
    fill = pr["fill_value_raw"]
    require(fill is not None and fill[0] == 2 and fill[3] == 1 and fill[4:8] == b"\x04\x00\x00\x00"
            and fill[8:12] == FILL_F32_BYTES, f"pr fill value message unexpected: {fill.hex() if fill else None}")
    pattrs = f.attributes(links["pr"], pr_msgs)
    require(pattrs.get("units") == "kg m-2 s-1", f"pr units {pattrs.get('units')!r}")
    require(pattrs.get("standard_name") == "precipitation_flux", "pr standard_name")
    require(pattrs.get("cell_methods") == "area: time: mean", f"pr cell_methods {pattrs.get('cell_methods')!r}")
    require(attr_scalar(pattrs.get("_FillValue")) == FILL_F32, f"pr _FillValue {pattrs.get('_FillValue')!r}")
    require(abs(attr_scalar(pattrs.get("missing_value")) - 1e20) <= 1e13, f"pr missing_value {pattrs.get('missing_value')!r}")

    t_msgs = f.messages(links["time"])
    t_info = f.dataset(links["time"], t_msgs)
    require(t_info["shape"] == (nt,) and t_info["datatype"] == F64LE, "time is not float64 (n_time,)")
    t_attrs = f.attributes(links["time"], t_msgs)
    require(t_attrs.get("units") == "days since 0001-01-01 00:00:00", f"time units {t_attrs.get('units')!r}")
    require(t_attrs.get("calendar") == "noleap", f"time calendar {t_attrs.get('calendar')!r}")
    check_filters(t_info["filters"], 8)
    times = list(struct.unpack(f"<{nt}d", read_leading_chunked(f, t_info, 8)))
    for i, t in enumerate(times):
        require(t == spec["time_first"] + i, f"time[{i}]={t} is not time_first+{i}")
    b_info = f.dataset(links["time_bnds"])
    require(b_info["shape"] == (nt, 2) and b_info["datatype"] == F64LE, "time_bnds is not float64 (n_time, 2)")
    check_filters(b_info["filters"], 8)
    bnds = struct.unpack(f"<{2 * nt}d", read_leading_chunked(f, b_info, 8))
    for i in range(nt):
        require(bnds[2 * i + 1] - bnds[2 * i] == 1.0, f"time_bnds[{i}] does not span one day")
        require(bnds[2 * i + 1] == times[i], f"time_bnds[{i}] upper bound != time[{i}]")
    lats = lons = None
    if spec["check_coords"]:
        lat_info = f.dataset(links["lat"])
        lon_info = f.dataset(links["lon"])
        require(lat_info["shape"] == (ny,) and lon_info["shape"] == (nx,), "lat/lon shapes")
        lats = struct.unpack(f"<{ny}d", read_leading_chunked(f, lat_info, 8))
        lons = struct.unpack(f"<{nx}d", read_leading_chunked(f, lon_info, 8))
        require(lats[0] == -90.0 and lats[-1] == 90.0 and all(b > a for a, b in zip(lats, lats[1:])),
                "lat is not increasing from -90 to 90")
        require(all(abs(lons[i] - 1.25 * i) < 1e-9 for i in range(nx)), "lon is not 0..358.75 step 1.25")

    entries, _final = f.chunk_index(pr["chunk_btree"], 4)
    chunks = {}
    for size, mask, offsets, addr in entries:
        require(offsets[1:] == (0, 0, 0), f"pr chunk offsets {offsets} split the grid")
        require(0 <= offsets[0] < nt and offsets[0] not in chunks, f"pr chunk offset {offsets} duplicate/out of range")
        require(mask == 0, f"pr chunk {offsets[0]} has filter mask {mask:#x}")
        require(0 < size and addr + size <= len(raw), f"pr chunk {offsets[0]} extent exceeds file")
        chunks[offsets[0]] = (addr, size)
    require(len(chunks) == nt, f"pr chunk index holds {len(chunks)} chunks, expected {nt}")
    dates = [noleap_date(t) for t in times]
    require(dates[0] == spec["date_first"] and dates[-1] == spec["date_last"], f"date span {dates[0]}..{dates[-1]}")
    log(f"source ok: {path.name} bytes={len(raw)} pr={pr['shape']} chunks={len(chunks)} "
        f"filters={pr['filters']} dates={dates[0]}..{dates[-1]} checked_blocks={f.checked_blocks}")
    return {"fh": fh, "raw": raw, "f": f, "pr": pr, "chunks": chunks, "times": times, "bnds": bnds,
            "dates": dates, "global_attrs": gattrs, "license": license_text}


def decode_day(src: dict, index: int, spec: dict) -> bytes:
    addr, size = src["chunks"][index]
    nbytes = 4 * spec["n_lat"] * spec["n_lon"]
    return h5lite.decode_chunk(src["raw"][addr:addr + size], src["pr"]["filters"], 0, 4, nbytes)


def field_stats(data: bytes, spec: dict) -> dict:
    """Statistics of one stored float32 field; raises on the missing-value policy."""
    values = array("f")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = set(values)
    for v in distinct:
        if v != v or math.isinf(v):
            raise RecipeError(f"non-finite value {v!r} in field")
        if abs(v) >= 1e19:
            raise RecipeError(f"fill/missing value {v!r} (1e20 sentinel) in field")
    stats = {
        "min": min(distinct),
        "max": max(distinct),
        "zero_values": values.count(0.0),
        "negative_values": sum(1 for v in values if v < 0.0),
        "distinct_values": len(distinct),
    }
    if stats["distinct_values"] < spec["min_distinct_values"]:
        raise RecipeError(f"degenerate field: only {stats['distinct_values']} distinct values")
    if stats["max"] <= 0.0:
        raise RecipeError("degenerate field: no positive precipitation anywhere")
    return stats


def sample_rel_path(date: str) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/pr_day_{date}.bin"


# ------------------------------------------------------------ build
def build(source: Path, data_root: Path, spec: dict = SPEC, log=print) -> dict:
    src = open_source(source, spec, "name", log)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*"):
        stale.unlink()
    index_dir = data_root / "index" / DATASET_ID
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir = data_root / "filtered" / DATASET_ID
    filtered_dir.mkdir(parents=True, exist_ok=True)
    nt, ny, nx = spec["n_time"], spec["n_lat"], spec["n_lon"]
    rows = []
    totals = {"zero_values": 0, "negative_values": 0, "bytes": 0}
    gmin, gmax = math.inf, -math.inf
    for i in range(nt):
        data = decode_day(src, i, spec)
        stats = field_stats(data, spec)
        rel = sample_rel_path(src["dates"][i])
        out = data_root / rel
        tmp = out.with_suffix(".bin.tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(data),
            "value_count": ny * nx,
            "shape": [ny, nx],
            "axes": ["lat", "lon"],
            "record_index": i,
            "time_days_since_0001_01_01_noleap": src["times"][i],
            "time_bnds": [src["bnds"][2 * i], src["bnds"][2 * i + 1]],
            "date_label": src["dates"][i],
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        row.update(stats)
        rows.append(row)
        totals["zero_values"] += stats["zero_values"]
        totals["negative_values"] += stats["negative_values"]
        totals["bytes"] += len(data)
        gmin, gmax = min(gmin, stats["min"]), max(gmax, stats["max"])
        if (i + 1) % 365 == 0 or i + 1 == nt:
            log(f"  decoded {i + 1}/{nt} fields (last {src['dates'][i]})")
    index_path = index_dir / "samples.jsonl"
    tmp_index = index_path.with_suffix(".jsonl.tmp")
    with tmp_index.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.replace(index_path)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_file": source.name,
        "samples": len(rows),
        "values": len(rows) * ny * nx,
        "total_size_bytes": totals["bytes"],
        "zero_values": totals["zero_values"],
        "negative_values": totals["negative_values"],
        "zero_fraction": totals["zero_values"] / (len(rows) * ny * nx),
        "min": gmin,
        "max": gmax,
        "date_first": src["dates"][0],
        "date_last": src["dates"][-1],
        "license_attribute": src["license"],
        "global_attrs": {k: src["global_attrs"].get(k) for k in sorted(spec["global_attrs"])},
    }
    (filtered_dir / "build_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    src["raw"].close()
    src["fh"].close()
    log(f"build ok: samples={summary['samples']} values={summary['values']} bytes={summary['total_size_bytes']} "
        f"zero_fraction={summary['zero_fraction']:.6f} negatives={summary['negative_values']} "
        f"min={gmin!r} max={gmax!r}")
    return summary


# ------------------------------------------------------------ verify
def verify_unshuffle4(data: bytes) -> bytes:
    """Independent per-element inverse of the 4-byte HDF5 shuffle (slow; spot checks only)."""
    n = len(data) // 4
    out = bytearray(4 * n)
    for k in range(n):
        out[4 * k] = data[k]
        out[4 * k + 1] = data[n + k]
        out[4 * k + 2] = data[2 * n + k]
        out[4 * k + 3] = data[3 * n + k]
    return bytes(out) + data[4 * n:]


def verify_date(days: float) -> str:
    """Independent noleap date: cumulative day-of-year table lookup."""
    n = int(days)
    if n != days:
        raise RecipeError(f"non-integral time {days}")
    starts = [0]
    for m in NOLEAP_MONTH_DAYS:
        starts.append(starts[-1] + m)
    year, doy = divmod(n, 365)
    month = max(m for m in range(12) if starts[m] <= doy)
    return "%04d%02d%02d" % (year + 1, month + 1, doy - starts[month] + 1)


def verify_stats(data: bytes, spec: dict) -> dict:
    """Recompute field statistics from the bit patterns (different path from build)."""
    n = len(data) // 4
    bits = array("I")
    bits.frombytes(data)
    vals = array("f")
    vals.frombytes(data)
    if sys.byteorder != "little":
        bits.byteswap()
        vals.byteswap()
    exp_all_ones = [b for b in set(bits) if (b & 0x7F800000) == 0x7F800000]
    if exp_all_ones:
        raise RecipeError("NaN/Inf bit pattern present")
    fill_bits = struct.unpack("<I", FILL_F32_BYTES)[0]
    if fill_bits in bits or (fill_bits | 0x80000000) in bits:
        raise RecipeError("1e20 fill bit pattern present")
    ordered = sorted(vals)
    if abs(ordered[0]) >= 1e19 or abs(ordered[-1]) >= 1e19:
        raise RecipeError("value of fill magnitude present")
    negatives = 0
    while negatives < n and ordered[negatives] < 0.0:
        negatives += 1
    zeros = 0
    while negatives + zeros < n and ordered[negatives + zeros] == 0.0:
        zeros += 1
    distinct = 1 + sum(1 for a, b in zip(ordered, ordered[1:]) if a != b)
    if distinct < spec["min_distinct_values"] or ordered[-1] <= 0.0:
        raise RecipeError(f"degenerate field (distinct={distinct}, max={ordered[-1]})")
    return {"min": ordered[0], "max": ordered[-1], "zero_values": zeros, "negative_values": negatives,
            "distinct_values": distinct}


def verify(source: Path, data_root: Path, manifest: Path | None, spec: dict = SPEC, log=print) -> dict:
    nt, ny, nx = spec["n_time"], spec["n_lat"], spec["n_lon"]
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(rows) == nt, f"index has {len(rows)} rows, expected {nt}")
    sample_root = data_root / "samples" / DATASET_ID
    require(sorted(p.name for p in sample_root.iterdir()) == [SERIES_ID], "unexpected series directories")
    on_disk = sorted(p.name for p in (sample_root / SERIES_ID).iterdir())
    require(on_disk == sorted(Path(r["sample_path"]).name for r in rows), "sample files and index rows differ")
    # Independent link resolution: creation-order index instead of the name index.
    src = open_source(source, spec, "creation_order", log)
    spot = set(range(0, nt, 365)) | {nt - 1}
    total_bytes = 0
    for i, row in enumerate(rows):
        date = verify_date(src["times"][i])
        expect = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 32,
            "endianness": "little", "element_size_bytes": 4, "sample_size_bytes": 4 * ny * nx,
            "value_count": ny * nx, "shape": [ny, nx], "axes": ["lat", "lon"], "record_index": i,
            "date_label": date, "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/pr_day_{date}.bin",
            "time_days_since_0001_01_01_noleap": src["times"][i],
            "time_bnds": [src["bnds"][2 * i], src["bnds"][2 * i + 1]],
        }
        for key, value in expect.items():
            require(row.get(key) == value, f"row {i} field {key}={row.get(key)!r}, expected {value!r}")
        stored = (data_root / row["sample_path"]).read_bytes()
        require(len(stored) == 4 * ny * nx, f"row {i} sample has {len(stored)} bytes")
        derived = decode_day(src, i, spec)
        require(stored == derived, f"row {i} sample bytes differ from the re-decoded chunk")
        if i in spot:
            addr, size = src["chunks"][i]
            import zlib
            independent = verify_unshuffle4(zlib.decompress(bytes(src["raw"][addr:addr + size])))
            require(independent == stored, f"row {i} independent unshuffle disagrees")
        digest = hashlib.sha256(stored).hexdigest()
        require(row.get("sha256") == digest, f"row {i} sha256 mismatch")
        stats = verify_stats(stored, spec)
        for key, value in stats.items():
            require(row.get(key) == value, f"row {i} {key}={row.get(key)!r}, recomputed {value!r}")
        total_bytes += len(stored)
        if (i + 1) % 365 == 0 or i + 1 == nt:
            log(f"  verified {i + 1}/{nt} fields (last {date})")
    require(len({r["sha256"] for r in rows}) == nt, "duplicate daily fields")
    if manifest is not None:
        import tomllib
        doc = tomllib.loads(manifest.read_text(encoding="utf-8"))
        require(doc.get("dataset_id") == DATASET_ID, "manifest dataset_id")
        series = [s for s in doc.get("series", []) if s.get("id") == SERIES_ID]
        require(len(series) == 1, "manifest lacks the series")
        require(series[0].get("sample_count") == nt, f"manifest sample_count {series[0].get('sample_count')} != {nt}")
        require(series[0].get("total_size_bytes") == total_bytes,
                f"manifest total_size_bytes {series[0].get('total_size_bytes')} != {total_bytes}")
        res = [r for r in doc.get("resources", []) if r.get("local_path", "").endswith(source.name)]
        require(len(res) == 1 and res[0].get("size_bytes") == spec["file_size"], "manifest resource size")
    src["raw"].close()
    src["fh"].close()
    log(f"verify ok: samples={nt} bytes={total_bytes} spot_unshuffle_checks={len(spot)}")
    return {"samples": nt, "total_size_bytes": total_bytes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check-source", "build", "verify"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check-source":
            src = open_source(args.source, SPEC)
            # Decode the first and last day as a payload sanity check.
            for i in (0, SPEC["n_time"] - 1):
                stats = field_stats(decode_day(src, i, SPEC), SPEC)
                print(f"  day {src['dates'][i]}: min={stats['min']!r} max={stats['max']!r} "
                      f"distinct={stats['distinct_values']} zeros={stats['zero_values']}")
            print(f"license attribute: {src['license']}")
        elif args.command == "build":
            build(args.source, args.data_root)
        else:
            verify(args.source, args.data_root, args.manifest)
    except (RecipeError, H5Error) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
