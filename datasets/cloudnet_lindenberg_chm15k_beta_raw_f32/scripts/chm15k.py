#!/usr/bin/env python3
"""Decode, build and verify Cloudnet Lindenberg CHM15k beta_raw samples.

Pure standard library.  One sample per pinned daily Cloudnet "lidar" product
file: the complete ``beta_raw`` (time x range) float32 matrix exactly as
stored (little-endian IEEE binary32, time-major), with no masking, scaling or
reordering.

Subcommands
  selftest        synthetic HDF5 round trip (scripts/selftest_chm15k.py)
  check-meta      validate one per-file API record against sources.tsv
  check-file      validate one downloaded .nc (size, sha256, full decode)
  build           decode every pinned file, write samples + index
  verify          independently re-derive every sample and the index

Decode routes
  build   chunk list by recursive v1 B-tree descent (h5lite.chunk_index),
          zlib.decompress, unshuffle by strided slice assignment
  verify  chunk list by walking the leaf level's right-sibling chain,
          streamed zlib.decompressobj, unshuffle by zipping byte lanes
"""
from __future__ import annotations

import argparse
import array
import hashlib
import itertools
import json
import math
import os
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import H5Error, H5File, UNDEF  # noqa: E402

DATASET_ID = "cloudnet_lindenberg_chm15k_beta_raw_f32"
SERIES_ID = "lindenberg_chm15k_beta_raw_f32"
SOURCES_SHA256 = "3a8c2f032a512c417511ef3b73e00606eaaf2ec4696f79ddd4b1fead9282c7e1"

INSTRUMENT_UUID = "cdf99c53-6bd0-4146-be2a-604cf1164c30"
INSTRUMENT_PID = "https://hdl.handle.net/21.12132/3.cdf99c536bd04146"
SERIAL = "CHM100110"
SITE = "lindenberg"
PRODUCT = "lidar"

# IEEE binary32 little-endian datatype message as written by HDF5 1.14 / netCDF 4.9
F32_LE = bytes.fromhex("11201f000400000000002000170800177f000000")
FILL_F32 = struct.unpack("<f", struct.pack("<f", 9.969209968386869e36))[0]
FILL_BITS = struct.unpack("<I", struct.pack("<f", FILL_F32))[0]  # 0x7CF00000

REAL_SPEC = {
    "n_range": 1535,
    "range_step_m": 9.99,
    "range_tol_m": 0.02,
    "min_time": 5700,
    "max_time": 5800,
    "dt_s": 15.0,
    "dt_tol_s": 0.05,
    "max_fill_fraction": 0.01,
    "value_bound": 1.0,
    "min_distinct": 100_000,
    "distinct_stride": 8,
    "neg_fraction": (0.05, 0.95),
    "globals": {
        "serial_number": SERIAL,
        "instrument_pid": INSTRUMENT_PID,
        "cloudnet_file_type": "lidar",
        "source": "Lufft CHM15k",
        "location": "Lindenberg",
        "title": "CHM15k ceilometer from Lindenberg",
    },
    "beta_raw_attrs": {
        "units": "sr-1 m-1",
        "long_name": "Attenuated backscatter coefficient",
        "comment": "Non-screened attenuated backscatter coefficient.",
    },
}

DECODE_ERRORS = (H5Error, ValueError, KeyError, IndexError, struct.error, zlib.error, TypeError)


class RecipeError(ValueError):
    pass


def fail(msg: str) -> None:
    raise RecipeError(msg)


