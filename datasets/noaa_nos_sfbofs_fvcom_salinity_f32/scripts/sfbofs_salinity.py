#!/usr/bin/env python3
"""Decode SFBOFS (FVCOM) nowcast salinity fields from byte ranges of the
NOAA NOS OFS NetCDF4/HDF5 ``fields.n003`` files.

The download stage fetches only these ranges of each 56,605,561-byte object:

* ``head``        bytes [0, 262144): superblock, root group, fractal heap,
                  v2 B-trees and every object header the decode needs
* ``sal_btree``   a 4096-byte window at the salinity chunk B-tree node
* ``time_btree``  a 4096-byte window at the time chunk B-tree node
* ``xy``          the contiguous ``x`` and ``y`` node coordinates (mesh pin)
* ``sal_cK``      each raw (unfiltered) salinity chunk, K = 0..3
* ``time_c0``     the single time chunk

Every offset is derived by parsing the previously fetched ranges, so
``build`` and ``verify`` re-derive the whole plan from ``head.bin`` and never
trust a stored offset table.  Subcommands:

  plan-meta / plan-data   print "<name>\\t<start>\\t<length>" range plans
  check-response          validate a 206 response header block
  check-file              full semantic validation of one fetched file
  build / verify          emit / independently re-check the samples
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import struct
import sys
from array import array
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fvcom_h5 as h5  # noqa: E402

DATASET_ID = "noaa_nos_sfbofs_fvcom_salinity_f32"
SERIES_ID = "sfbofs_fields_n003_salinity_f32"
BASE_URL = "https://noaa-nos-ofs-pds.s3.amazonaws.com"
SOURCES_SHA256 = "dcc50d8ab0d9e8b750ddcac2e0a4e61ba1b325fe2ddf30a92db489c7cfa924e2"

F32_LE = bytes.fromhex("11201f000400000000002000170800177f000000")
F64_LE_PREFIX = bytes.fromhex("11203f0008000000")
NC_FILL_F32_BITS = 0x7CF00000  # netCDF default float fill, 9.96921e36
EPOCH = dt.datetime(2013, 1, 1, tzinfo=dt.timezone.utc)

REAL_SPEC = {
    "file_size": 56605561,
    "head_len": 262144,
    "btree_window": 4096,
    "n_siglay": 20,
    "n_node": 54120,
    "sal_chunk": (1, 10, 27060),
    "time_chunk": 512,
    "n_links": 56,
    "links_sha256": "5341a0e01b00b62fa88dab0097c0f3af0f283a33ec9b7d3e5d93429971a6de28",
    "xy_sha256": "05d1047e1ef7b87df594787553692b7a62e4f636312f6a2359dd95a9ceb1ac08",
    "globals": {"title": "SFBOFS", "source": "FVCOM_4.4.7", "institution": "School for Marine Science and Technology"},
    "forcing_attr": "Surface_Heat_Forcing",
    "time_units": "seconds since 2013-01-01 00:00:00",
    "sal_attrs": {"long_name": "salinity", "standard_name": "sea_water_salinity", "units": "1e-3", "location": "node"},
    "bounds": (-1.0, 45.0),
    "min_distinct": 100000,
    "max_modal_fraction": 0.5,
}

DECODE_ERRORS = (h5.H5Error, ValueError, KeyError, IndexError, struct.error)


class RecipeError(ValueError):
    pass


def fail(msg: str) -> None:
    raise RecipeError(msg)


# ----------------------------------------------------------------- sources
def read_sources(path: Path, check_pin: bool = True) -> list[dict]:
    raw = path.read_bytes()
    if check_pin and hashlib.sha256(raw).hexdigest() != SOURCES_SHA256:
        fail(f"sources.tsv SHA-256 {hashlib.sha256(raw).hexdigest()} != pinned {SOURCES_SHA256}")
    lines = raw.decode().splitlines()
    if lines[0].split("\t") != ["date", "key", "size_bytes", "etag"]:
        fail("unexpected sources.tsv header")
    rows = []
    for line in lines[1:]:
        date, key, size, etag = line.split("\t")
        ymd = date.replace("-", "")
        if key != f"sfbofs/netcdf/{ymd[:4]}/{ymd[4:6]}/{ymd[6:]}/sfbofs.t03z.{ymd}.fields.n003.nc":
            fail(f"key {key} does not match the t03z fields.n003 pattern for {date}")
        rows.append({"date": date, "key": key, "size": int(size), "etag": etag})
    if check_pin:
        start = dt.date(2025, 1, 1)
        want = [(start + dt.timedelta(days=7 * k)).isoformat() for k in range(52)]
        if [r["date"] for r in rows] != want:
            fail("sources.tsv dates are not the 52-date weekly lattice from 2025-01-01")
        if any(r["size"] != REAL_SPEC["file_size"] for r in rows):
            fail("unexpected object size in sources.tsv")
    return rows


# ------------------------------------------------------------- HDF5 decode
def expected_time(date: str) -> float:
    day = dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc)
    return float((day - EPOCH).total_seconds())


def load_segments(fdir: Path, spec: dict, names: list[tuple[str, int, int]]) -> list[tuple[int, bytes]]:
    segs = []
    for name, start, length in names:
        path = fdir / f"{name}.bin"
        if not path.is_file():
            fail(f"missing segment {path}")
        data = path.read_bytes()
        if len(data) != length:
            fail(f"segment {path} has {len(data)} bytes, expected {length}")
        segs.append((start, data))
    return segs


def head_plan(spec: dict) -> list[tuple[str, int, int]]:
    return [("head", 0, min(spec["head_len"], spec["file_size"]))]


def inspect_meta(f: h5.H5File, spec: dict, date: str) -> dict:
    """Validate the root group and object headers; return addresses."""
    if f.superblock_version != 0:
        fail(f"superblock version {f.superblock_version} != 0")
    links = f.links(f.root_addr, "name")
    names = "\n".join(sorted(links)).encode()
    if len(links) != spec["n_links"] or hashlib.sha256(names).hexdigest() != spec["links_sha256"]:
        fail(f"root link set differs from the pinned SFBOFS fields layout ({len(links)} links)")
    glob = f.attributes(f.root_addr)
    for key, value in spec["globals"].items():
        if glob.get(key) != value:
            fail(f"global attribute {key}={glob.get(key)!r} != {value!r}")
    ymd = date.replace("-", "")
    forcing = glob.get(spec["forcing_attr"])
    if not isinstance(forcing, str) or f"sfbofs.t03z.{ymd}." not in forcing:
        fail(f"global {spec['forcing_attr']} does not name the {ymd} t03z cycle")

    sal = f.dataset(links["salinity"])
    if sal["shape"] != (1, spec["n_siglay"], spec["n_node"]):
        fail(f"salinity shape {sal['shape']}")
    if sal["datatype"] != F32_LE:
        fail(f"salinity datatype {sal['datatype'].hex()} is not IEEE float32 LE")
    if sal["filters"]:
        fail(f"salinity has a filter pipeline {sal['filters']} (expected raw chunks)")
    if sal["layout_class"] != 2 or tuple(sal["chunk_dims"]) != tuple(spec["sal_chunk"]) + (4,):
        fail(f"salinity layout class {sal['layout_class']} chunk {sal.get('chunk_dims')}")
    sattrs = f.attributes(links["salinity"])
    for key, value in spec["sal_attrs"].items():
        if sattrs.get(key) != value:
            fail(f"salinity attribute {key}={sattrs.get(key)!r} != {value!r}")
    if "_FillValue" in sattrs or "scale_factor" in sattrs or "add_offset" in sattrs:
        fail("salinity carries _FillValue/scale_factor/add_offset attributes (out of pinned scope)")

    siglay = f.dataset(links["siglay"])
    if siglay["shape"] != (spec["n_siglay"], spec["n_node"]):
        fail(f"siglay shape {siglay['shape']}")

    tm = f.dataset(links["time"])
    if tm["shape"] != (1,) or tm["datatype"][:8] != F64_LE_PREFIX or tm["filters"] or tm["layout_class"] != 2:
        fail("time variable is not one unfiltered chunked float64")
    if tuple(tm["chunk_dims"]) != (spec["time_chunk"], 8):
        fail(f"time chunk dims {tm['chunk_dims']}")
    if f.attributes(links["time"]).get("units") != spec["time_units"]:
        fail("time units changed")

    xy = []
    for name in ("x", "y"):
        info = f.dataset(links[name])
        if info["shape"] != (spec["n_node"],) or info["datatype"] != F32_LE or info["layout_class"] != 1:
            fail(f"{name} is not a contiguous float32 node vector")
        addr, size = struct.unpack_from("<QQ", info["layout_raw"], 2)
        if addr == h5.UNDEF or size != 4 * spec["n_node"]:
            fail(f"{name} storage {addr} {size}")
        xy.append((addr, size))
    return {"sal_btree": sal["chunk_btree"], "time_btree": tm["chunk_btree"], "xy": xy}


def plan_meta_ranges(meta: dict, spec: dict) -> list[tuple[str, int, int]]:
    size = spec["file_size"]
    out = []
    for name in ("sal_btree", "time_btree"):
        addr = meta[name]
        if addr == h5.UNDEF or addr >= size:
            fail(f"{name} address {addr} invalid")
        out.append((name, addr, min(spec["btree_window"], size - addr)))
    (xa, xs), (ya, ys) = meta["xy"]
    if xa + xs == ya:
        out.append(("xy", xa, xs + ys))
    else:
        out.append(("x", xa, xs))
        out.append(("y", ya, ys))
    return out


def sal_chunk_grid(spec: dict) -> list[tuple[int, int]]:
    _t, cl, cn = spec["sal_chunk"]
    return [(l0, n0) for l0 in range(0, spec["n_siglay"], cl) for n0 in range(0, spec["n_node"], cn)]


def inspect_chunks(f: h5.H5File, meta: dict, spec: dict) -> dict:
    _t, cl, cn = spec["sal_chunk"]
    entries, _final = f.chunk_index(meta["sal_btree"], 4)
    grid = sal_chunk_grid(spec)
    by_offset = {}
    for size, mask, offsets, addr in entries:
        if mask != 0:
            fail(f"salinity chunk {offsets} has filter mask {mask}")
        if size != cl * cn * 4:
            fail(f"salinity chunk {offsets} stored size {size} != {cl * cn * 4}")
        if offsets[0] != 0 or offsets[3] != 0:
            fail(f"salinity chunk offsets {offsets}")
        key = (offsets[1], offsets[2])
        if key in by_offset:
            fail(f"duplicate salinity chunk {key}")
        if addr == h5.UNDEF or addr + size > spec["file_size"]:
            fail(f"salinity chunk {key} address {addr} invalid")
        by_offset[key] = addr
    if sorted(by_offset) != sorted(grid):
        fail(f"salinity chunk grid {sorted(by_offset)} != {grid}")
    tentries, _tfinal = f.chunk_index(meta["time_btree"], 2)
    if len(tentries) != 1:
        fail(f"time has {len(tentries)} chunks")
    tsize, tmask, toff, taddr = tentries[0]
    if tmask != 0 or toff != (0, 0) or tsize != spec["time_chunk"] * 8:
        fail(f"time chunk {tentries[0]}")
    return {"sal": [(k, by_offset[k]) for k in grid], "time": (taddr, tsize)}


def plan_data_ranges(chunks: dict, spec: dict) -> list[tuple[str, int, int]]:
    _t, cl, cn = spec["sal_chunk"]
    out = [(f"sal_c{i}", addr, cl * cn * 4) for i, (_key, addr) in enumerate(chunks["sal"])]
    out.append(("time_c0", chunks["time"][0], chunks["time"][1]))
    return out


def open_file(fdir: Path, spec: dict, date: str, stage: str):
    """Re-derive the range plan from head.bin and open a Sparse view."""
    plan = head_plan(spec)
    view = h5.Sparse(load_segments(fdir, spec, plan), spec["file_size"])
    f = h5.H5File(view)
    meta = inspect_meta(f, spec, date)
    mplan = plan_meta_ranges(meta, spec)
    if stage == "meta":
        return f, meta, mplan, None, None
    plan = plan + mplan
    view = h5.Sparse(load_segments(fdir, spec, plan), spec["file_size"])
    f = h5.H5File(view)
    chunks = inspect_chunks(f, meta, spec)
    dplan = plan_data_ranges(chunks, spec)
    if stage == "chunks":
        return f, meta, mplan, chunks, dplan
    view = h5.Sparse(load_segments(fdir, spec, plan + dplan), spec["file_size"])
    f = h5.H5File(view)
    return f, meta, mplan, chunks, dplan


def read_xy(f: h5.H5File, meta: dict) -> bytes:
    return b"".join(bytes(f.raw[a:a + s]) for a, s in meta["xy"])


def read_time(f: h5.H5File, chunks: dict) -> float:
    addr, _size = chunks["time"]
    return struct.unpack("<d", bytes(f.raw[addr:addr + 8]))[0]


def assemble_by_chunk(f: h5.H5File, chunks: dict, spec: dict) -> bytes:
    """Build route: copy each chunk's layer rows into the (siglay, node) array."""
    _t, cl, cn = spec["sal_chunk"]
    n_l, n_n = spec["n_siglay"], spec["n_node"]
    out = bytearray(n_l * n_n * 4)
    for (l0, n0), addr in chunks["sal"]:
        data = bytes(f.raw[addr:addr + cl * cn * 4])
        for li in range(cl):
            layer = l0 + li
            if layer >= n_l:
                break  # edge chunk padding (never present in the pinned files)
            width = min(cn, n_n - n0)
            src = li * cn * 4
            dst = (layer * n_n + n0) * 4
            out[dst:dst + width * 4] = data[src:src + width * 4]
    return bytes(out)


