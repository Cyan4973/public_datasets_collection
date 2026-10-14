#!/usr/bin/env python3
"""Inventory, download planning, build and verify for NOAA OISST v2.1
(AVHRR-only, 0.25 degree, final) daily sea-surface temperature grids.

Network I/O is done by discover.sh / download.sh with curl; this script only
parses what curl fetched.  Primary samples are the decoded ``sst`` int16
variable of each daily NetCDF4 file (1 x 1 x 720 x 1440, row-major lat, lon),
stored values unchanged (0.01 degC units, -999 land fill kept native).
"""
from __future__ import annotations

import argparse
import array
import collections
import datetime as dt
import hashlib
import html
import itertools
import json
import re
import shutil
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import h5lite  # noqa: E402

DATASET_ID = "noaa_cdr_oisst_v21_sst_i16"
SERIES_ID = "oisst_v21_sst_daily_i16"
VARIABLE = "sst"
NATURAL_RECORD_KIND = "oisst_v21_daily_global_quarter_degree_sst_analysis_grid"

# Scope: the 1st and 15th of every month, 2020-01-01 .. 2024-12-15 (final files).
YEARS = range(2020, 2025)
DAYS_OF_MONTH = (1, 15)
EXPECTED_FILES = len(YEARS) * 12 * len(DAYS_OF_MONTH)
INVENTORY_PATH = SCRIPT_DIR / "inventory.tsv"
INVENTORY_HEADER = "date\tkey\tsize_bytes\tmd5\n"
# Pinned by discover.sh on 2026-10-14; any upstream change to a selected file
# (size or MD5 ETag) changes this digest and stops the download.
INVENTORY_SHA256 = "6ffd557f3076b29686bd176f3e9b1233c60b8e83af780db72241dfb23e984c75"
EXPECTED_SOURCE_BYTES = 188_685_403
MONTH_PREFIX = "data/v2.1/avhrr/{yyyymm}/"
FINAL_RE = re.compile(r"^oisst-avhrr-v02r01\.(\d{8})\.nc$")
PRELIM_RE = re.compile(r"^oisst-avhrr-v02r01\.(\d{8})_preliminary\.nc$")

SHAPE = (1, 1, 720, 1440)
ROWS, COLS = SHAPE[2], SHAPE[3]
VALUE_COUNT = ROWS * COLS
STORED_BYTES = 2 * VALUE_COUNT
# HDF5 datatype message: fixed-point class v1, little-endian, signed, size 2,
# bit offset 0, precision 16.
I16_DATATYPE = bytes.fromhex("100800000200000000001000")
FILTER_DEFLATE = 1
FILTER_SHUFFLE = 2
FILL = -999
VALID_MIN, VALID_MAX = -300, 4500
LAND_FILL_CELLS = 345_650  # static land mask observed in 2015, 2020 and 2024 probe files
MIN_DISTINCT_OCEAN_VALUES = 1000

EXPECTED_VARIABLE_ATTRS = {
    "long_name": "Daily sea surface temperature",
    "units": "Celsius",
    "_FillValue": [FILL],
    "add_offset": [0.0],
    "valid_min": [VALID_MIN],
    "valid_max": [VALID_MAX],
}
EXPECTED_GLOBAL_ATTRS = {
    "title": "NOAA/NCEI 1/4 Degree Daily Optimum Interpolation Sea Surface Temperature (OISST) Analysis, Version 2.1 - Final",
    "product_version": "Version v02r01",
    "processing_level": "NOAA Level 4",
    "institution": "NOAA/National Centers for Environmental Information",
    "metadata_link": "https://doi.org/10.25921/RE9P-PT57",
    "geospatial_lat_resolution": [0.25],
    "geospatial_lon_resolution": [0.25],
    "geospatial_lat_min": [-90.0],
    "geospatial_lat_max": [90.0],
    "geospatial_lon_min": [0.0],
    "geospatial_lon_max": [360.0],
}
EXPECTED_AXIS_GRIDS = {
    "lat": "Uniform grid from -89.875 to 89.875 by 0.25",
    "lon": "Uniform grid from 0.125 to 359.875 by 0.25",
}