# ---------------------------------------------------------------- sources
def load_sources(path: Path, check_pin: bool = True) -> list[dict]:
    raw = path.read_bytes()
    if check_pin and SOURCES_SHA256 != "__SOURCES_SHA256__":
        actual = hashlib.sha256(raw).hexdigest()
        if actual != SOURCES_SHA256:
            fail(f"sources.tsv sha256 {actual} != pinned {SOURCES_SHA256}")
    lines = raw.decode("utf-8").splitlines()
    header = lines[0].split("\t")
    if header != ["date", "uuid", "filename", "size", "sha256", "cloudnetpy_version"]:
        fail(f"unexpected sources.tsv header {header}")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        date, uuid, filename, size, sha, version = line.split("\t")
        if filename != f"{date.replace('-', '')}_lindenberg_chm15k_cdf99c53.nc":
            fail(f"unexpected filename {filename} for {date}")
        rows.append({"date": date, "uuid": uuid, "filename": filename, "size": int(size),
                     "sha256": sha, "cloudnetpy_version": version})
    dates = [r["date"] for r in rows]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        fail("sources.tsv dates must be unique and sorted")
    if len(rows) != 24:
        fail(f"expected 24 pinned files, found {len(rows)}")
    return rows


def nc_path(downloads: Path, row: dict) -> Path:
    return downloads / "nc" / row["filename"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------ chunk lists
def chunks_descent(f: H5File, btree: int, rank: int) -> list[tuple[int, int, tuple[int, ...], int]]:
    entries, _final = f.chunk_index(btree, rank)
    return entries


def chunks_siblings(f: H5File, btree: int, rank: int) -> list[tuple[int, int, tuple[int, ...], int]]:
    """Leftmost descent to level 0, then follow right-sibling pointers."""
    raw = f.raw
    key_size = 8 + 8 * rank
    node = btree
    root_level = None
    while True:
        if raw[node:node + 4] != b"TREE" or raw[node + 4] != 1:
            raise H5Error(f"not a raw-data chunk B-tree node at {node}")
        level = raw[node + 5]
        if root_level is None:
            root_level = level
        if level == 0:
            break
        used = struct.unpack_from("<H", raw, node + 6)[0]
        if used == 0:
            raise H5Error("empty internal B-tree node")
        node = struct.unpack_from("<Q", raw, node + 24 + key_size)[0]
    out = []
    left_expected = UNDEF
    seen = set()
    while node != UNDEF:
        if node in seen:
            raise H5Error("B-tree sibling loop")
        seen.add(node)
        if raw[node:node + 4] != b"TREE" or raw[node + 4] != 1 or raw[node + 5] != 0:
            raise H5Error(f"sibling at {node} is not a level-0 chunk node")
        used, left, right = struct.unpack_from("<HQQ", raw, node + 6)
        if left != left_expected:
            raise H5Error("B-tree left-sibling pointer mismatch")
        pos = node + 24
        for _ in range(used):
            size, mask = struct.unpack_from("<II", raw, pos)
            offsets = struct.unpack_from(f"<{rank}Q", raw, pos + 8)
            child = struct.unpack_from("<Q", raw, pos + key_size)[0]
            out.append((size, mask, offsets, child))
            pos += key_size + 8
        left_expected = node
        node = right
    return out


# ------------------------------------------------------- filters/unshuffle
def inflate_whole(buf: bytes) -> bytes:
    return zlib.decompress(buf)


def inflate_streamed(buf: bytes) -> bytes:
    d = zlib.decompressobj()
    parts = []
    for i in range(0, len(buf), 1 << 20):
        parts.append(d.decompress(buf[i:i + (1 << 20)]))
    parts.append(d.flush())
    if not d.eof or d.unused_data:
        raise zlib.error("deflate stream not cleanly terminated")
    return b"".join(parts)


def unshuffle_slices(buf: bytes, size: int = 4) -> bytes:
    n = len(buf) // size
    out = bytearray(buf)  # leftover tail bytes (len % size) stay in place
    for j in range(size):
        out[j:n * size:size] = buf[j * n:(j + 1) * n]
    return bytes(out)


def unshuffle_lanes(buf: bytes, size: int = 4) -> bytes:
    n = len(buf) // size
    lanes = [bytes(buf[j * n:(j + 1) * n]) for j in range(size)]
    # gather: element k is (lane0[k], lane1[k], ...), i.e. a zip of the lanes
    body = bytes(itertools.chain.from_iterable(zip(*lanes)))
    return body + bytes(buf[n * size:])


# ----------------------------------------------------------------- decode
def _assemble(f: H5File, ds: dict, route: str) -> bytes:
    shape = ds["shape"]
    rank = len(shape)
    if ds.get("layout_class") != 2:
        fail("dataset is not chunked")
    cdims = tuple(ds["chunk_dims"])
    if len(cdims) != rank + 1 or cdims[-1] != 4:
        fail(f"unexpected chunk dims {cdims}")
    cdims = cdims[:rank]
    filters = ds["filters"]
    if [fid for fid, _fl, _cd in filters] != [2, 1] or tuple(filters[0][2]) != (4,):
        fail(f"filter pipeline {filters} is not [shuffle(4), deflate]")
    if route == "descent":
        entries = chunks_descent(f, ds["chunk_btree"], rank + 1)
        inflate, unshuffle = inflate_whole, unshuffle_slices
    else:
        entries = chunks_siblings(f, ds["chunk_btree"], rank + 1)
        inflate, unshuffle = inflate_streamed, unshuffle_lanes
    expected_chunks = 1
    for s, c in zip(shape, cdims):
        expected_chunks *= -(-s // c)
    if len(entries) != expected_chunks:
        fail(f"{len(entries)} chunks, expected {expected_chunks}")
    seen = set()
    total = 1
    for s in shape:
        total *= s
    out = bytearray(total * 4)
    chunk_values = 1
    for c in cdims:
        chunk_values *= c
    raw = f.raw
    for size, mask, offsets, addr in entries:
        offs = tuple(offsets[:rank])
        if offsets[rank] != 0 or mask != 0:
            fail(f"chunk {offsets} has element offset or filter mask set")
        if offs in seen:
            fail(f"duplicate chunk {offs}")
        seen.add(offs)
        for o, s, c in zip(offs, shape, cdims):
            if o % c or o >= s:
                fail(f"misaligned/out-of-range chunk {offs}")
        if addr + size > len(raw):
            fail("chunk exceeds file")
        data = unshuffle(inflate(raw[addr:addr + size]))
        if len(data) != chunk_values * 4:
            fail(f"chunk {offs} inflated to {len(data)} bytes, expected {chunk_values * 4}")
        if rank == 1:
            m = min(cdims[0], shape[0] - offs[0])
            out[offs[0] * 4:(offs[0] + m) * 4] = data[:m * 4]
        elif rank == 2:
            r0, c0 = offs
            m = min(cdims[1], shape[1] - c0)
            for r in range(min(cdims[0], shape[0] - r0)):
                src = r * cdims[1] * 4
                dst = ((r0 + r) * shape[1] + c0) * 4
                out[dst:dst + m * 4] = data[src:src + m * 4]
        else:
            fail("rank > 2 is out of scope")
    return bytes(out)


def _f32_values(b: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(b)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def decode_file(raw: bytes, row: dict, spec: dict, route: str) -> dict:
    """Decode and validate one daily file; returns beta_raw bytes plus metadata."""
    f = H5File(raw)
    links = f.links(f.root_addr)
    for name in ("beta_raw", "time", "range"):
        if name not in links:
            fail(f"root group lacks {name}")
    g = f.attributes(f.root_addr)
    for key, value in spec["globals"].items():
        if g.get(key) != value:
            fail(f"global {key}={g.get(key)!r}, expected {value!r}")
    if g.get("file_uuid") != row["uuid"]:
        fail(f"file_uuid {g.get('file_uuid')!r} != pinned {row['uuid']}")
    y, m, d = row["date"].split("-")
    if (g.get("year"), g.get("month"), g.get("day")) != (y, m, d):
        fail(f"file date {g.get('year')}-{g.get('month')}-{g.get('day')} != {row['date']}")
    if g.get("cloudnetpy_version") != row["cloudnetpy_version"]:
        fail(f"cloudnetpy_version {g.get('cloudnetpy_version')!r} != pinned {row['cloudnetpy_version']}")

    datasets = {}
    for name in ("beta_raw", "time", "range"):
        ds = f.dataset(links[name])
        if ds["datatype"] != F32_LE:
            fail(f"{name} datatype {ds['datatype'].hex()} is not IEEE float32 LE")
        datasets[name] = ds
    n_time, n_range = datasets["beta_raw"]["shape"] if len(datasets["beta_raw"]["shape"]) == 2 else (None, None)
    if n_time is None:
        fail("beta_raw is not rank 2")
    if n_range != spec["n_range"] or not spec["min_time"] <= n_time <= spec["max_time"]:
        fail(f"beta_raw shape {(n_time, n_range)} outside spec")
    if datasets["time"]["shape"] != (n_time,) or datasets["range"]["shape"] != (n_range,):
        fail("time/range axes disagree with beta_raw shape")
    attrs = f.attributes(links["beta_raw"])
    for key, value in spec["beta_raw_attrs"].items():
        if attrs.get(key) != value:
            fail(f"beta_raw {key}={attrs.get(key)!r}, expected {value!r}")
    fv = attrs.get("_FillValue")
    if not isinstance(fv, list) or len(fv) != 1 or fv[0] != FILL_F32:
        fail(f"beta_raw _FillValue {fv!r} is not the netCDF default float fill")
    tattrs = f.attributes(links["time"])
    if tattrs.get("units") != f"hours since {row['date']} 00:00:00 +00:00":
        fail(f"time units {tattrs.get('units')!r}")

    t = _f32_values(_assemble(f, datasets["time"], route))
    rng = _f32_values(_assemble(f, datasets["range"], route))
    for i, v in enumerate(rng):
        if abs(v - spec["range_step_m"] * (i + 1)) > spec["range_tol_m"]:
            fail(f"range[{i}]={v} off the {spec['range_step_m']} m lattice")
    if not all(0.0 <= v < 24.0 for v in t):
        fail("time outside [0, 24) h")
    dts = [(t[i + 1] - t[i]) * 3600.0 for i in range(len(t) - 1)]
    if min(dts) <= 0:
        fail("time not strictly increasing")
    med = sorted(dts)[len(dts) // 2]
    if abs(med - spec["dt_s"]) > spec["dt_tol_s"]:
        fail(f"median profile interval {med:.3f} s != {spec['dt_s']} s")
    beta = _assemble(f, datasets["beta_raw"], route)
    if len(beta) != n_time * n_range * 4:
        fail("beta_raw byte count mismatch")
    bds = datasets["beta_raw"]
    return {
        "beta": beta,
        "n_time": n_time,
        "n_range": n_range,
        "time_first_h": t[0],
        "time_last_h": t[-1],
        "median_dt_s": round(med, 3),
        "max_gap_s": round(max(dts), 3),
        "range_sha256": hashlib.sha256(rng.tobytes()).hexdigest(),
        "chunk_dims": list(bds["chunk_dims"][:2]),
        "deflate_level": bds["filters"][1][2][0] if bds["filters"][1][2] else None,
        "h5_checked_blocks": f.checked_blocks,
    }


# ------------------------------------------------------------------ stats
def sample_stats(beta: bytes, n_time: int, n_range: int, spec: dict) -> dict:
    a = _f32_values(beta)
    u = array.array("I")
    u.frombytes(beta)
    if sys.byteorder != "little":
        u.byteswap()
    n = len(a)
    fill = u.count(FILL_BITS)
    bound = spec["value_bound"]
    outside = sum(1 for v in a if not -bound <= v <= bound)  # NaN fails both comparisons
    if outside != fill:
        fail(f"{outside - fill} non-finite or out-of-bound (|v| > {bound}) non-fill values")
    if fill > spec["max_fill_fraction"] * n:
        fail(f"fill fraction {fill / n:.4f} exceeds {spec['max_fill_fraction']}")
    vals = a if fill == 0 else array.array("f", (v for v in a if -bound <= v <= bound))
    vmin, vmax = min(vals), max(vals)
    mean = math.fsum(vals) / len(vals)
    var = math.fsum((v - mean) * (v - mean) for v in vals) / len(vals)
    neg = sum(1 for v in vals if v < 0)
    zero = vals.count(0.0)
    distinct = len(set(u[::spec["distinct_stride"]]))
    fill_rows = 0
    if fill:
        for r in range(n_time):
            if u[r * n_range:(r + 1) * n_range].count(FILL_BITS) == n_range:
                fill_rows += 1
    neg_fraction = neg / len(vals)
    lo, hi = spec["neg_fraction"]
    if not lo <= neg_fraction <= hi:
        fail(f"negative fraction {neg_fraction:.3f} outside [{lo}, {hi}]")
    if var <= 0 or vmin == vmax:
        fail("constant sample")
    if distinct < spec["min_distinct"]:
        fail(f"only {distinct} distinct values in stride-{spec['distinct_stride']} subsample")
    if beta[:n_range * 4] == beta[-n_range * 4:]:
        fail("first and last profiles identical")
    return {
        "value_count": n,
        "fill_count": fill,
        "fill_profiles": fill_rows,
        "min": vmin,
        "max": vmax,
        "mean": mean,
        "std": math.sqrt(var),
        "negative_fraction": round(neg_fraction, 6),
        "zero_count": zero,
        "distinct_subsample": distinct,
    }


# ------------------------------------------------------------- commands
def cmd_check_meta(args) -> None:
    rows = {r["uuid"]: r for r in load_sources(Path(args.sources))}
    rec = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    row = rows.get(rec.get("uuid"))
    if row is None:
        fail(f"API record uuid {rec.get('uuid')} not pinned")
    checks = {
        "filename": (rec.get("filename"), row["filename"]),
        "measurementDate": (rec.get("measurementDate"), row["date"]),
        "checksum": (rec.get("checksum"), row["sha256"]),
        "size": (int(rec.get("size", -1)), row["size"]),
        "instrument.uuid": (rec.get("instrument", {}).get("uuid"), INSTRUMENT_UUID),
        "instrument.serialNumber": (rec.get("instrument", {}).get("serialNumber"), SERIAL),
        "site.id": (rec.get("site", {}).get("id"), SITE),
        "product.id": (rec.get("product", {}).get("id"), PRODUCT),
        "errorLevel": (rec.get("errorLevel"), "pass"),
        "tombstoneReason": (rec.get("tombstoneReason"), None),
        "format": (rec.get("format"), "HDF5 (NetCDF4)"),
    }
    for key, (got, want) in checks.items():
        if got != want:
            fail(f"{row['date']}: API {key}={got!r}, pinned {want!r}")
    if float(rec.get("coverage", 0)) < 0.99:
        fail(f"{row['date']}: coverage {rec.get('coverage')} < 0.99")
    versions = [s.get("version") for s in rec.get("software", []) if s.get("id") == "cloudnetpy"]
    if versions != [row["cloudnetpy_version"]]:
        fail(f"{row['date']}: cloudnetpy {versions} != pinned {row['cloudnetpy_version']}")
    expected_url = f"https://cloudnet.fmi.fi/api/download/product/{row['uuid']}/{row['filename']}"
    if rec.get("downloadUrl") != expected_url:
        fail(f"{row['date']}: downloadUrl {rec.get('downloadUrl')!r} != {expected_url}")
    print(f"meta ok {row['date']} {row['uuid']}")


def cmd_check_file(args) -> None:
    rows = {r["date"]: r for r in load_sources(Path(args.sources))}
    row = rows[args.date]
    path = Path(args.file)
    size = path.stat().st_size
    if size != row["size"]:
        fail(f"{row['date']}: size {size} != pinned {row['size']}")
    digest = sha256_file(path)
    if digest != row["sha256"]:
        fail(f"{row['date']}: sha256 {digest} != pinned {row['sha256']}")
    info = decode_file(path.read_bytes(), row, REAL_SPEC, "descent")
    stats = sample_stats(info["beta"], info["n_time"], info["n_range"], REAL_SPEC)
    print(f"file ok {row['date']} shape=({info['n_time']},{info['n_range']}) chunks={info['chunk_dims']} "
          f"fill={stats['fill_count']} min={stats['min']:.3e} max={stats['max']:.3e}")


def run_selftest() -> None:
    import selftest_chm15k
    selftest_chm15k.main(quiet=True)
    print("selftest ok")


def sample_rel(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['date'].replace('-', '')}_lindenberg_chm15k_beta_raw.f32le.bin"


def index_row(row: dict, info: dict, stats: dict, sample_sha: str) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_rel(row),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": stats["value_count"] * 4,
        "value_count": stats["value_count"],
        "shape": [info["n_time"], info["n_range"]],
        "axes": ["time", "range"],
        "measurement_date": row["date"],
        "source_uuid": row["uuid"],
        "source_filename": row["filename"],
        "source_sha256": row["sha256"],
        "cloudnetpy_version": row["cloudnetpy_version"],
        "chunk_dims": info["chunk_dims"],
        "deflate_level": info["deflate_level"],
        "time_first_h": info["time_first_h"],
        "time_last_h": info["time_last_h"],
        "median_dt_s": info["median_dt_s"],
        "max_gap_s": info["max_gap_s"],
        "range_sha256": info["range_sha256"],
        "fill_count": stats["fill_count"],
        "fill_profiles": stats["fill_profiles"],
        "min": stats["min"],
        "max": stats["max"],
        "mean": stats["mean"],
        "std": stats["std"],
        "negative_fraction": stats["negative_fraction"],
        "zero_count": stats["zero_count"],
        "distinct_subsample": stats["distinct_subsample"],
        "sample_sha256": sample_sha,
    }


def cmd_build(args) -> None:
    run_selftest()
    rows = load_sources(Path(args.sources))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*"):
        stale.unlink()
    index_rows = []
    range_hashes = set()
    sample_hashes = set()
    for row in rows:
        path = nc_path(downloads, row)
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            fail(f"{row['date']}: missing or unverified local file {path}; run download.sh")
        info = decode_file(path.read_bytes(), row, REAL_SPEC, "descent")
        stats = sample_stats(info["beta"], info["n_time"], info["n_range"], REAL_SPEC)
        sha = hashlib.sha256(info["beta"]).hexdigest()
        if sha in sample_hashes:
            fail(f"{row['date']}: duplicate sample content")
        sample_hashes.add(sha)
        range_hashes.add(info["range_sha256"])
        target = data_root / sample_rel(row)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(info["beta"])
        os.replace(tmp, target)
        index_rows.append(index_row(row, info, stats, sha))
        print(f"{row['date']} shape=({info['n_time']},{info['n_range']}) chunks={info['chunk_dims']} "
              f"deflate={info['deflate_level']} fill={stats['fill_count']} min={stats['min']:.4e} "
              f"max={stats['max']:.4e} std={stats['std']:.3e} neg={stats['negative_fraction']:.3f} "
              f"distinct={stats['distinct_subsample']} gap={info['max_gap_s']}s", flush=True)
    if len(range_hashes) != 1:
        fail(f"range axis differs across files ({len(range_hashes)} variants)")
    index_dir = data_root / "index" / DATASET_ID
    index_dir.mkdir(parents=True, exist_ok=True)
    with open(index_dir / "samples.jsonl.part", "w", encoding="utf-8") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(index_dir / "samples.jsonl.part", index_dir / "samples.jsonl")
    total_values = sum(r["value_count"] for r in index_rows)
    summary = {
        "dataset_id": DATASET_ID,
        "samples": len(index_rows),
        "total_values": total_values,
        "total_bytes": total_values * 4,
        "median_values": sorted(r["value_count"] for r in index_rows)[len(index_rows) // 2],
        "fill_values": sum(r["fill_count"] for r in index_rows),
        "range_sha256": range_hashes.pop(),
        "time_lengths": [r["shape"][0] for r in index_rows],
        "chunk_dims": sorted({tuple(r["chunk_dims"]) for r in index_rows}),
    }
    filtered = data_root / "filtered" / DATASET_ID
    filtered.mkdir(parents=True, exist_ok=True)
    (filtered / "ingest_stats.json").write_text(json.dumps(summary, indent=1, default=list) + "\n", encoding="utf-8")
    print(json.dumps(summary, default=list))


def cmd_verify(args) -> None:
    run_selftest()
    rows = load_sources(Path(args.sources))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [r["measurement_date"] for r in index] != [r["date"] for r in rows]:
        fail("index dates do not match sources.tsv")
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    expected_files = {Path(sample_rel(r)).name for r in rows}
    actual_files = {p.name for p in out_dir.iterdir()}
    if actual_files != expected_files:
        fail(f"sample directory mismatch: extra={sorted(actual_files - expected_files)} missing={sorted(expected_files - actual_files)}")
    hashes = set()
    range_hashes = set()
    for row, irow in zip(rows, index):
        path = nc_path(downloads, row)
        if path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            fail(f"{row['date']}: source file changed")
        info = decode_file(path.read_bytes(), row, REAL_SPEC, "siblings")
        sample_path = data_root / irow["sample_path"]
        if irow["sample_path"] != sample_rel(row):
            fail(f"{row['date']}: unexpected sample_path")
        sample = sample_path.read_bytes()
        if sample != info["beta"]:
            fail(f"{row['date']}: sample bytes differ from independent re-decode")
        stats = sample_stats(sample, info["n_time"], info["n_range"], REAL_SPEC)
        sha = hashlib.sha256(sample).hexdigest()
        expect = index_row(row, info, stats, sha)
        for key, value in expect.items():
            got = irow.get(key)
            if isinstance(value, float):
                if not (got == value or (math.isfinite(value) and abs(got - value) <= 1e-12 * max(1.0, abs(value)))):
                    fail(f"{row['date']}: index {key}={got!r} != recomputed {value!r}")
            elif got != value:
                fail(f"{row['date']}: index {key}={got!r} != recomputed {value!r}")
        # stored-dtype round trip of min/max
        for key in ("min", "max"):
            if struct.unpack("<f", struct.pack("<f", irow[key]))[0] != irow[key]:
                fail(f"{row['date']}: index {key} is not a float32 value")
        if len(sample) != irow["sample_size_bytes"] or irow["value_count"] * 4 != len(sample):
            fail(f"{row['date']}: size mismatch")
        if sha in hashes:
            fail(f"{row['date']}: duplicate sample")
        hashes.add(sha)
        range_hashes.add(info["range_sha256"])
        print(f"verified {row['date']} values={stats['value_count']} fill={stats['fill_count']}", flush=True)
    if len(range_hashes) != 1:
        fail("range axis differs across files")
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    total = sum(r["sample_size_bytes"] for r in index)
    if series[0]["sample_count"] != len(index) or series[0]["total_size_bytes"] != total:
        fail(f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
             f"!= realized {len(index)}/{total}")
    values = sorted(r["value_count"] for r in index)
    if values[len(values) // 2] < 1000 or total > 1_000_000_000:
        fail("floor or cap violated")
    print(f"verify ok samples={len(index)} values={sum(values)} bytes={total}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check-meta")
    p.add_argument("--sources", required=True)
    p.add_argument("--meta", required=True)
    p = sub.add_parser("check-file")
    p.add_argument("--sources", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--file", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--downloads", required=True)
        p.add_argument("--data-root", required=True)
        p.add_argument("--manifest", required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "selftest":
            run_selftest()
        elif args.cmd == "check-meta":
            cmd_check_meta(args)
        elif args.cmd == "check-file":
            cmd_check_file(args)
        elif args.cmd == "build":
            cmd_build(args)
        elif args.cmd == "verify":
            cmd_verify(args)
    except (RecipeError,) + DECODE_ERRORS as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
