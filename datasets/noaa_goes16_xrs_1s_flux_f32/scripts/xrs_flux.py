#!/usr/bin/env python3
"""GOES-16 EXIS/XRS science-quality 1-s flux (xrsf-l2-flx1s_science v2-2-1).

Subcommands:
  plan             write a curl config for files that are missing or partial,
                   promoting completed .part files after size/SHA-256 checks
  check-downloads  fully decode every downloaded file (semantic validation)
  build            emit one raw little-endian float32 sample per UTC day and
                   channel (xrsa_flux, xrsb_flux) plus the sample index

The NetCDF4/HDF5 files are decoded with the pure-stdlib reader h5lite.py
(copied unchanged from datasets/noaa_cdr_seaice_conc_nh_daily_u8).  Variables
are always selected by link name, never by position.
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
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import H5Error, H5File  # noqa: E402

DATASET_ID = "noaa_goes16_xrs_1s_flux_f32"
BASE_URL = (
    "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/"
    "goes/goes16/l2/data/xrsf-l2-flx1s_science"
)
N_SECONDS = 86400
# HDF5 datatype messages (class 1 floating point, version 1, little-endian,
# IEEE layout): float32 and float64.
F32_TYPE = bytes.fromhex("11201f000400000000002000170800177f000000")
F64_TYPE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
FILL_VALUE = -9999.0
FILL_BITS = struct.pack("<f", FILL_VALUE)
MAX_MISSING_FRACTION = 0.5
MIN_DISTINCT_VALID = 100
LICENSE_ATTR = "These data may be redistributed and used without restriction. "
EPOCH = dt.datetime(2000, 1, 1, 12, 0, 0)

# series id -> (source variable, expected long_name)
SERIES = {
    "goes16_xrsa_flux_1s_f32": ("xrsa_flux", "Primary XRS-A channel flux."),
    "goes16_xrsb_flux_1s_f32": ("xrsb_flux", "Primary XRS-B channel flux."),
}
EXPECTED_GLOBALS = {
    "platform": "g16",
    "title": "L2 XRS 1-s fluxes",
    "institution": "DOC/NOAA/NESDIS",
    "time_coverage_resolution": "PT1S",
    "processing_level": "Level 2",
    "license": LICENSE_ATTR,
}


class RecipeError(ValueError):
    """Semantic validation failure."""


# ------------------------------------------------------------------ inventory
def read_inventory(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != ["date", "filename", "size_bytes", "sha256"]:
        raise RecipeError(f"unexpected inventory header in {path}")
    rows = []
    for line in lines[1:]:
        date, name, size, sha = line.split("\t")
        compact = date.replace("-", "")
        if name != f"sci_xrsf-l2-flx1s_g16_d{compact}_v2-2-1.nc":
            raise RecipeError(f"inventory filename {name} does not match date {date}")
        if sha != "-" and (len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)):
            raise RecipeError(f"bad sha256 field for {name}")
        rows.append({"date": date, "filename": name, "size": int(size), "sha256": "" if sha == "-" else sha})
    dates = [row["date"] for row in rows]
    if dates != sorted(set(dates)):
        raise RecipeError("inventory dates are not unique and sorted")
    return rows


def file_url(name: str) -> str:
    stamp = name.split("_d", 1)[1]
    return f"{BASE_URL}/{stamp[0:4]}/{stamp[4:6]}/{name}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_file_bytes(path: Path, row: dict) -> None:
    size = path.stat().st_size
    if size != row["size"]:
        raise RecipeError(f"{row['filename']}: size {size} != pinned {row['size']}")
    if row["sha256"] and sha256_of(path) != row["sha256"]:
        raise RecipeError(f"{row['filename']}: SHA-256 mismatch against pinned value")


# --------------------------------------------------------------------- decode
def unshuffle(data: bytes, element: int) -> bytes:
    """Inverse of the HDF5 byte-shuffle filter (all bytes 0, then all bytes 1, ...)."""
    if len(data) % element:
        raise RecipeError("shuffled buffer is not a whole number of elements")
    count = len(data) // element
    out = bytearray(len(data))
    for lane in range(element):
        out[lane::element] = data[lane * count:(lane + 1) * count]
    return bytes(out)


def read_variable(f: H5File, addr: int, datatype: bytes, element: int) -> bytes:
    """Decode a rank-1 (86400,) single-chunk shuffle+deflate variable."""
    info = f.dataset(addr)
    if info["shape"] != (N_SECONDS,):
        raise RecipeError(f"shape {info['shape']} != ({N_SECONDS},)")
    if info["datatype"] != datatype:
        raise RecipeError(f"unexpected datatype message {info['datatype'].hex()}")
    filters = [(fid, values) for fid, _flags, values in info["filters"]]
    if len(filters) != 2 or filters[0] != (2, (element,)) or filters[1][0] != 1 or len(filters[1][1]) != 1:
        raise RecipeError(f"unexpected filter pipeline {info['filters']}")
    if info["layout_class"] != 2 or tuple(info["chunk_dims"]) != (N_SECONDS, element):
        raise RecipeError(f"unexpected layout class/chunk dims {info['layout_class']} {info.get('chunk_dims')}")
    entries, final_key = f.chunk_index(info["chunk_btree"], 2)
    if len(entries) != 1:
        raise RecipeError(f"expected one chunk, found {len(entries)}")
    stored, mask, offsets, chunk_addr = entries[0]
    if mask != 0 or tuple(offsets) != (0, 0) or tuple(final_key) != (N_SECONDS, element):
        raise RecipeError(f"unexpected chunk key mask={mask} offsets={offsets} final={final_key}")
    if chunk_addr + stored > len(f.raw):
        raise RecipeError("chunk exceeds file")
    inflater = zlib.decompressobj()
    plain = inflater.decompress(f.raw[chunk_addr:chunk_addr + stored])
    if not inflater.eof or inflater.unused_data or len(plain) != N_SECONDS * element:
        raise RecipeError(f"chunk inflated to {len(plain)} bytes (want {N_SECONDS * element}) or did not end cleanly")
    return unshuffle(plain, element)


def check_globals(attrs: dict, filename: str, date: str) -> None:
    for key, value in EXPECTED_GLOBALS.items():
        if attrs.get(key) != value:
            raise RecipeError(f"global attribute {key}={attrs.get(key)!r} != {value!r}")
    if attrs.get("id") != filename:
        raise RecipeError(f"global id {attrs.get('id')!r} != {filename}")
    if attrs.get("time_coverage_start") != f"{date}T00:00:00.000Z":
        raise RecipeError(f"time_coverage_start {attrs.get('time_coverage_start')!r} does not match {date}")


def check_time(values: tuple[float, ...], date: str) -> dict:
    day0 = (dt.datetime.fromisoformat(date) - EPOCH).total_seconds()
    valid = [t for t in values if t != FILL_VALUE]
    if len(valid) < N_SECONDS // 2:
        raise RecipeError("time variable is mostly fill")
    if any(not math.isfinite(t) for t in valid):
        raise RecipeError("non-finite time value")
    if any(b <= a for a, b in zip(valid, valid[1:])):
        raise RecipeError("time is not strictly increasing")
    if valid[0] < day0 - 2.0 or valid[-1] > day0 + N_SECONDS + 2.0:
        raise RecipeError(f"time span {valid[0] - day0:.3f}..{valid[-1] - day0:.3f} s is outside the UTC day")
    return {"time_fill": N_SECONDS - len(valid), "first_offset_s": round(valid[0] - day0, 6),
            "last_offset_s": round(valid[-1] - day0, 6)}


def decode_day(raw: bytes, filename: str, date: str, index: str = "name") -> tuple[dict[str, bytes], dict]:
    f = H5File(raw)
    if f.superblock_version != 2:
        raise RecipeError(f"superblock version {f.superblock_version} != 2")
    links = f.links(f.root_addr, index)
    check_globals(f.attributes(f.root_addr), filename, date)
    payloads: dict[str, bytes] = {}
    for series_id, (variable, long_name) in SERIES.items():
        if variable not in links:
            raise RecipeError(f"missing variable {variable}")
        attrs = f.attributes(links[variable])
        if attrs.get("units") != "W/m2" or attrs.get("long_name") != long_name:
            raise RecipeError(f"{variable}: units/long_name {attrs.get('units')!r}/{attrs.get('long_name')!r}")
        if attrs.get("_FillValue") != [FILL_VALUE]:
            raise RecipeError(f"{variable}: _FillValue {attrs.get('_FillValue')!r}")
        payloads[series_id] = read_variable(f, links[variable], F32_TYPE, 4)
    if "time" not in links:
        raise RecipeError("missing time variable")
    time_raw = read_variable(f, links["time"], F64_TYPE, 8)
    meta = check_time(struct.unpack(f"<{N_SECONDS}d", time_raw), date)
    meta["checked_metadata_blocks"] = f.checked_blocks
    return payloads, meta


def profile(payload: bytes) -> dict:
    """Missing-value accounting and degeneracy checks for one float32 day."""
    if len(payload) != N_SECONDS * 4:
        raise RecipeError("payload length is not 86400 float32 values")
    values = struct.unpack(f"<{N_SECONDS}f", payload)
    fill = nan = inf = negative = 0
    valid: list[float] = []
    valid_bits: set[bytes] = set()
    for position, value in enumerate(values):
        if value != value:
            nan += 1
        elif value == FILL_VALUE:
            fill += 1
        elif math.isinf(value):
            inf += 1
        else:
            valid.append(value)
            valid_bits.add(payload[4 * position:4 * position + 4])
            if value < 0:
                negative += 1
    if inf:
        raise RecipeError(f"{inf} infinite values")
    distinct = len(valid_bits)
    return {
        "fill_count": fill,
        "nan_count": nan,
        "missing_fraction": round((fill + nan) / N_SECONDS, 6),
        "negative_count": negative,
        "distinct_valid": distinct,
        "min": min(valid) if valid else None,
        "max": max(valid) if valid else None,
    }


def day_is_kept(profiles: dict[str, dict]) -> tuple[bool, str]:
    for series_id, prof in profiles.items():
        if prof["missing_fraction"] > MAX_MISSING_FRACTION:
            return False, f"{series_id} missing fraction {prof['missing_fraction']} > {MAX_MISSING_FRACTION}"
    for series_id, prof in profiles.items():
        if prof["distinct_valid"] < MIN_DISTINCT_VALID:
            return False, f"{series_id} has only {prof['distinct_valid']} distinct valid values"
    return True, ""


# ------------------------------------------------------------------ commands
def cmd_plan(args: argparse.Namespace) -> None:
    rows = read_inventory(Path(args.inventory))
    daily = Path(args.downloads) / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    pending = []
    for row in rows:
        final = daily / row["filename"]
        part = daily / (row["filename"] + ".part")
        if final.exists():
            if final.stat().st_size == row["size"]:
                continue
            print(f"removing wrong-size file {final.name}")
            final.unlink()
        if part.exists():
            size = part.stat().st_size
            if size == row["size"]:
                if row["sha256"] and sha256_of(part) != row["sha256"]:
                    print(f"removing {part.name}: SHA-256 mismatch")
                    part.unlink()
                else:
                    part.rename(final)
                    continue
            elif size > row["size"]:
                print(f"removing oversized {part.name}")
                part.unlink()
        pending.append(row)
    with open(args.config, "w", encoding="utf-8") as fh:
        for row in pending:
            fh.write(f'url = "{file_url(row["filename"])}"\n')
            fh.write(f'output = "{daily / (row["filename"] + ".part")}"\n')
    print(f"plan: {len(rows) - len(pending)} complete, {len(pending)} pending")


def cmd_check_downloads(args: argparse.Namespace) -> None:
    downloads = Path(args.downloads)
    rows = read_inventory(Path(args.inventory))
    sha_lines = ["filename\tsize_bytes\tsha256"]
    for number, row in enumerate(rows, 1):
        path = downloads / "daily" / row["filename"]
        if not path.is_file():
            raise RecipeError(f"missing download {row['filename']}")
        check_file_bytes(path, row)
        raw = path.read_bytes()
        try:
            payloads, _meta = decode_day(raw, row["filename"], row["date"])
            for payload in payloads.values():
                profile(payload)
        except (H5Error, struct.error, KeyError, IndexError) as exc:
            raise RecipeError(f"{row['filename']}: {exc}") from exc
        sha_lines.append(f"{row['filename']}\t{len(raw)}\t{hashlib.sha256(raw).hexdigest()}")
        if number % 25 == 0:
            print(f"checked {number}/{len(rows)}")
    (downloads / "observed_sha256.tsv").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    print(f"check-downloads: {len(rows)} files decode to valid xrsa_flux/xrsb_flux days")


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID
    rows = read_inventory(Path(args.inventory))
    sample_root = data_root / "samples" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered = data_root / "filtered" / DATASET_ID
    for directory in [index_dir, filtered] + [sample_root / sid for sid in SERIES]:
        directory.mkdir(parents=True, exist_ok=True)
    for sid in SERIES:
        for stale in (sample_root / sid).glob("*.f32"):
            stale.unlink()
    index_rows: dict[str, list[dict]] = {sid: [] for sid in SERIES}
    excluded = []
    days = []
    for number, row in enumerate(rows, 1):
        path = downloads / "daily" / row["filename"]
        check_file_bytes(path, row)
        payloads, meta = decode_day(path.read_bytes(), row["filename"], row["date"])
        profiles = {sid: profile(payload) for sid, payload in payloads.items()}
        keep, reason = day_is_kept(profiles)
        days.append({"date": row["date"], "kept": keep, "reason": reason, "time": meta,
                     "profiles": profiles})
        if not keep:
            excluded.append({"date": row["date"], "reason": reason})
            print(f"exclude {row['date']}: {reason}")
            continue
        stamp = row["date"].replace("-", "")
        for sid, payload in payloads.items():
            rel = f"samples/{DATASET_ID}/{sid}/{stamp}.f32"
            (data_root / rel).write_bytes(payload)
            prof = profiles[sid]
            index_rows[sid].append({
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "sample_path": rel,
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": N_SECONDS,
                "date": row["date"],
                "source_file": row["filename"],
                "source_variable": SERIES[sid][0],
                "fill_count": prof["fill_count"],
                "nan_count": prof["nan_count"],
                "min": prof["min"],
                "max": prof["max"],
            })
        if number % 25 == 0:
            print(f"built {number}/{len(rows)}")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for sid in SERIES:
            for item in index_rows[sid]:
                fh.write(json.dumps(item, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "inventory_days": len(rows),
        "kept_days": len(rows) - len(excluded),
        "excluded_days": excluded,
        "max_missing_fraction": MAX_MISSING_FRACTION,
        "series": {
            sid: {
                "sample_count": len(items),
                "total_size_bytes": sum(item["sample_size_bytes"] for item in items),
                "fill_values": sum(item["fill_count"] for item in items),
                "nan_values": sum(item["nan_count"] for item in items),
                "max_day_missing_fraction": max(((item["fill_count"] + item["nan_count"]) / N_SECONDS for item in items), default=0),
                "min": min((item["min"] for item in items), default=None),
                "max": max((item["max"] for item in items), default=None),
            }
            for sid, items in index_rows.items()
        },
        "days": days,
    }
    (filtered / "ingest_stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for sid, info in stats["series"].items():
        print(f"series {sid}: samples={info['sample_count']} bytes={info['total_size_bytes']} "
              f"fill={info['fill_values']} nan={info['nan_values']} range={info['min']}..{info['max']}")
    print(f"build: kept {stats['kept_days']}/{len(rows)} days, excluded {len(excluded)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--inventory", required=True)
    plan.add_argument("--downloads", required=True)
    plan.add_argument("--config", required=True)
    check = sub.add_parser("check-downloads")
    check.add_argument("--inventory", required=True)
    check.add_argument("--downloads", required=True)
    build = sub.add_parser("build")
    build.add_argument("--inventory", required=True)
    build.add_argument("--data-root", required=True)
    args = parser.parse_args()
    try:
        {"plan": cmd_plan, "check-downloads": cmd_check_downloads, "build": cmd_build}[args.command](args)
    except (RecipeError, H5Error) as exc:
        raise SystemExit(f"FATAL: {exc}")


if __name__ == "__main__":
    main()