# --------------------------------------------------------------------------
# helpers
def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def selected_dates() -> list[dt.date]:
    return [dt.date(y, m, d) for y in YEARS for m in range(1, 13) for d in DAYS_OF_MONTH]


def file_key(day: dt.date) -> str:
    return MONTH_PREFIX.format(yyyymm=day.strftime("%Y%m")) + f"oisst-avhrr-v02r01.{day:%Y%m%d}.nc"


def source_path(downloads: Path, row: dict) -> Path:
    return downloads / "nc" / row["date"][:4] / Path(row["key"]).name


# --------------------------------------------------------------------------
# inventory (discover.sh)
def parse_listing(path: Path, prefix: str) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if "<ListBucketResult" not in text:
        fail(f"{path.name}: not an S3 ListBucketResult document")
    truncated = re.search(r"<IsTruncated>(\w+)</IsTruncated>", text)
    if not truncated or truncated.group(1) != "false":
        fail(f"{path.name}: listing is truncated or lacks IsTruncated")
    prefix_match = re.search(r"<Prefix>([^<]*)</Prefix>", text)
    if not prefix_match or html.unescape(prefix_match.group(1)) != prefix:
        fail(f"{path.name}: listing prefix mismatch")
    items = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, flags=re.S):
        key = re.search(r"<Key>([^<]+)</Key>", block)
        etag = re.search(r"<ETag>([^<]+)</ETag>", block)
        size = re.search(r"<Size>(\d+)</Size>", block)
        if not (key and etag and size):
            fail(f"{path.name}: malformed Contents element")
        items.append(
            {
                "key": html.unescape(key.group(1)),
                "etag": html.unescape(etag.group(1)).strip('"'),
                "size": int(size.group(1)),
            }
        )
    return items


def build_inventory(listings: Path) -> str:
    wanted = {file_key(day): day for day in selected_dates()}
    rows = []
    months = sorted({day.strftime("%Y%m") for day in wanted.values()})
    for yyyymm in months:
        prefix = MONTH_PREFIX.format(yyyymm=yyyymm)
        items = parse_listing(listings / f"{yyyymm}.xml", prefix)
        finals = 0
        for item in items:
            name = item["key"][len(prefix):]
            if not item["key"].startswith(prefix):
                fail(f"key outside prefix: {item['key']}")
            if PRELIM_RE.match(name):
                fail(f"{yyyymm}: preliminary file still present ({name}); month is not final")
            if not FINAL_RE.match(name):
                fail(f"{yyyymm}: unexpected object {name}")
            finals += 1
            if item["key"] in wanted:
                if not re.fullmatch(r"[0-9a-f]{32}", item["etag"]):
                    fail(f"{item['key']}: ETag is not a single-part MD5: {item['etag']}")
                if not 1_000_000 <= item["size"] <= 3_000_000:
                    fail(f"{item['key']}: implausible size {item['size']}")
                rows.append((wanted[item["key"]].isoformat(), item["key"], item["size"], item["etag"]))
        year, month = int(yyyymm[:4]), int(yyyymm[4:])
        days = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.date(year, month, 1)).days
        if finals != days:
            fail(f"{yyyymm}: {finals} final daily files, expected {days}")
    rows.sort()
    if len(rows) != EXPECTED_FILES or len({r[1] for r in rows}) != EXPECTED_FILES:
        fail(f"inventory has {len(rows)} files, expected {EXPECTED_FILES}")
    return INVENTORY_HEADER + "".join(f"{d}\t{k}\t{s}\t{m}\n" for d, k, s, m in rows)


def cmd_inventory(args: argparse.Namespace) -> None:
    text = build_inventory(args.listings)
    total = sum(int(line.split("\t")[2]) for line in text.splitlines()[1:])
    print(f"inventory_files={EXPECTED_FILES} inventory_bytes={total} inventory_sha256={sha256_hex(text.encode())}")
    args.out.write_text(text, encoding="utf-8")


