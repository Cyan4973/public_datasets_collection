#!/usr/bin/env python3
"""Build / verify MBARI MARS daily hybrid-millidecade PSD float32 samples.

build:  for each pinned day in days.tsv, parse the local NetCDF4/HDF5 file,
        locate the root-group ``psd`` dataset by link name, assert a contiguous
        unfiltered IEEE f32 LE 1440 x 2787 layout, and copy exactly its
        16,053,120-byte span (row-major minute x band, already little-endian)
        to one sample file per day. NaN (the dataset fill value) is preserved.
verify: independently re-derive each sample from the source file, compare
        bytes, recompute statistics with a different decoding path, check the
        index and manifest totals, and reject degenerate samples.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import mmap
import shutil
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mars_hdf5 as h5  # noqa: E402

DATASET_ID = "mbari_mars_hydrophone_hmd_psd_f32"
SERIES_ID = "mars_hmd_psd_db_f32"
FILE_SIZE = 16124324
MINUTES = 1440
BANDS = 2787
VALUES = MINUTES * BANDS
SAMPLE_BYTES = VALUES * 4
EXPECTED_SAMPLES = 36
MAX_NAN_FRACTION = 0.10  # a day that is >10% fill is "mostly missing" -> fatal
MAX_DUPLICATE_ROWS = 14  # consecutive identical minute spectra allowed (<1%)
MIN_ROW_DISTINCT_RATIO = 0.5
NATURAL_RECORD_KIND = "mars_daily_hmd_psd_netcdf_file_psd_variable"


def read_days(path: Path) -> list[dict[str, str]]:
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    header = lines[0].split("\t")
    rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]
    if len(rows) != EXPECTED_SAMPLES or len({r["key"] for r in rows}) != len(rows):
        raise SystemExit(f"days.tsv must list {EXPECTED_SAMPLES} distinct keys, found {len(rows)}")
    return rows


def locate_psd(raw, key: str) -> int:
    info = h5.root_datasets(raw)
    if "psd" not in info:
        raise ValueError(f"{key}: no root-group link named 'psd'")
    psd = info["psd"]
    lay = psd["layout"]
    if (
        tuple(psd["shape"]) != (MINUTES, BANDS)
        or not h5.is_ieee_f32le(psd["dtype"])
        or lay["class"] != 1
        or psd["filters"] != 0
        or lay["size"] != SAMPLE_BYTES
        or lay["address"] + lay["size"] > len(raw)
    ):
        raise ValueError(f"{key}: psd is not contiguous unfiltered f32le {MINUTES}x{BANDS}: {psd}")
    return int(lay["address"])


def stats_array(payload: bytes, key: str) -> dict[str, object]:
    """Build-side statistics via array('f')."""
    vals = array.array("f")
    vals.frombytes(payload)
    if sys.byteorder != "little":
        vals.byteswap()
    nan = 0
    inf = 0
    lo = math.inf
    hi = -math.inf
    for v in vals:
        if v != v:
            nan += 1
        elif v in (math.inf, -math.inf):
            inf += 1
        else:
            if v < lo:
                lo = v
            if v > hi:
                hi = v
    return {"nan_count": nan, "inf_count": inf, "min": lo, "max": hi}


def stats_struct(payload: bytes) -> dict[str, object]:
    """Verify-side statistics via struct per row, plus degeneracy checks."""
    nan = inf = 0
    lo = math.inf
    hi = -math.inf
    dup_rows = 0
    all_nan_rows = 0
    distinct_ratio_sum = 0.0
    prev = None
    row_bytes = BANDS * 4
    for r in range(MINUTES):
        chunk = payload[r * row_bytes:(r + 1) * row_bytes]
        if chunk == prev:
            dup_rows += 1
        prev = chunk
        row = struct.unpack(f"<{BANDS}f", chunk)
        finite = [v for v in row if math.isfinite(v)]
        nan += sum(1 for v in row if math.isnan(v))
        inf += sum(1 for v in row if math.isinf(v))
        if finite:
            lo = min(lo, min(finite))
            hi = max(hi, max(finite))
            distinct_ratio_sum += len(set(finite)) / BANDS
        else:
            all_nan_rows += 1
    return {
        "nan_count": nan,
        "inf_count": inf,
        "min": lo,
        "max": hi,
        "duplicate_consecutive_rows": dup_rows,
        "all_nan_rows": all_nan_rows,
        "mean_row_distinct_ratio": distinct_ratio_sum / MINUTES,
    }


def check_policy(st: dict[str, object], key: str) -> None:
    if st["inf_count"]:
        raise ValueError(f"{key}: {st['inf_count']} infinite values (only NaN fill is allowed)")
    if st["nan_count"] > MAX_NAN_FRACTION * VALUES:
        raise ValueError(f"{key}: mostly fill ({st['nan_count']} NaN of {VALUES})")
    if not (st["min"] < st["max"]):
        raise ValueError(f"{key}: constant or empty sample")


def sample_name(key: str) -> str:
    return Path(key).name[:-3] + ".bin"


def index_row(day: dict[str, str], rel: str, address: int, st: dict[str, object], digest: str) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel,
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": SAMPLE_BYTES,
        "value_count": VALUES,
        "shape": [MINUTES, BANDS],
        "axes": ["minute_utc", "hmd_band"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_key": day["key"],
        "source_etag": day["etag"],
        "utc_date": Path(day["key"]).name[5:13],
        "psd_hdf5_address": address,
        "nan_count": st["nan_count"],
        "min": st["min"],
        "max": st["max"],
        "sample_sha256": digest,
    }


def build(args: argparse.Namespace) -> None:
    data_root = args.data_root.resolve()
    days = read_days(args.days)
    out_dir = args.samples_dir.resolve() / SERIES_ID
    tmp_dir = args.samples_dir.resolve() / f".{SERIES_ID}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    rows = []
    agg = hashlib.sha256()
    total_nan = 0
    gmin, gmax = math.inf, -math.inf
    try:
        for i, day in enumerate(days, 1):
            src = args.downloads.resolve() / Path(day["key"]).name
            if not src.is_file() or src.stat().st_size != FILE_SIZE:
                raise ValueError(f"missing or wrong-sized source {src}")
            with src.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as raw:
                address = locate_psd(raw, day["key"])
                payload = bytes(raw[address:address + SAMPLE_BYTES])
            st = stats_array(payload, day["key"])
            check_policy(st, day["key"])
            digest = hashlib.sha256(payload).hexdigest()
            agg.update(payload)
            final = out_dir / sample_name(day["key"])
            (tmp_dir / final.name).write_bytes(payload)
            rows.append(index_row(day, final.relative_to(data_root).as_posix(), address, st, digest))
            total_nan += st["nan_count"]
            gmin, gmax = min(gmin, st["min"]), max(gmax, st["max"])
            print(f"[{i}/{len(days)}] {day['key']} addr={address} nan={st['nan_count']} "
                  f"min={st['min']:.4f} max={st['max']:.4f}", flush=True)
        if out_dir.exists():
            shutil.rmtree(out_dir)
        tmp_dir.replace(out_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    args.index.parent.mkdir(parents=True, exist_ok=True)
    tmp_index = args.index.with_suffix(".jsonl.tmp")
    with tmp_index.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.replace(args.index)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "values_per_sample": VALUES,
        "sample_size_bytes": SAMPLE_BYTES,
        "total_values": VALUES * len(rows),
        "total_size_bytes": SAMPLE_BYTES * len(rows),
        "nan_values": total_nan,
        "nan_fraction": total_nan / (VALUES * len(rows)),
        "min": gmin,
        "max": gmax,
        "aggregate_sha256": agg.hexdigest(),
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    data_root = args.data_root.resolve()
    days = read_days(args.days)
    out_dir = args.samples_dir.resolve() / SERIES_ID
    rows = [json.loads(ln) for ln in args.index.read_text().splitlines() if ln.strip()]
    if len(rows) != len(days):
        raise SystemExit(f"index has {len(rows)} rows, expected {len(days)}")
    by_key = {r["source_key"]: r for r in rows}
    if set(by_key) != {d["key"] for d in days}:
        raise SystemExit("index source keys differ from days.tsv")
    manifest = tomllib.loads(args.manifest.read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest lacks the primary series")
    expected_files = set()
    total_bytes = 0
    total_nan = 0
    agg = hashlib.sha256()
    for i, day in enumerate(days, 1):
        key = day["key"]
        src = args.downloads.resolve() / Path(key).name
        with src.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as raw:
            if len(raw) != FILE_SIZE:
                raise SystemExit(f"{key}: source size changed")
            address = locate_psd(raw, key)
            expected = bytes(raw[address:address + SAMPLE_BYTES])
        path = out_dir / sample_name(key)
        row = by_key[key]
        if data_root / row["sample_path"] != path or not path.is_file():
            raise SystemExit(f"{key}: sample path mismatch or missing")
        actual = path.read_bytes()
        if actual != expected:
            raise SystemExit(f"{key}: sample bytes differ from the source psd span")
        st = stats_struct(actual)
        try:
            check_policy(st, key)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if st["duplicate_consecutive_rows"] > MAX_DUPLICATE_ROWS:
            raise SystemExit(f"{key}: {st['duplicate_consecutive_rows']} repeated minute spectra")
        if st["mean_row_distinct_ratio"] < MIN_ROW_DISTINCT_RATIO:
            raise SystemExit(f"{key}: degenerate spectra (row distinct ratio {st['mean_row_distinct_ratio']:.3f})")
        digest = hashlib.sha256(actual).hexdigest()
        want = index_row(day, path.relative_to(data_root).as_posix(), address, st, digest)
        if row != want:
            diff = {k: (row.get(k), want.get(k)) for k in set(row) | set(want) if row.get(k) != want.get(k)}
            raise SystemExit(f"{key}: index row mismatch {diff}")
        expected_files.add(path)
        total_bytes += len(actual)
        total_nan += st["nan_count"]
        agg.update(actual)
        print(f"[{i}/{len(days)}] ok {key} nan={st['nan_count']} dup_rows={st['duplicate_consecutive_rows']} "
              f"distinct={st['mean_row_distinct_ratio']:.3f} range={st['min']:.3f}..{st['max']:.3f}", flush=True)
    if set(out_dir.glob("*.bin")) != expected_files:
        raise SystemExit("sample directory contains unexpected or missing files")
    s = series[0]
    if s["sample_count"] != len(days) or s["total_size_bytes"] != total_bytes:
        raise SystemExit(f"manifest totals {s['sample_count']}/{s['total_size_bytes']} != realized {len(days)}/{total_bytes}")
    stats = json.loads(args.stats.read_text())
    if stats["aggregate_sha256"] != agg.hexdigest() or stats["nan_values"] != total_nan:
        raise SystemExit("ingest_stats.json disagrees with verified samples")
    print(f"verify ok samples={len(days)} bytes={total_bytes} nan={total_nan} aggregate_sha256={agg.hexdigest()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["build", "verify"])
    ap.add_argument("--days", type=Path, required=True)
    ap.add_argument("--downloads", type=Path, required=True)
    ap.add_argument("--samples-dir", type=Path, required=True)
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--stats", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path)
    args = ap.parse_args()
    if args.mode == "build":
        build(args)
    else:
        if args.manifest is None:
            raise SystemExit("--manifest is required for verify")
        verify(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