def assemble_by_layer(f: h5.H5File, chunks: dict, spec: dict) -> bytes:
    """Verify route: walk output layers and node blocks, looking chunks up by key."""
    _t, cl, cn = spec["sal_chunk"]
    n_l, n_n = spec["n_siglay"], spec["n_node"]
    table = dict(chunks["sal"])
    parts = []
    for layer in range(n_l):
        for n0 in range(0, n_n, cn):
            addr = table[(layer - layer % cl, n0)]
            width = min(cn, n_n - n0)
            row = (layer % cl) * cn
            parts.append(bytes(f.raw[addr + 4 * row: addr + 4 * (row + width)]))
    return b"".join(parts)


def decode_file(fdir: Path, spec: dict, date: str, route: str = "chunk") -> tuple[bytes, dict]:
    f, meta, mplan, chunks, dplan = open_file(fdir, spec, date, "data")
    xy = read_xy(f, meta)
    xy_sha = hashlib.sha256(xy).hexdigest()
    if xy_sha != spec["xy_sha256"]:
        fail(f"x/y mesh coordinates SHA-256 {xy_sha} != pinned {spec['xy_sha256']} (different mesh)")
    tval = read_time(f, chunks)
    if tval != expected_time(date):
        fail(f"time {tval} s != expected {expected_time(date)} s ({date} 00:00 UTC)")
    payload = assemble_by_chunk(f, chunks, spec) if route == "chunk" else assemble_by_layer(f, chunks, spec)
    info = {
        "valid_time_utc": (EPOCH + dt.timedelta(seconds=tval)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_seconds_since_2013": tval,
        "ranges": [(n, s, l) for n, s, l in head_plan(spec) + mplan + dplan],
    }
    return payload, info


# --------------------------------------------------------------- profiles
def profile(payload: bytes, spec: dict) -> dict:
    n_l, n_n = spec["n_siglay"], spec["n_node"]
    if len(payload) != n_l * n_n * 4:
        fail(f"sample has {len(payload)} bytes, expected {n_l * n_n * 4}")
    vals = array("f")
    vals.frombytes(payload)
    if sys.byteorder != "little":
        vals.byteswap()
    bits = array("I")
    bits.frombytes(payload)
    if sys.byteorder != "little":
        bits.byteswap()
    fill = bits.count(NC_FILL_F32_BITS)
    if fill:
        fail(f"{fill} netCDF fill values (9.96921e36) present")
    lo, hi = spec["bounds"]
    total = 0.0
    for v in vals:
        if not math.isfinite(v):
            fail("non-finite salinity value")
        if not lo < v < hi:
            fail(f"salinity value {v} outside sanity bounds {spec['bounds']}")
        total += v
    counts = Counter(bits)
    modal_bits, modal_n = counts.most_common(1)[0]
    distinct = len(counts)
    if distinct < spec["min_distinct"]:
        fail(f"only {distinct} distinct values (< {spec['min_distinct']})")
    if modal_n / len(vals) > spec["max_modal_fraction"]:
        fail(f"modal value covers {modal_n / len(vals):.3f} of the sample")
    layer_bytes = n_n * 4
    layers = [payload[i * layer_bytes:(i + 1) * layer_bytes] for i in range(n_l)]
    identical_adjacent = sum(1 for a, b in zip(layers, layers[1:]) if a == b)
    if identical_adjacent == n_l - 1:
        fail("all sigma layers are identical (vertically degenerate)")
    return {
        "min": min(vals),
        "max": max(vals),
        "mean": total / len(vals),
        "distinct_count": distinct,
        "modal_value": struct.unpack("<f", struct.pack("<I", modal_bits))[0],
        "modal_fraction": modal_n / len(vals),
        "zero_count": bits.count(0) + bits.count(0x80000000),
        "identical_adjacent_layers": identical_adjacent,
        "surface_layer_mean": sum(vals[:n_n]) / n_n,
        "bottom_layer_mean": sum(vals[(n_l - 1) * n_n:]) / n_n,
    }


# -------------------------------------------------------------- commands
def check_response(headers: Path, start: int, end: int, total: int, etag: str) -> None:
    blocks, cur = [], []
    for line in headers.read_text("latin-1").splitlines():
        line = line.strip()
        if line.upper().startswith("HTTP/"):
            cur = [line]
            blocks.append(cur)
        elif line and cur:
            cur.append(line)
    if not blocks:
        fail("no HTTP response headers")
    status, *fields = blocks[-1]
    hdr = {}
    for field in fields:
        if ":" in field:
            k, v = field.split(":", 1)
            hdr[k.strip().lower()] = v.strip()
    if status.split()[1] != "206":
        fail(f"status {status!r} (expected 206)")
    if hdr.get("content-range") != f"bytes {start}-{end}/{total}":
        fail(f"Content-Range {hdr.get('content-range')!r} != bytes {start}-{end}/{total}")
    if hdr.get("etag", "").strip('"') != etag:
        fail(f"ETag {hdr.get('etag')!r} != pinned {etag}")
    if int(hdr.get("content-length", "-1")) != end - start + 1:
        fail(f"Content-Length {hdr.get('content-length')!r} != {end - start + 1}")


def cmd_plan(args) -> None:
    spec = REAL_SPEC
    stage = "meta" if args.cmd == "plan-meta" else "chunks"
    _f, _meta, mplan, _chunks, dplan = open_file(Path(args.dir), spec, args.date, stage)
    for name, start, length in (mplan if stage == "meta" else dplan):
        print(f"{name}\t{start}\t{length}")


def cmd_check_file(args) -> None:
    payload, info = decode_file(Path(args.dir), REAL_SPEC, args.date)
    prof = profile(payload, REAL_SPEC)
    print(f"check_file=ok date={args.date} valid={info['valid_time_utc']} min={prof['min']:.4f} "
          f"max={prof['max']:.4f} distinct={prof['distinct_count']} modal_fraction={prof['modal_fraction']:.4f}")


def sample_name(date: str) -> str:
    return f"sfbofs_t03z_{date.replace('-', '')}_fields_n003_salinity.f32le"


def index_row(row: dict, payload: bytes, prof: dict, info: dict, rel: str) -> dict:
    spec = REAL_SPEC
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": rel,
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": len(payload),
        "value_count": len(payload) // 4,
        "shape": [spec["n_siglay"], spec["n_node"]],
        "axes": ["siglay", "node"],
        "date": row["date"],
        "valid_time_utc": info["valid_time_utc"],
        "source_url": f"{BASE_URL}/{row['key']}",
        "source_etag": row["etag"],
        "source_size_bytes": row["size"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        **{k: prof[k] for k in ("min", "max", "mean", "distinct_count", "modal_value", "modal_fraction",
                                "zero_count", "identical_adjacent_layers", "surface_layer_mean",
                                "bottom_layer_mean")},
    }


def cmd_build(args) -> None:
    rows = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    out_dir = Path(args.samples_dir) / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.iterdir():
        if stale.name not in {sample_name(r["date"]) for r in rows}:
            stale.unlink()
    index = []
    for row in rows:
        payload, info = decode_file(downloads / row["date"], REAL_SPEC, row["date"], "chunk")
        prof = profile(payload, REAL_SPEC)
        dest = out_dir / sample_name(row["date"])
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(payload)
        os.replace(tmp, dest)
        index.append(index_row(row, payload, prof, info, str(dest.relative_to(data_root))))
        print(f"sample date={row['date']} bytes={len(payload)} min={prof['min']:.4f} max={prof['max']:.4f} "
              f"distinct={prof['distinct_count']} modal={prof['modal_value']:.4f}@{prof['modal_fraction']:.4f}")
    shas = [r["sha256"] for r in index]
    if len(set(shas)) != len(shas):
        fail("duplicate samples")
    idx = Path(args.index)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with open(idx.with_suffix(".part"), "w") as fh:
        for r in index:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(idx.with_suffix(".part"), idx)
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(index),
        "total_size_bytes": sum(r["sample_size_bytes"] for r in index),
        "value_count": sum(r["value_count"] for r in index),
        "global_min": min(r["min"] for r in index),
        "global_max": max(r["max"] for r in index),
        "max_modal_fraction": max(r["modal_fraction"] for r in index),
        "total_zero_count": sum(r["zero_count"] for r in index),
    }
    st = Path(args.stats)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print("build_stats " + json.dumps(stats, sort_keys=True))