def load_inventory() -> list[dict]:
    if not INVENTORY_PATH.is_file():
        fail(f"missing pinned inventory {INVENTORY_PATH}")
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    digest = sha256_hex(text.encode("utf-8"))
    if digest != INVENTORY_SHA256:
        fail(f"inventory SHA-256 {digest} != pinned {INVENTORY_SHA256}")
    lines = text.splitlines()
    if lines[0] + "\n" != INVENTORY_HEADER:
        fail("inventory header changed")
    rows = []
    for line in lines[1:]:
        date, key, size, md5 = line.split("\t")
        rows.append({"date": date, "key": key, "size": int(size), "md5": md5})
    expected = [(day.isoformat(), file_key(day)) for day in selected_dates()]
    if [(r["date"], r["key"]) for r in rows] != expected:
        fail("inventory dates/keys differ from the declared 1st/15th 2020-2024 scope")
    if sum(r["size"] for r in rows) != EXPECTED_SOURCE_BYTES:
        fail("inventory byte total differs from pinned EXPECTED_SOURCE_BYTES")
    return rows


# --------------------------------------------------------------------------
# download planning / validation (called by download.sh between curl passes)
def check_source_bytes(data: bytes, row: dict) -> str | None:
    if len(data) != row["size"]:
        return f"size {len(data)} != {row['size']}"
    if data[:8] != h5lite.HDF5_SIGNATURE:
        return "missing HDF5 signature"
    digest = md5_hex(data)
    if digest != row["md5"]:
        return f"md5 {digest} != {row['md5']}"
    return None


def cmd_plan(args: argparse.Namespace) -> None:
    rows = load_inventory()
    pending = []
    promoted = rejected = 0
    for row in rows:
        final = source_path(args.downloads, row)
        part = final.with_name(final.name + ".part")
        if final.is_file():
            problem = check_source_bytes(final.read_bytes(), row)
            if problem is None:
                continue
            print(f"rejecting cached {final.name}: {problem}")
            final.unlink()
            rejected += 1
        if part.is_file():
            data = part.read_bytes()
            problem = check_source_bytes(data, row)
            if problem is None:
                part.replace(final)
                promoted += 1
                continue
            if len(data) >= row["size"]:
                print(f"rejecting partial {part.name}: {problem}")
                part.unlink()
                rejected += 1
        final.parent.mkdir(parents=True, exist_ok=True)
        pending.append((args.base_url.rstrip("/") + "/" + row["key"], part))
    with args.config.open("w", encoding="utf-8") as handle:
        for url, part in pending:
            handle.write(f'url = "{url}"\noutput = "{part}"\n')
    print(f"plan pending={len(pending)} promoted={promoted} rejected={rejected}")


# --------------------------------------------------------------------------
# decoding
def unshuffle_slices(shuffled: bytes) -> bytes:
    """HDF5 shuffle inverse for 2-byte elements (build route): byte j of
    element i is stored at j * n + i."""
    n = len(shuffled) // 2
    out = bytearray(len(shuffled))
    out[0::2] = shuffled[:n]
    out[1::2] = shuffled[n:]
    return bytes(out)


def unshuffle_zip(shuffled: bytes) -> bytes:
    """Independent shuffle inverse (verify route): pairwise interleave."""
    n = len(shuffled) // 2
    return bytes(itertools.chain.from_iterable(zip(shuffled[:n], shuffled[n:])))


