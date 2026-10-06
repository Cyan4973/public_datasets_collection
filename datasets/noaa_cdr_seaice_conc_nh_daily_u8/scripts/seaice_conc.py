#!/usr/bin/env python3
"""Inventory, download planning, build and verify for the NOAA/NSIDC sea-ice
concentration CDR (G02202 v4) Northern-Hemisphere daily grids.

Network I/O is done by download.sh with curl; this script only parses what
curl fetched.  Primary samples are the decoded ``cdr_seaice_conc`` uint8
raster of each daily NetCDF4 file (1 x 448 x 304 cells, row-major y, x).
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402

DATASET_ID = "noaa_cdr_seaice_conc_nh_daily_u8"
SERIES_ID = "cdr_seaice_conc_nh_daily_u8"
VARIABLE = "cdr_seaice_conc"
YEARS = (2022, 2023, 2024)
EXPECTED_FILES = 1096
EXPECTED_SOURCE_BYTES = 258_251_783
INVENTORY_SHA256 = "3489cfd1292053c64c2a671e3cb93ef0a4fce0a0ded449050a4fda5530760f3d"
INVENTORY_HEADER = "date\tkey\tsize_bytes\tmd5\n"
NAME_RE = re.compile(r"^seaice_conc_daily_nh_(\d{8})_f17_v04r00\.nc$")
DATA_PREFIX = "data/final/north/daily/{year}/"
CHECKSUM_PREFIX = "data/final/north/checksums/daily/{year}/"

SHAPE = (1, 448, 304)
VALUE_COUNT = SHAPE[0] * SHAPE[1] * SHAPE[2]
U8_DATATYPE = bytes.fromhex("100000000100000000000800")  # class 0 v1, LE unsigned, size 1, offset 0, precision 8
FILTER_DEFLATE = 1
FILTER_SHUFFLE = 2
FLAG_CODES = (251, 252, 253, 254, 255)
FLAG_MEANINGS = "pole_hole lakes coastal land_mask missing_data"
STATIC_CODES = (252, 253, 254)
ALLOWED_CODES = frozenset(range(0, 101)) | frozenset(FLAG_CODES)
STATIC_TABLE = bytes(value if value in STATIC_CODES else 0 for value in range(256))
EXPECTED_VARIABLE_ATTRS = {
    "long_name": "NOAA/NSIDC Climate Data Record of Passive Microwave Daily Northern Hemisphere Sea Ice Concentration",
    "standard_name": "sea_ice_area_fraction",
    "units": "1",
    "flag_values": list(FLAG_CODES),
    "flag_meanings": FLAG_MEANINGS,
    "valid_range": [0, 100],
    "_FillValue": [255],
    "_Unsigned": "true",
    "grid_mapping": "projection",
}
EXPECTED_GLOBAL_ATTRS = {
    "cdr_variable": VARIABLE,
    "product_version": "v04r00",
    "title": "NOAA/NSIDC Climate Data Record of Passive Microwave Sea Ice Concentration Version 4",
    "platform": "DMSP 5D-3/F17 > Defense Meteorological Satellite Program-F17",
    "sensor": "SSMI/S > Special Sensor Microwave Imager/Sounder",
    "license": "No constraints on data access or use",
    "time_coverage_duration": "P1D",
}


# --------------------------------------------------------------------------
# helpers
def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def source_path(downloads: Path, row: dict) -> Path:
    return downloads / "daily" / row["date"][:4] / Path(row["key"]).name


def mnf_path(downloads: Path, row: dict) -> Path:
    return downloads / "checksums" / row["date"][:4] / (Path(row["key"]).name + ".mnf")


def mnf_key(row: dict) -> str:
    return CHECKSUM_PREFIX.format(year=row["date"][:4]) + Path(row["key"]).name + ".mnf"


# --------------------------------------------------------------------------
# inventory
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
    count = re.search(r"<KeyCount>(\d+)</KeyCount>", text)
    if count and int(count.group(1)) != len(items):
        fail(f"{path.name}: KeyCount {count.group(1)} != parsed {len(items)}")
    return items


def build_inventory(listings: Path) -> str:
    rows = []
    for year in YEARS:
        data_prefix = DATA_PREFIX.format(year=year)
        checksum_prefix = CHECKSUM_PREFIX.format(year=year)
        data_items = parse_listing(listings / f"daily_{year}.xml", data_prefix)
        checksum_items = parse_listing(listings / f"checksums_{year}.xml", checksum_prefix)
        checksum_keys = {item["key"] for item in checksum_items}
        dates = set()
        for item in data_items:
            key = item["key"]
            if not key.startswith(data_prefix):
                fail(f"key outside prefix: {key}")
            match = NAME_RE.match(key[len(data_prefix):])
            if not match:
                fail(f"unexpected file in {data_prefix}: {key} (expected only f17 v04r00 daily files)")
            date = match.group(1)
            try:
                day = dt.date(int(date[:4]), int(date[4:6]), int(date[6:]))
            except ValueError:
                fail(f"invalid date in {key}")
            if day.year != year or date in dates:
                fail(f"date {date} misplaced or duplicated")
            dates.add(date)
            if not re.fullmatch(r"[0-9a-f]{32}", item["etag"]):
                fail(f"{key}: ETag is not a single-part MD5: {item['etag']}")
            if not 100_000 <= item["size"] <= 400_000:
                fail(f"{key}: implausible size {item['size']}")
            if checksum_prefix + key[len(data_prefix):] + ".mnf" not in checksum_keys:
                fail(f"{key}: no matching .mnf checksum manifest")
            rows.append((day.isoformat(), key, item["size"], item["etag"]))
        if len(dates) != days_in_year(year):
            fail(f"{year}: {len(dates)} daily files, expected {days_in_year(year)}")
    rows.sort()
    if len(rows) != EXPECTED_FILES:
        fail(f"inventory has {len(rows)} files, expected {EXPECTED_FILES}")
    total = sum(size for _date, _key, size, _md5 in rows)
    if total != EXPECTED_SOURCE_BYTES:
        fail(f"inventory totals {total} bytes, expected {EXPECTED_SOURCE_BYTES}")
    return INVENTORY_HEADER + "".join(f"{d}\t{k}\t{s}\t{m}\n" for d, k, s, m in rows)


def load_inventory(path: Path) -> list[dict]:
    if not path.is_file():
        fail(f"missing inventory {path}; run download.sh first")
    text = path.read_text(encoding="utf-8")
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
    if len(rows) != EXPECTED_FILES:
        fail("inventory row count changed")
    return rows


def cmd_inventory(args: argparse.Namespace) -> None:
    text = build_inventory(args.listings)
    digest = sha256_hex(text.encode("utf-8"))
    print(f"inventory_files={EXPECTED_FILES} inventory_bytes={EXPECTED_SOURCE_BYTES} inventory_sha256={digest}")
    if args.print_digest_only:
        return
    if digest != INVENTORY_SHA256:
        fail(f"upstream inventory changed: sha256 {digest} != pinned {INVENTORY_SHA256}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(args.out)


# --------------------------------------------------------------------------
# download planning / validation (called by download.sh between curl passes)
def check_mnf_bytes(data: bytes, row: dict) -> str | None:
    try:
        text = data.decode("ascii").strip()
    except UnicodeDecodeError:
        return "not ASCII"
    parts = text.split(",")
    if len(parts) != 3:
        return f"unexpected manifest text {text[:120]!r}"
    name, md5, size = parts
    if name != Path(row["key"]).name:
        return f"manifest names {name!r}"
    if md5 != row["md5"]:
        return f"manifest md5 {md5} != listing ETag {row['md5']}"
    if not size.isdigit() or int(size) != row["size"]:
        return f"manifest size {size} != listing size {row['size']}"
    return None


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
    rows = load_inventory(args.inventory)
    downloads = args.downloads
    pending = []
    promoted = rejected = 0
    for row in rows:
        if args.kind == "mnf":
            final, key, checker, limit = mnf_path(downloads, row), mnf_key(row), check_mnf_bytes, 1024
        else:
            if check_mnf_bytes(mnf_path(downloads, row).read_bytes() if mnf_path(downloads, row).is_file() else b"", row):
                fail(f"missing or invalid .mnf for {row['key']}; fetch manifests first")
            final, key, checker, limit = source_path(downloads, row), row["key"], check_source_bytes, row["size"]
        part = final.with_name(final.name + ".part")
        if final.is_file():
            problem = checker(final.read_bytes(), row)
            if problem is None:
                continue
            print(f"rejecting cached {final.name}: {problem}")
            final.unlink()
            rejected += 1
        if part.is_file():
            data = part.read_bytes()
            problem = checker(data, row)
            if problem is None:
                part.replace(final)
                promoted += 1
                continue
            if args.kind == "mnf" or len(data) >= limit:
                print(f"rejecting partial {part.name}: {problem}")
                part.unlink()
                rejected += 1
        final.parent.mkdir(parents=True, exist_ok=True)
        pending.append((args.base_url.rstrip("/") + "/" + key, part))
    with args.config.open("w", encoding="utf-8") as handle:
        for url, part in pending:
            handle.write(f'url = "{url}"\noutput = "{part}"\n')
    print(f"plan kind={args.kind} pending={len(pending)} promoted={promoted} rejected={rejected}")


# --------------------------------------------------------------------------
# decoding
def decode_grid(raw: bytes, date: str, link_index: str) -> tuple[bytes, dict]:
    """Decode and validate the cdr_seaice_conc raster of one daily file."""
    h5 = h5lite.H5File(raw)
    links = h5.links(h5.root_addr, index=link_index)
    if VARIABLE not in links:
        raise h5lite.H5Error(f"no root link named {VARIABLE!r}")
    attrs_global = h5.attributes(h5.root_addr)
    for key, expected in EXPECTED_GLOBAL_ATTRS.items():
        if attrs_global.get(key) != expected:
            raise h5lite.H5Error(f"global attribute {key}={attrs_global.get(key)!r} != {expected!r}")
    if attrs_global.get("time_coverage_start") != f"{date}T00:00:00Z":
        raise h5lite.H5Error(f"time_coverage_start {attrs_global.get('time_coverage_start')!r} != {date}")
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
    if info["datatype"] != U8_DATATYPE:
        raise h5lite.H5Error(f"datatype {info['datatype'].hex()} is not little-endian uint8")
    if info["layout_class"] != 2 or tuple(info["chunk_dims"]) != SHAPE + (1,):
        raise h5lite.H5Error(f"layout is not one {SHAPE} chunk: {info['layout_raw'].hex()}")
    filters = info["filters"]
    ids = [fid for fid, _flags, _cd in filters]
    if ids == [FILTER_DEFLATE]:
        pass
    elif ids == [FILTER_SHUFFLE, FILTER_DEFLATE] and filters[0][2] == (1,):
        pass  # byte shuffle over 1-byte elements is the identity permutation
    else:
        raise h5lite.H5Error(f"filter pipeline {filters} is not deflate (optionally after 1-byte shuffle)")
    deflate_params = filters[-1][2]
    if len(deflate_params) != 1 or not 0 <= deflate_params[0] <= 9:
        raise h5lite.H5Error(f"unexpected deflate parameters {deflate_params}")
    chunks, final_key = h5.chunk_index(info["chunk_btree"], 4)
    if len(chunks) != 1:
        raise h5lite.H5Error(f"expected exactly one chunk, found {len(chunks)}")
    stored_size, mask, offsets, chunk_addr = chunks[0]
    if mask != 0 or offsets != (0, 0, 0, 0) or final_key != SHAPE + (1,):
        raise h5lite.H5Error(f"unexpected chunk key mask={mask} offsets={offsets} final={final_key}")
    if stored_size <= 0 or chunk_addr + stored_size > len(raw):
        raise h5lite.H5Error("chunk extent exceeds file")
    inflater = zlib.decompressobj()
    payload = inflater.decompress(raw[chunk_addr:chunk_addr + stored_size], VALUE_COUNT + 1)
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail or len(payload) != VALUE_COUNT:
        raise h5lite.H5Error(f"chunk does not inflate to exactly {VALUE_COUNT} values")
    meta = {
        "writer": attrs_global.get("_NCProperties"),
        "software_version_id": attrs_global.get("software_version_id"),
        "date_created": attrs_global.get("date_created"),
        "superblock_version": h5.superblock_version,
        "filters": [[fid, list(cd)] for fid, _flags, cd in filters],
        "stored_chunk_size": stored_size,
        "checked_metadata_blocks": h5.checked_blocks,
    }
    return payload, meta


def grid_profile(payload: bytes) -> dict:
    counts = collections.Counter(payload)
    bad = sorted(set(counts) - ALLOWED_CODES)
    if bad:
        raise h5lite.H5Error(f"undocumented codes present: {bad[:10]}")
    if len(counts) < 2:
        raise h5lite.H5Error("constant grid")
    ice_cells = sum(n for code, n in counts.items() if 1 <= code <= 100)
    concentration = [code for code in counts if code <= 100]
    if not concentration:
        raise h5lite.H5Error("grid has no concentration codes (0..100) at all")
    if not all(counts.get(code, 0) for code in STATIC_CODES):
        raise h5lite.H5Error("grid lacks the static lake/coast/land mask codes")
    static = payload.translate(STATIC_TABLE)
    return {
        "min": min(counts),
        "max": max(counts),
        "distinct_codes": len(counts),
        "ice_cells": ice_cells,
        "open_water_cells": counts.get(0, 0),
        "concentration_min": min(concentration) if concentration else None,
        "concentration_max": max(concentration) if concentration else None,
        "flag_counts": {str(code): counts.get(code, 0) for code in FLAG_CODES},
        "static_mask_sha256": sha256_hex(static),
        "sha256": sha256_hex(payload),
    }


def scan(args: argparse.Namespace, link_index: str, consumer) -> dict:
    rows = load_inventory(args.downloads / "inventory.tsv")
    per_year = collections.Counter()
    flag_totals = collections.Counter()
    writers = collections.Counter()
    software = collections.Counter()
    masks = collections.Counter()
    aggregate = hashlib.sha256()
    ice_total = water_total = 0
    days_with_missing = days_without_ice = days_with_pole_hole = 0
    for number, row in enumerate(rows, 1):
        mnf = mnf_path(args.downloads, row)
        if not mnf.is_file() or check_mnf_bytes(mnf.read_bytes(), row):
            fail(f"missing or invalid checksum manifest {mnf}")
        path = source_path(args.downloads, row)
        if not path.is_file():
            fail(f"missing source file {path}")
        raw = path.read_bytes()
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            payload, meta = decode_grid(raw, row["date"], link_index)
            profile = grid_profile(payload)
        except (h5lite.H5Error, struct.error, KeyError, IndexError) as error:
            fail(f"{path.name}: {error}")
        per_year[row["date"][:4]] += 1
        flag_totals.update({code: int(n) for code, n in profile["flag_counts"].items()})
        writers[meta["writer"]] += 1
        software[meta["software_version_id"]] += 1
        masks[profile["static_mask_sha256"]] += 1
        ice_total += profile["ice_cells"]
        water_total += profile["open_water_cells"]
        days_with_missing += profile["flag_counts"]["255"] > 0
        days_with_pole_hole += profile["flag_counts"]["251"] > 0
        days_without_ice += profile["ice_cells"] == 0
        aggregate.update(payload)
        consumer(row, payload, meta, profile)
        if number % 100 == 0:
            print(f"processed={number}/{len(rows)}", flush=True)
    if len(masks) != 1:
        fail(f"static lake/coast/land mask differs between files: {dict(masks)}")
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "inventory_sha256": INVENTORY_SHA256,
        "sample_count": len(rows),
        "value_count": len(rows) * VALUE_COUNT,
        "total_size_bytes": len(rows) * VALUE_COUNT,
        "samples_per_year": dict(sorted(per_year.items())),
        "flag_code_totals": dict(sorted(flag_totals.items())),
        "ice_cells_total": ice_total,
        "open_water_cells_total": water_total,
        "days_with_missing_cells": days_with_missing,
        "days_with_pole_hole_cells": days_with_pole_hole,
        "days_without_ice_cells": days_without_ice,
        "writers": dict(sorted(writers.items())),
        "software_version_ids": dict(sorted(software.items())),
        "static_mask_sha256": next(iter(masks)),
        "aggregate_sha256": aggregate.hexdigest(),
    }


def sample_rel(row: dict) -> str:
    day = row["date"].replace("-", "")
    return f"samples/{DATASET_ID}/{SERIES_ID}/{day[:4]}/seaice_conc_nh_{day}.bin"


def index_row(row: dict, meta: dict, profile: dict) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_rel(row),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": VALUE_COUNT,
        "value_count": VALUE_COUNT,
        "sample_shape": [SHAPE[1], SHAPE[2]],
        "sample_axes": ["y", "x"],
        "natural_record_kind": "nsidc_cdr_daily_northern_hemisphere_concentration_grid",
        "source_field": VARIABLE,
        "source_key": row["key"],
        "source_md5": row["md5"],
        "source_size_bytes": row["size"],
        "date": row["date"],
        "writer": meta["writer"],
        "software_version_id": meta["software_version_id"],
        "filters": meta["filters"],
        "min": profile["min"],
        "max": profile["max"],
        "distinct_codes": profile["distinct_codes"],
        "ice_cells": profile["ice_cells"],
        "open_water_cells": profile["open_water_cells"],
        "flag_counts": profile["flag_counts"],
        "sha256": profile["sha256"],
    }


def run_selftest() -> None:
    import selftest_h5

    selftest_h5.main(quiet=True)


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
        summary = scan(args, "name", emit)
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
            fail(f"sample {sample} differs from fresh creation-order-index decode")
        seen.add(sample.resolve())

    # Independent route: resolve the variable through the creation-order v2
    # B-tree instead of the name-index B-tree used by build.
    summary = scan(args, "creation_order", compare)
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
    print(
        f"verified samples={summary['sample_count']} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']} aggregate_sha256={summary['aggregate_sha256']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--listings", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--print-digest-only", action="store_true")
    p.set_defaults(func=cmd_inventory)
    p = sub.add_parser("plan")
    p.add_argument("--kind", choices=("mnf", "nc"), required=True)
    p.add_argument("--inventory", type=Path, required=True)
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


def cmd_check_downloads(args: argparse.Namespace) -> None:
    """Semantic download check: every file decodes to a valid concentration grid."""
    rows = load_inventory(args.downloads / "inventory.tsv")
    total = 0
    for number, row in enumerate(rows, 1):
        path = source_path(args.downloads, row)
        raw = path.read_bytes() if path.is_file() else b""
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            payload, _meta = decode_grid(raw, row["date"], "name")
            grid_profile(payload)
        except (h5lite.H5Error, struct.error, KeyError, IndexError) as error:
            fail(f"{path.name}: semantically invalid: {error}")
        total += len(raw)
        if number % 200 == 0:
            print(f"checked={number}/{len(rows)}", flush=True)
    print(f"download_check=ok files={len(rows)} bytes={total}")


if __name__ == "__main__":
    main()