def manifest_series(manifest: Path) -> dict:
    import tomllib
    data = tomllib.loads(manifest.read_text())
    series = [s for s in data["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest must declare exactly one series with the expected id")
    return series[0]


def cmd_verify(args) -> None:
    rows = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    out_dir = Path(args.samples_dir) / SERIES_ID
    index = [json.loads(line) for line in Path(args.index).read_text().splitlines() if line.strip()]
    if len(index) != len(rows):
        fail(f"index has {len(index)} rows, sources {len(rows)}")
    expected_files = sorted(sample_name(r["date"]) for r in rows)
    if sorted(p.name for p in out_dir.iterdir()) != expected_files:
        fail("samples directory does not hold exactly the expected sample files")
    total_bytes = 0
    shas = set()
    for row, rec in zip(rows, index):
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{sample_name(row['date'])}"
        if rec["sample_path"] != rel or rec["date"] != row["date"]:
            fail(f"index row mismatch for {row['date']}")
        for key, value in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                           ("bit_width", 32), ("endianness", "little"), ("element_size_bytes", 4),
                           ("source_etag", row["etag"])):
            if rec.get(key) != value:
                fail(f"index field {key}={rec.get(key)!r} for {row['date']}")
        sample = (data_root / rel).read_bytes()
        if len(sample) != rec["sample_size_bytes"] or len(sample) // 4 != rec["value_count"]:
            fail(f"size mismatch for {rel}")
        sha = hashlib.sha256(sample).hexdigest()
        if sha != rec["sha256"]:
            fail(f"sha256 mismatch for {rel}")
        shas.add(sha)
        # Independent re-decode via the layer-walk assembly route.
        redo, info = decode_file(downloads / row["date"], REAL_SPEC, row["date"], "layer")
        if redo != sample:
            fail(f"re-decoded salinity differs from sample {rel}")
        if info["valid_time_utc"] != rec["valid_time_utc"]:
            fail(f"valid time mismatch for {rel}")
        prof = profile(sample, REAL_SPEC)
        for key in ("min", "max", "distinct_count", "modal_value", "modal_fraction", "zero_count",
                    "identical_adjacent_layers"):
            if prof[key] != rec[key]:
                fail(f"{key} recomputed {prof[key]!r} != index {rec[key]!r} for {rel}")
        if abs(prof["mean"] - rec["mean"]) > 1e-9:
            fail(f"mean mismatch for {rel}")
        total_bytes += len(sample)
    if len(shas) != len(rows):
        fail("duplicate samples")
    series = manifest_series(Path(args.manifest))
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
             f"!= realized {len(rows)}/{total_bytes}")
    values = sorted(r["value_count"] for r in index)
    print(f"verify=ok samples={len(rows)} bytes={total_bytes} values={sum(values)} "
          f"median_values={values[len(values) // 2]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan-meta", "plan-data", "check-file"):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True)
        p.add_argument("--date", required=True)
    p = sub.add_parser("check-response")
    p.add_argument("--headers", required=True)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--total", type=int, required=True)
    p.add_argument("--etag", required=True)
    p = sub.add_parser("check-sources")
    p.add_argument("--sources", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--downloads", required=True)
        p.add_argument("--samples-dir", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--data-root", required=True)
        if name == "build":
            p.add_argument("--stats", required=True)
        else:
            p.add_argument("--manifest", required=True)
    args = ap.parse_args()
    try:
        if args.cmd in ("plan-meta", "plan-data"):
            cmd_plan(args)
        elif args.cmd == "check-file":
            cmd_check_file(args)
        elif args.cmd == "check-response":
            check_response(Path(args.headers), args.start, args.end, args.total, args.etag)
        elif args.cmd == "check-sources":
            print(f"sources=ok rows={len(read_sources(Path(args.sources)))}")
        elif args.cmd == "build":
            cmd_build(args)
        else:
            cmd_verify(args)
    except DECODE_ERRORS as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