def decode_grid(raw: bytes, row: dict, link_index: str, unshuffle) -> tuple[bytes, dict]:
    """Decode and validate the sst int16 grid of one daily file; returns the
    little-endian stored bytes in (lat, lon) row-major order."""
    date = row["date"]
    h5 = h5lite.H5File(raw)
    links = h5.links(h5.root_addr, index=link_index)
    for name in (VARIABLE, "lat", "lon"):
        if name not in links:
            raise h5lite.H5Error(f"no root link named {name!r}")
    attrs_global = h5.attributes(h5.root_addr)
    for key, expected in EXPECTED_GLOBAL_ATTRS.items():
        if attrs_global.get(key) != expected:
            raise h5lite.H5Error(f"global attribute {key}={attrs_global.get(key)!r} != {expected!r}")
    if attrs_global.get("id") != Path(row["key"]).name:
        raise h5lite.H5Error(f"global id {attrs_global.get('id')!r} != file name")
    if attrs_global.get("time_coverage_start") != f"{date}T00:00:00Z":
        raise h5lite.H5Error(f"time_coverage_start {attrs_global.get('time_coverage_start')!r} != {date}")
    if attrs_global.get("time_coverage_end") != f"{date}T23:59:59Z":
        raise h5lite.H5Error(f"time_coverage_end {attrs_global.get('time_coverage_end')!r} != {date}")
    if not str(attrs_global.get("history", "")).startswith("Final file"):
        raise h5lite.H5Error(f"history does not describe a final file: {attrs_global.get('history')!r}")
    for axis, grid in EXPECTED_AXIS_GRIDS.items():
        axis_attrs = h5.attributes(links[axis])
        if axis_attrs.get("grids") != grid:
            raise h5lite.H5Error(f"{axis}.grids={axis_attrs.get('grids')!r} != {grid!r}")
    addr = links[VARIABLE]
    attrs = h5.attributes(addr)
    for key, expected in EXPECTED_VARIABLE_ATTRS.items():
        if attrs.get(key) != expected:
            raise h5lite.H5Error(f"{VARIABLE}.{key}={attrs.get(key)!r} != {expected!r}")
    scale = attrs.get("scale_factor")
    if not (isinstance(scale, list) and len(scale) == 1 and struct.pack("<f", scale[0]) == struct.pack("<f", 0.01)):
        raise h5lite.H5Error(f"{VARIABLE}.scale_factor={scale!r} is not float32 0.01")
    info = h5.dataset(addr)
    if info["shape"] != SHAPE:
        raise h5lite.H5Error(f"dataspace {info['shape']} != {SHAPE}")
    if info["datatype"] != I16_DATATYPE:
        raise h5lite.H5Error(f"datatype {info['datatype'].hex()} is not little-endian signed int16")
    if info["layout_class"] != 2 or tuple(info["chunk_dims"]) != SHAPE + (2,):
        raise h5lite.H5Error(f"layout is not one {SHAPE} chunk: {info['layout_raw'].hex()}")
    filters = info["filters"]
    if [fid for fid, _flags, _cd in filters] != [FILTER_SHUFFLE, FILTER_DEFLATE] or filters[0][2] != (2,):
        raise h5lite.H5Error(f"filter pipeline {filters} is not shuffle(2) + deflate")
    deflate_params = filters[1][2]
    if len(deflate_params) != 1 or not 0 <= deflate_params[0] <= 9:
        raise h5lite.H5Error(f"unexpected deflate parameters {deflate_params}")
    chunks, final_key = h5.chunk_index(info["chunk_btree"], 5)
    if len(chunks) != 1:
        raise h5lite.H5Error(f"expected exactly one chunk, found {len(chunks)}")
    stored_size, mask, offsets, chunk_addr = chunks[0]
    if mask != 0 or offsets != (0, 0, 0, 0, 0) or final_key != SHAPE + (2,):
        raise h5lite.H5Error(f"unexpected chunk key mask={mask} offsets={offsets} final={final_key}")
    if stored_size <= 0 or chunk_addr + stored_size > len(raw):
        raise h5lite.H5Error("chunk extent exceeds file")
    inflater = zlib.decompressobj()
    shuffled = inflater.decompress(raw[chunk_addr:chunk_addr + stored_size], STORED_BYTES + 1)
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail or len(shuffled) != STORED_BYTES:
        raise h5lite.H5Error(f"chunk does not inflate to exactly {STORED_BYTES} bytes")
    payload = unshuffle(shuffled)
    meta = {
        "writer": attrs_global.get("_NCProperties"),
        "date_created": attrs_global.get("date_created"),
        "superblock_version": h5.superblock_version,
        "deflate_level": deflate_params[0],
        "stored_chunk_size": stored_size,
        "checked_metadata_blocks": h5.checked_blocks,
    }
    return payload, meta


