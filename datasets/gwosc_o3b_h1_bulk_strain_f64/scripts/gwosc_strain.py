#!/usr/bin/env python3
"""Validate, build and verify gwosc_o3b_h1_bulk_strain_f64 (pure standard library).

validate  one downloaded GWOSC file against its files.tsv row (used by download.sh)
build     decode /strain/Strain of every pinned file into one raw float64 LE sample
verify    re-decode every source, byte-compare the samples, re-check the index

Each pinned file must satisfy (identical checks in every mode):
* exact pinned size; HDF5 superblock v0, v1 object headers, v1 chunk B-tree;
* /meta: StrainChannel H1:DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01, Detector H1,
  FrameType H1_HOFT_CLEAN_SUB60HZ_C01, Type StrainTimeSeries, GPSstart = pinned
  GPS, Duration 4096;
* /strain/Strain: rank-1 IEEE float64 LE, 16,777,216 values, chunk 8192,
  filters exactly [deflate, fletcher32]; attributes Npoints 16777216,
  Xspacing 1/4096, Xstart = pinned GPS;
* every chunk's Fletcher-32 verifies, inflates to 65,536 bytes, contains only
  finite values and is not all zero; no chunk repeats the previous one;
* /quality/simple/DQmask: 4096 1-Hz words with bit 0 (DQShortnames[0] == DATA)
  set in every second, i.e. the whole file is H1 science data;
* min and max of the decoded strain equal GWOSC's published per-file
  min_strain/max_strain (relative 1e-9) and the standard deviation agrees with
  GWOSC's stdev_strain (relative 1e-3).
No value is dropped, replaced or imputed; any failure is fatal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import mmap
import operator
import os
import struct
import sys
from array import array
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gwosc_h5  # noqa: E402

DATASET_ID = "gwosc_o3b_h1_bulk_strain_f64"
SERIES_ID = "h1_o3b_strain_4khz_f64"
CHANNEL = "H1:DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01"
FRAME_TYPE = "H1_HOFT_CLEAN_SUB60HZ_C01"
DURATION = 4096
RATE = 4096
NPOINTS = DURATION * RATE
CHUNK = 8192


class CheckError(SystemExit):
    pass


def fail(msg: str) -> None:
    raise CheckError(f"FATAL: {msg}")


def read_rows(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    for r in rows:
        r["gps_start"] = int(r["gps_start"])
        r["size_bytes"] = int(r["size_bytes"])
    return rows


def file_name(row: dict) -> str:
    return row["url"].rsplit("/", 1)[1]


def sample_rel(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/H-H1_GWOSC_O3b_4KHZ_R1-{row['gps_start']}-{DURATION}.f64le.bin"


def rel_close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b))


def decode_file(path: Path, row: dict, sink=None) -> dict:
    """Run every check on one source file; feed logical strain bytes to ``sink``."""
    size = path.stat().st_size
    if size != row["size_bytes"]:
        fail(f"{path.name}: size {size} != pinned {row['size_bytes']}")
    gps = row["gps_start"]
    with path.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        try:
            f = gwosc_h5.H5File(mm, row["size_bytes"])
            meta = {k: f.read_scalar(f"meta/{k}") for k in
                    ("StrainChannel", "Detector", "FrameType", "Type", "GPSstart", "Duration")}
            want = {"StrainChannel": CHANNEL, "Detector": "H1", "FrameType": FRAME_TYPE,
                    "Type": "StrainTimeSeries", "GPSstart": gps, "Duration": DURATION}
            if meta != want:
                fail(f"{path.name}: meta {meta} != {want}")
            names = f.read_strings("quality/simple/DQShortnames")
            if not names or names[0] != "DATA":
                fail(f"{path.name}: DQShortnames[0] is {names[:1]}, expected DATA")
            dq_info = f.dataset(f.resolve("quality/simple/DQmask"))
            if dq_info["shape"] != (DURATION,) or dq_info["dtype"]["size"] != 4:
                fail(f"{path.name}: DQmask shape/dtype {dq_info['shape']} {dq_info['dtype']}")
            dq = struct.unpack(f"<{DURATION}I", f.read_array_bytes(dq_info))
            missing = sum(1 for x in dq if not x & 1)
            if missing:
                fail(f"{path.name}: {missing} seconds lack the DQ DATA bit")
            info = f.dataset(f.resolve("strain/Strain"))
            if info["shape"] != (NPOINTS,) or info["dtype"] != {"kind": "float", "size": 8, "code": "d"}:
                fail(f"{path.name}: strain shape/dtype {info['shape']} {info['dtype']}")
            if [x[0] for x in info["filters"]] != [gwosc_h5.FILTER_DEFLATE, gwosc_h5.FILTER_FLETCHER32]:
                fail(f"{path.name}: unexpected filter pipeline {info['filters']}")
            if info["chunk_dims"] != (CHUNK,):
                fail(f"{path.name}: chunk dims {info['chunk_dims']}")
            attrs = info["attributes"]
            if (attrs.get("Npoints") != [NPOINTS] or attrs.get("Xspacing") != [1.0 / RATE]
                    or attrs.get("Xstart") != [gps]):
                fail(f"{path.name}: strain attributes {attrs}")
            lo, hi = math.inf, -math.inf
            total = 0.0
            sq = 0.0
            count = 0
            prev = None
            for off, n, data in f.iter_chunks_1d(info):
                if data == prev:
                    fail(f"{path.name}: chunk at {off} repeats the previous chunk")
                prev = data
                if data.count(0) == len(data):
                    fail(f"{path.name}: all-zero chunk at element {off}")
                vals = array("d")
                vals.frombytes(data)
                if sys.byteorder != "little":
                    vals.byteswap()
                s = math.fsum(vals)
                if not math.isfinite(s) or not math.isfinite(sum(map(abs, vals))):
                    fail(f"{path.name}: non-finite value in chunk at element {off}")
                lo = min(lo, min(vals))
                hi = max(hi, max(vals))
                total += s
                sq += math.fsum(map(operator.mul, vals, vals))
                count += n
                if sink is not None:
                    sink(data)
        except gwosc_h5.H5Error as exc:
            fail(f"{path.name}: HDF5 error: {exc}")
    if count != NPOINTS:
        fail(f"{path.name}: decoded {count} values")
    mean = total / count
    std = math.sqrt(max(0.0, sq / count - mean * mean))
    if not (lo < hi and std > 0):
        fail(f"{path.name}: degenerate strain (min {lo}, max {hi}, std {std})")
    gmin, gmax = float(row["gwosc_min_strain"]), float(row["gwosc_max_strain"])
    gstd = float(row["gwosc_stdev_strain"])
    if not (rel_close(lo, gmin, 1e-9) and rel_close(hi, gmax, 1e-9)):
        fail(f"{path.name}: min/max {lo!r}/{hi!r} != GWOSC published {gmin!r}/{gmax!r}")
    if not rel_close(std, gstd, 1e-3):
        fail(f"{path.name}: stdev {std!r} != GWOSC published {gstd!r}")
    return {"gps_start": gps, "min": lo, "max": hi, "mean": mean, "std": std, "values": count,
            "gwosc_mean": float(row["gwosc_mean_strain"])}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(8 << 20):
            h.update(block)
    return h.hexdigest()


def read_sums(path: Path) -> dict[str, str]:
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, name = line.split(None, 1)
                out[name.strip().lstrip("*")] = digest
    return out


def check_source_sha(downloads: Path, row: dict) -> str:
    sums = read_sums(downloads / "SHA256SUMS")
    name = file_name(row)
    if name not in sums:
        fail(f"{name}: no sha256 recorded by download.sh in SHA256SUMS")
    actual = sha256_file(downloads / name)
    if actual != sums[name]:
        fail(f"{name}: sha256 {actual} != recorded {sums[name]}")
    pinned = row.get("sha256", "").strip()
    if pinned and actual != pinned:
        fail(f"{name}: sha256 {actual} != pinned in files.tsv {pinned}")
    return actual


def cmd_validate(a) -> int:
    rows = {r["gps_start"]: r for r in read_rows(Path(a.files))}
    row = rows.get(a.gps)
    if row is None:
        fail(f"gps {a.gps} not pinned")
    stats = decode_file(Path(a.file), row)
    pinned = row.get("sha256", "").strip()
    if pinned:
        actual = sha256_file(Path(a.file))
        if actual != pinned:
            fail(f"{Path(a.file).name}: sha256 {actual} != pinned {pinned}")
        stats["sha256_pinned_match"] = True
    print("validate_ok " + json.dumps(stats, sort_keys=True))
    return 0


def index_row(row: dict, stats: dict, src_sha: str, sample_sha: str) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_rel(row),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": NPOINTS * 8,
        "value_count": NPOINTS,
        "sample_shape": [NPOINTS],
        "sample_axes": ["time"],
        "sample_rate_hz": RATE,
        "gps_start": row["gps_start"],
        "utc_start": row["utc_start"],
        "duration_s": DURATION,
        "channel": CHANNEL,
        "source_url": row["url"],
        "source_size_bytes": row["size_bytes"],
        "source_sha256": src_sha,
        "sample_sha256": sample_sha,
        "min": stats["min"],
        "max": stats["max"],
        "std": stats["std"],
    }


def cmd_build(a) -> int:
    rows = read_rows(Path(a.files))
    downloads, data_root = Path(a.downloads), Path(a.data_root)
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*"):
        stale.unlink()
    index_rows, per_file = [], []
    for row in rows:
        src = downloads / file_name(row)
        src_sha = check_source_sha(downloads, row)
        dst = data_root / sample_rel(row)
        tmp = dst.with_suffix(".part")
        h = hashlib.sha256()
        with tmp.open("wb") as out:
            def sink(data: bytes) -> None:
                out.write(data)
                h.update(data)
            stats = decode_file(src, row, sink)
        if tmp.stat().st_size != NPOINTS * 8:
            fail(f"{tmp}: wrong size")
        os.replace(tmp, dst)
        index_rows.append(index_row(row, stats, src_sha, h.hexdigest()))
        per_file.append(stats)
        print(f"built {dst.name} min={stats['min']:.6e} max={stats['max']:.6e} std={stats['std']:.6e} "
              f"mean={stats['mean']:.3e} (GWOSC mean {stats['gwosc_mean']:.3e})", flush=True)
    index = Path(a.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows), encoding="utf-8")
    st = Path(a.stats)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps({"dataset_id": DATASET_ID, "samples": len(index_rows),
                              "values": NPOINTS * len(index_rows), "bytes": NPOINTS * 8 * len(index_rows),
                              "files": per_file}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build_ok samples={len(index_rows)} bytes={NPOINTS * 8 * len(index_rows)}")
    return 0


def cmd_verify(a) -> int:
    rows = read_rows(Path(a.files))
    downloads, data_root = Path(a.downloads), Path(a.data_root)
    index = [json.loads(line) for line in Path(a.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != len(rows):
        fail(f"index has {len(index)} rows, files.tsv pins {len(rows)}")
    by_path = {r["sample_path"]: r for r in index}
    if len(by_path) != len(index):
        fail("duplicate sample paths in index")
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    expected_files = {Path(sample_rel(r)).name for r in rows}
    actual_files = {p.name for p in out_dir.iterdir()}
    if actual_files != expected_files:
        fail(f"sample directory mismatch: extra {sorted(actual_files - expected_files)} "
             f"missing {sorted(expected_files - actual_files)}")
    seen_sha = set()
    for row in rows:
        rel = sample_rel(row)
        ir = by_path.get(rel)
        if ir is None:
            fail(f"index lacks {rel}")
        fixed = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 64,
                 "endianness": "little", "element_size_bytes": 8, "sample_size_bytes": NPOINTS * 8,
                 "value_count": NPOINTS, "gps_start": row["gps_start"], "channel": CHANNEL,
                 "source_url": row["url"]}
        for k, v in fixed.items():
            if ir.get(k) != v:
                fail(f"{rel}: index {k}={ir.get(k)!r}, expected {v!r}")
        sample = data_root / rel
        if sample.stat().st_size != NPOINTS * 8:
            fail(f"{rel}: size {sample.stat().st_size}")
        src_sha = check_source_sha(downloads, row)
        if ir["source_sha256"] != src_sha:
            fail(f"{rel}: index source_sha256 differs from the local source")
        # independent pass over the stored sample bytes
        lo, hi, prev, n = math.inf, -math.inf, None, 0
        h = hashlib.sha256()
        with sample.open("rb") as fh:
            while block := fh.read(CHUNK * 8):
                h.update(block)
                vals = array("d")
                vals.frombytes(block)
                if sys.byteorder != "little":
                    vals.byteswap()
                if not math.isfinite(math.fsum(map(abs, vals))):
                    fail(f"{rel}: non-finite value near element {n}")
                if block == prev or block.count(0) == len(block):
                    fail(f"{rel}: repeated or all-zero block near element {n}")
                prev = block
                lo, hi = min(lo, min(vals)), max(hi, max(vals))
                n += len(vals)
        if n != NPOINTS or not lo < hi:
            fail(f"{rel}: {n} values, min {lo} max {hi}")
        if h.hexdigest() != ir["sample_sha256"] or lo != ir["min"] or hi != ir["max"]:
            fail(f"{rel}: sample sha256/min/max disagree with the index")
        if h.hexdigest() in seen_sha:
            fail(f"{rel}: duplicate sample content")
        seen_sha.add(h.hexdigest())
        # re-derive from the source and compare byte for byte
        hs = hashlib.sha256()
        stats = decode_file(downloads / file_name(row), row, hs.update)
        if hs.hexdigest() != ir["sample_sha256"] or stats["min"] != lo or stats["max"] != hi:
            fail(f"{rel}: re-decoded source differs from the stored sample")
        print(f"verified {Path(rel).name} sha256={h.hexdigest()[:16]} min={lo:.6e} max={hi:.6e}", flush=True)
    # manifest totals
    import tomllib
    manifest = tomllib.loads(Path(a.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest must declare the primary series exactly once")
    s = series[0]
    if s["sample_count"] != len(index) or s["total_size_bytes"] != NPOINTS * 8 * len(index):
        fail(f"manifest sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} != "
             f"{len(index)}/{NPOINTS * 8 * len(index)}")
    print(f"verify_ok samples={len(index)} bytes={NPOINTS * 8 * len(index)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--files", required=True)
    v.add_argument("--file", required=True)
    v.add_argument("--gps", type=int, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--files", required=True)
        p.add_argument("--downloads", required=True)
        p.add_argument("--data-root", required=True)
        p.add_argument("--index", required=True)
        if name == "build":
            p.add_argument("--stats", required=True)
        else:
            p.add_argument("--manifest", required=True)
    a = ap.parse_args()
    return {"validate": cmd_validate, "build": cmd_build, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