def grid_profile(payload: bytes) -> dict:
    """Missing-value policy and degeneracy checks on one stored int16 grid."""
    if len(payload) != STORED_BYTES:
        raise h5lite.H5Error("grid has the wrong byte length")
    values = array.array("h")
    values.frombytes(payload)
    if sys.byteorder == "big":
        values.byteswap()
    counts = collections.Counter(values)
    fill = counts.pop(FILL, 0)
    if not counts:
        raise h5lite.H5Error("grid is entirely fill")
    ocean_min, ocean_max = min(counts), max(counts)
    if ocean_min < VALID_MIN or ocean_max > VALID_MAX:
        raise h5lite.H5Error(f"ocean values {ocean_min}..{ocean_max} outside valid range {VALID_MIN}..{VALID_MAX}")
    if fill != LAND_FILL_CELLS:
        raise h5lite.H5Error(f"{fill} fill cells, expected the static land mask of {LAND_FILL_CELLS}")
    if len(counts) < MIN_DISTINCT_OCEAN_VALUES:
        raise h5lite.H5Error(f"only {len(counts)} distinct ocean values (degenerate)")
    land_mask = bytes(1 if v == FILL else 0 for v in values)
    top_value, top_count = counts.most_common(1)[0]
    return {
        "min": FILL,
        "max": ocean_max,
        "ocean_min": ocean_min,
        "ocean_max": ocean_max,
        "fill_cells": fill,
        "distinct_ocean_values": len(counts),
        "most_common_ocean_value": top_value,
        "most_common_ocean_fraction": round(top_count / VALUE_COUNT, 6),
        "ocean_sum": sum(v * n for v, n in counts.items()),
        "land_mask_sha256": sha256_hex(land_mask),
        "sha256": sha256_hex(payload),
    }


def scan(args: argparse.Namespace, link_index: str, unshuffle, consumer) -> dict:
    rows = load_inventory()
    per_year = collections.Counter()
    writers = collections.Counter()
    masks = collections.Counter()
    aggregate = hashlib.sha256()
    ocean_min = ocean_max = None
    ocean_sum = ocean_cells = 0
    for number, row in enumerate(rows, 1):
        path = source_path(args.downloads, row)
        if not path.is_file():
            fail(f"missing source file {path}")
        raw = path.read_bytes()
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            payload, meta = decode_grid(raw, row, link_index, unshuffle)
            profile = grid_profile(payload)
        except (h5lite.H5Error, struct.error, KeyError, IndexError) as error:
            fail(f"{path.name}: {error}")
        per_year[row["date"][:4]] += 1
        writers[str(meta["writer"])] += 1
        masks[profile["land_mask_sha256"]] += 1
        ocean_min = profile["ocean_min"] if ocean_min is None else min(ocean_min, profile["ocean_min"])
        ocean_max = profile["ocean_max"] if ocean_max is None else max(ocean_max, profile["ocean_max"])
        ocean_sum += profile["ocean_sum"]
        ocean_cells += VALUE_COUNT - profile["fill_cells"]
        aggregate.update(payload)
        consumer(row, payload, meta, profile)
        if number % 20 == 0:
            print(f"processed={number}/{len(rows)}", flush=True)
    if len(masks) != 1:
        fail(f"land fill mask differs between files: {dict(masks)}")
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "inventory_sha256": INVENTORY_SHA256,
        "sample_count": len(rows),
        "value_count": len(rows) * VALUE_COUNT,
        "total_size_bytes": len(rows) * STORED_BYTES,
        "samples_per_year": dict(sorted(per_year.items())),
        "writers": dict(sorted(writers.items())),
        "land_mask_sha256": next(iter(masks)),
        "land_fill_cells_per_grid": LAND_FILL_CELLS,
        "fill_fraction": round(LAND_FILL_CELLS / VALUE_COUNT, 6),
        "ocean_min": ocean_min,
        "ocean_max": ocean_max,
        "ocean_mean_centi_degc": round(ocean_sum / ocean_cells, 4),
        "aggregate_sha256": aggregate.hexdigest(),
    }


def sample_rel(row: dict) -> str:
    day = row["date"].replace("-", "")
    return f"samples/{DATASET_ID}/{SERIES_ID}/{day[:4]}/oisst_sst_{day}.bin"


def index_row(row: dict, meta: dict, profile: dict) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_rel(row),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": STORED_BYTES,
        "value_count": VALUE_COUNT,
        "sample_shape": [ROWS, COLS],
        "sample_axes": ["lat", "lon"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_field": VARIABLE,
        "source_key": row["key"],
        "source_md5": row["md5"],
        "source_size_bytes": row["size"],
        "date": row["date"],
        "writer": meta["writer"],
        "date_created": meta["date_created"],
        "min": profile["min"],
        "max": profile["max"],
        "ocean_min": profile["ocean_min"],
        "ocean_max": profile["ocean_max"],
        "fill_value": FILL,
        "fill_cells": profile["fill_cells"],
        "distinct_ocean_values": profile["distinct_ocean_values"],
        "most_common_ocean_value": profile["most_common_ocean_value"],
        "most_common_ocean_fraction": profile["most_common_ocean_fraction"],
        "sha256": profile["sha256"],
    }


def run_selftest() -> None:
    import selftest_oisst

    selftest_oisst.main(quiet=True)


def cmd_build(args: argparse.Namespace) -> None:
    run_selftest()
    out_dir = args.data_root / "samples" / DATASET_ID
    tmp_dir = args.data_root / "samples" / f".{DATASET_ID}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    rows_out: list[dict] = []

    def emit(row: dict, payload: bytes, meta: dict, profile: dict) -> None:
        rel = sample_rel(row)
        target = tmp_dir / Path(rel).relative_to(f"samples/{DATASET_ID}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        rows_out.append(index_row(row, meta, profile))

    try:
        summary = scan(args, "name", unshuffle_slices, emit)
    except BaseException:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_dir.replace(out_dir)
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows_out), encoding="utf-8")
    stats = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats.parent.mkdir(parents=True, exist_ok=True)
    stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    run_selftest()
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index.is_file() or not stats.is_file():
        fail("missing index or ingest stats; run build.sh first")
    indexed = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    position = 0
    seen: set[Path] = set()

    def compare(row: dict, payload: bytes, meta: dict, profile: dict) -> None:
        nonlocal position
        if position >= len(indexed):
            fail("index has fewer rows than the inventory")
        entry = indexed[position]
        position += 1
        expected = index_row(row, meta, profile)
        if entry != expected:
            diff = sorted(k for k in set(entry) | set(expected) if entry.get(k) != expected.get(k))
            fail(f"index row for {row['date']} differs from fresh decode: {diff}")
        sample = args.data_root / entry["sample_path"]
        if not sample.is_file() or sample.read_bytes() != payload:
            fail(f"sample {sample} differs from fresh independent decode")
        seen.add(sample.resolve())

    # Independent route: creation-order link index (build uses the name index)
    # and a different shuffle inverse.
    summary = scan(args, "creation_order", unshuffle_zip, compare)
    if position != len(indexed):
        fail("index has extra rows")
    on_disk = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if on_disk != seen:
        fail(f"sample directory has {len(on_disk - seen)} stale and {len(seen - on_disk)} missing files")
    if json.loads(stats.read_text(encoding="utf-8")) != summary:
        fail("ingest stats differ from fresh scan")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    if series[0].get("sample_count") != summary["sample_count"] or series[0].get("total_size_bytes") != summary["total_size_bytes"]:
        fail("manifest sample_count/total_size_bytes disagree with realized output")
    if len({e["sha256"] for e in indexed}) != len(indexed):
        fail("duplicate sample payloads")
    print(
        f"verified samples={summary['sample_count']} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']} aggregate_sha256={summary['aggregate_sha256']}"
    )


def cmd_check_downloads(args: argparse.Namespace) -> None:
    """Semantic download check: every file decodes to a valid SST grid."""
    rows = load_inventory()
    total = 0
    for number, row in enumerate(rows, 1):
        path = source_path(args.downloads, row)
        raw = path.read_bytes() if path.is_file() else b""
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            payload, _meta = decode_grid(raw, row, "name", unshuffle_slices)
            grid_profile(payload)
        except (h5lite.H5Error, struct.error, KeyError, IndexError) as error:
            fail(f"{path.name}: semantically invalid: {error}")
        total += len(raw)
        if number % 20 == 0:
            print(f"checked={number}/{len(rows)}", flush=True)
    print(f"download_check=ok files={len(rows)} bytes={total}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--listings", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_inventory)
    p = sub.add_parser("plan")
    p.add_argument("--downloads", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--config", type=Path, required=True)
    p.set_defaults(func=cmd_plan)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--downloads", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--manifest", type=Path, required=True)
        p.set_defaults(func=func)
    p = sub.add_parser("check-downloads")
    p.add_argument("--downloads", type=Path, required=True)
    p.set_defaults(func=cmd_check_downloads)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
