#!/usr/bin/env python3
"""ICON IVM-A L2-7 ion drift velocity: range planning, validation and build.

Subcommands (all local-only; download.sh does the curl I/O):

  check-license FILE         NASA Science Data license page must state CC0 for
                             NASA-led mission data
  meta-plan                  walk each pinned file's HDF5 metadata over cached
                             16 KiB blocks; write block_requests.tsv (exit 3)
                             until complete, then data_ranges.tsv (exit 0)
  inventory                  decode every fetched chunk span, cross-check the
                             whole control file, write download_inventory.json
  build                      emit samples, index and ingest stats

One sample = the finite values of one velocity component of one UTC day, in
stored record order (the variables depend on Epoch, 1 Hz).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import struct
import sys
from array import array
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from h5lite import (  # noqa: E402
    FILTER_DEFLATE,
    FILTER_SHUFFLE,
    BlockStore,
    H5Error,
    H5File,
    MissingBlock,
    decode_chunk,
)

DATASET_ID = "icon_ivm_a_l27_ion_drift_velocity_f64"
SERIES_ID = "ivm_a_ion_drift_velocity_f64"
BASE_URL = "https://gov-nasa-hdrl-data1.s3.amazonaws.com/"
SOURCES_SHA256 = "5a24feca57bb015b98f221307584568f498a1feffd705b32e8fa7beb9c540893"
SOURCES_COUNT = 120
CONTROL_DATE = "20210407"
BLOCK_SIZE = 16384
CHUNK_ELEMENTS = 512  # normal chunk length; partial-day files use others (20210903: 510)
MAX_CHUNK_ELEMENTS = 65536
MIN_RECORDS = 1  # partial-day files exist (20210903: 5,600 records)
MAX_RECORDS = 86500
MIN_SAMPLE_VALUES = 1000
MAX_SPAN_OVERHEAD = 1.10  # span bytes / stored chunk bytes
COMPONENTS = [
    ("zonal", "ICON_L27_Ion_Velocity_Zonal"),
    ("meridional", "ICON_L27_Ion_Velocity_Meridional"),
    ("field_aligned", "ICON_L27_Ion_Velocity_Field_Aligned"),
]
# H5T_IEEE_F64LE datatype message (class 1 v1, little-endian, 8 bytes, 52/11 bit
# mantissa/exponent, bias 1023).
F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
LICENSE_SENTENCE = (
    "Unless the data file is marked with a restrictive notice or license, data that is "
    "provided from a NASA-led mission including observations, engineering, calibration, "
    "and auxiliary data are licensed as Creative Commons Zero"
)

if sys.byteorder != "little":
    raise SystemExit("this recipe assumes a little-endian host for array('d') I/O")


class PlanIncomplete(Exception):
    pass


# --------------------------------------------------------------------- sources
def load_sources(recipe_dir: Path) -> list[dict]:
    path = recipe_dir / "sources.tsv"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCES_SHA256:
        raise SystemExit(f"sources.tsv SHA-256 {digest} != pinned {SOURCES_SHA256}")
    lines = raw.decode("utf-8").splitlines()
    header = lines[0].split("\t")
    if header != ["date", "version", "key", "size_bytes", "s3_etag", "last_modified"]:
        raise SystemExit("unexpected sources.tsv header")
    rows = []
    for line in lines[1:]:
        fields = dict(zip(header, line.split("\t")))
        fields["size_bytes"] = int(fields["size_bytes"])
        fields["url"] = BASE_URL + fields["key"]
        expected_key = (
            f"spdf/cdaweb/data/icon/l2-7_ivm-a/{fields['date'][:4]}/"
            f"icon_l2-7_ivm-a_{fields['date']}_{fields['version']}.nc"
        )
        if fields["key"] != expected_key or not re.fullmatch(r"v06r\d{3}", fields["version"]):
            raise SystemExit(f"bad sources.tsv row {line!r}")
        rows.append(fields)
    if len(rows) != SOURCES_COUNT or len({r["date"] for r in rows}) != SOURCES_COUNT:
        raise SystemExit("sources.tsv must list 120 distinct days")
    if CONTROL_DATE not in {r["date"] for r in rows}:
        raise SystemExit("control day missing from sources.tsv")
    return rows


def day_dir(downloads: Path, row: dict) -> Path:
    return downloads / "days" / row["date"]


def span_path(downloads: Path, row: dict, component: str) -> Path:
    return day_dir(downloads, row) / f"span_{component}.bin"


def control_row(rows: list[dict]) -> dict:
    return next(r for r in rows if r["date"] == CONTROL_DATE)


def control_path(downloads: Path, rows: list[dict]) -> Path:
    return downloads / "control" / Path(control_row(rows)["key"]).name


# ------------------------------------------------------------------- metadata
def _scalar(value):
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def resolve(raw, row: dict) -> dict:
    """Validate identity and the three velocity datasets; return chunk plans.

    ``raw`` is a BlockStore over cached metadata blocks or complete file bytes.
    """
    f = H5File(raw)
    if len(raw) != row["size_bytes"]:
        raise H5Error("file size disagrees with sources.tsv")
    ga = f.attributes(f.root_addr)
    date = row["date"]
    expected = {
        "Instrument": "IVM-A",
        "LogicalSource": "ICON_L2-7_IVM-A",
        "Logical_File_ID": f"ICON_L2-7_IVM-A_{date[:4]}-{date[4:6]}-{date[6:]}_{row['version']}",
        "Project": "NASA > ICON",
        "Rules_of_Use": "Public Data for Scientific Use",
        "Time_Resolution": "1 Second",
    }
    for key, want in expected.items():
        if _scalar(ga.get(key)) != want:
            raise H5Error(f"{date}: global attribute {key}={ga.get(key)!r}, want {want!r}")
    if _scalar(ga.get("Data_Version_Major")) != 6:
        raise H5Error(f"{date}: Data_Version_Major={ga.get('Data_Version_Major')!r}, want 6")
    links = f.links(f.root_addr)
    # The creation-order index must agree; verify_samples.py navigates by it.
    if f.links(f.root_addr, index="creation_order") != links:
        raise H5Error(f"{date}: name and creation-order link indexes disagree")
    plan = {"date": date, "version": row["version"], "data_version": _scalar(ga.get("Data_Version")),
            "components": {}}
    lengths = set()
    for component, var in COMPONENTS:
        if var not in links:
            raise H5Error(f"{date}: variable {var} missing")
        msgs = f.messages(links[var])
        info = f.dataset(links[var], msgs)
        attrs = f.attributes(links[var], msgs)
        if info["datatype"] != F64LE:
            raise H5Error(f"{date} {var}: datatype is not H5T_IEEE_F64LE")
        if len(info["shape"]) != 1 or not MIN_RECORDS <= info["shape"][0] <= MAX_RECORDS:
            raise H5Error(f"{date} {var}: shape {info['shape']} out of scope")
        if (info["layout_class"] != 2 or len(info["chunk_dims"]) != 2 or info["chunk_dims"][1] != 8
                or not 1 <= info["chunk_dims"][0] <= MAX_CHUNK_ELEMENTS):
            raise H5Error(f"{date} {var}: chunk dims {info.get('chunk_dims')} are not <elements> x f8")
        chunk_elems = info["chunk_dims"][0]
        ids = [fid for fid, _flags, _vals in info["filters"]]
        if ids != [FILTER_SHUFFLE, FILTER_DEFLATE] or tuple(info["filters"][0][2]) != (8,):
            raise H5Error(f"{date} {var}: filter pipeline {info['filters']} is not shuffle(8)+deflate")
        checks = {"Units": "m/s", "Depend_0": "Epoch", "Var_Type": "data"}
        for key, want in checks.items():
            if _scalar(attrs.get(key)) != want:
                raise H5Error(f"{date} {var}: attribute {key}={attrs.get(key)!r}")
        fill = _scalar(attrs.get("FillVal"))
        if not (isinstance(fill, float) and math.isnan(fill)):
            raise H5Error(f"{date} {var}: FillVal {attrs.get('FillVal')!r} is not NaN")
        valid = (_scalar(attrs.get("Valid_Min")), _scalar(attrs.get("Valid_Max")))
        if valid != (-500.0, 500.0):
            raise H5Error(f"{date} {var}: Valid_Min/Max {valid}")
        n = info["shape"][0]
        lengths.add(n)
        entries, final_key = f.chunk_index(info["chunk_btree"], 2)
        entries.sort(key=lambda e: e[2][0])
        nchunks = (n + chunk_elems - 1) // chunk_elems
        if [e[2] for e in entries] != [(i * chunk_elems, 0) for i in range(nchunks)]:
            raise H5Error(f"{date} {var}: chunk grid is not 0..{nchunks - 1} x {chunk_elems}")
        if any(e[1] for e in entries):
            raise H5Error(f"{date} {var}: nonzero chunk filter mask")
        start = min(e[3] for e in entries)
        end = max(e[3] + e[0] for e in entries)
        stored = sum(e[0] for e in entries)
        addrs = sorted((e[3], e[3] + e[0]) for e in entries)
        if any(a_end > b_start for (_a, a_end), (b_start, _b) in zip(addrs, addrs[1:])):
            raise H5Error(f"{date} {var}: overlapping chunks")
        if end > len(raw) or (end - start) > MAX_SPAN_OVERHEAD * stored:
            raise H5Error(f"{date} {var}: chunk span {end - start} too sparse for {stored} stored bytes")
        plan["components"][component] = {
            "variable": var,
            "records": n,
            "chunk_elements": chunk_elems,
            "filters": info["filters"],
            "chunks": [(e[0], e[3]) for e in entries],
            "span_start": start,
            "span_end": end,
            "stored_bytes": stored,
        }
    if len(lengths) != 1:
        raise H5Error(f"{date}: components have different lengths {lengths}")
    plan["records"] = lengths.pop()
    return plan


def decode_component(span: bytes, comp: dict) -> bytes:
    """All stored records (including NaN fill) of one component, little-endian f8."""
    if len(span) != comp["span_end"] - comp["span_start"]:
        raise H5Error("span length mismatch")
    filters = comp["filters"]
    out = bytearray()
    base = comp["span_start"]
    for size, addr in comp["chunks"]:
        out += decode_chunk(span[addr - base:addr - base + size], filters, 0, 8, comp["chunk_elements"] * 8)
    return bytes(out[:comp["records"] * 8])


def decode_from_file(raw: bytes, comp: dict) -> bytes:
    return decode_component(raw[comp["span_start"]:comp["span_end"]], comp)


def apply_policy(decoded: bytes) -> tuple[array, dict]:
    """Missing-value policy: drop NaN fill; +-inf is fatal; keep everything else."""
    values = array("d")
    values.frombytes(decoded)
    kept = array("d", [v for v in values if v == v])
    if any(math.isinf(v) for v in kept):
        raise H5Error("infinite velocity value")
    stats = {
        "records": len(values),
        "nan_dropped": len(values) - len(kept),
        "kept": len(kept),
        "outside_valid_range": sum(1 for v in kept if v < -500.0 or v > 500.0),
    }
    return kept, stats


def load_plan(downloads: Path, row: dict) -> dict:
    store = BlockStore(day_dir(downloads, row) / "meta", row["size_bytes"], BLOCK_SIZE)
    plan = resolve(store, row)
    plan["meta_blocks"] = sorted(store.used)
    return plan


# ------------------------------------------------------------------- commands
def cmd_check_license(args) -> int:
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    if LICENSE_SENTENCE not in text:
        print("ERROR: NASA science data license page no longer states CC0 for NASA-led mission data", file=sys.stderr)
        return 1
    print("license_ok: NASA-led mission data licensed as Creative Commons Zero")
    return 0


def cmd_meta_plan(args) -> int:
    downloads = Path(args.downloads)
    rows = load_sources(Path(args.recipe_dir))
    requests = []
    plans = []
    for row in rows:
        try:
            plans.append((row, load_plan(downloads, row)))
        except MissingBlock as exc:
            store = BlockStore(day_dir(downloads, row) / "meta", row["size_bytes"], BLOCK_SIZE)
            start, end = store.block_span(exc.index)
            requests.append((row["url"], start, end - 1, str(store.block_path(exc.index)),
                             row["size_bytes"], row["s3_etag"]))
    with open(downloads / "block_requests.tsv", "w", encoding="utf-8") as handle:
        for req in requests:
            handle.write("\t".join(map(str, req)) + "\n")
    if requests:
        print(f"meta_plan pending_days={len(requests)} resolved_days={len(plans)}")
        return 3
    with open(downloads / "data_ranges.tsv", "w", encoding="utf-8") as handle:
        for row, plan in plans:
            for component, _var in COMPONENTS:
                comp = plan["components"][component]
                handle.write("\t".join(map(str, (
                    row["url"], comp["span_start"], comp["span_end"] - 1,
                    span_path(downloads, row, component), row["size_bytes"], row["s3_etag"],
                ))) + "\n")
    blocks = sum(len(p["meta_blocks"]) for _r, p in plans)
    span_bytes = sum(c["span_end"] - c["span_start"] for _r, p in plans for c in p["components"].values())
    print(f"meta_plan complete days={len(plans)} meta_blocks={blocks} span_bytes={span_bytes}")
    return 0


def decode_day(downloads: Path, row: dict) -> tuple[dict, dict]:
    plan = load_plan(downloads, row)
    decoded = {}
    for component, _var in COMPONENTS:
        comp = plan["components"][component]
        path = span_path(downloads, row, component)
        span = path.read_bytes()
        decoded[component] = decode_component(span, comp)
    return plan, decoded


def check_control(downloads: Path, rows: list[dict], decoded_by_date: dict) -> dict:
    """Whole-file decode of the control day must equal the range-based decode."""
    row = control_row(rows)
    path = control_path(downloads, rows)
    raw = path.read_bytes()
    if len(raw) != row["size_bytes"]:
        raise SystemExit(f"control file {path} has {len(raw)} bytes, expected {row['size_bytes']}")
    full_plan = resolve(raw, row)
    # Every cached metadata block must equal the same bytes of the whole file.
    meta = day_dir(downloads, row) / "meta"
    blocks = 0
    for block_file in sorted(meta.glob("blk_*.bin")):
        index = int(block_file.stem[4:])
        if block_file.read_bytes() != raw[index * BLOCK_SIZE:(index + 1) * BLOCK_SIZE]:
            raise SystemExit(f"cached metadata block {index} differs from the control file")
        blocks += 1
    result = {"date": row["date"], "file_bytes": len(raw), "meta_blocks_compared": blocks, "components": {}}
    for component, _var in COMPONENTS:
        whole = decode_from_file(raw, full_plan["components"][component])
        ranged = decoded_by_date[row["date"]][component]
        if whole != ranged:
            raise SystemExit(f"control {component}: whole-file decode differs from range decode")
        result["components"][component] = hashlib.sha256(whole).hexdigest()
    print(f"control_ok date={row['date']} meta_blocks={blocks} components_identical=3")
    return result


def cmd_inventory(args) -> int:
    downloads = Path(args.downloads)
    rows = load_sources(Path(args.recipe_dir))
    inventory = {"dataset_id": DATASET_ID, "sources_sha256": SOURCES_SHA256, "days": []}
    decoded_by_date = {}
    for row in rows:
        plan, decoded = decode_day(downloads, row)
        entry = {"date": row["date"], "version": row["version"], "records": plan["records"],
                 "meta_blocks": len(plan["meta_blocks"]), "components": {}}
        for component, _var in COMPONENTS:
            path = span_path(downloads, row, component)
            _kept, stats = apply_policy(decoded[component])
            entry["components"][component] = {
                "span_bytes": path.stat().st_size,
                "span_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                **stats,
            }
        inventory["days"].append(entry)
        if row["date"] == CONTROL_DATE:
            decoded_by_date[row["date"]] = decoded
    inventory["control"] = check_control(downloads, rows, decoded_by_date)
    out = downloads / "download_inventory.json"
    out.write_text(json.dumps(inventory, indent=1) + "\n", encoding="utf-8")
    print(f"inventory_ok days={len(rows)} file={out}")
    return 0


def cmd_build(args) -> int:
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    rows = load_sources(Path(args.recipe_dir))
    sample_root = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for directory in (sample_root, index_dir, filtered_dir):
        directory.mkdir(parents=True, exist_ok=True)
    for stale in sample_root.rglob("*.bin"):
        stale.unlink()
    index_rows = []
    skipped = []
    totals = {"days": 0, "records": 0, "nan_dropped": 0, "kept": 0, "outside_valid_range": 0}
    decoded_by_date = {}
    seen_digests = {}
    for row in rows:
        plan, decoded = decode_day(downloads, row)
        totals["days"] += 1
        if row["date"] == CONTROL_DATE:
            decoded_by_date[row["date"]] = decoded
        for component, var in COMPONENTS:
            kept, stats = apply_policy(decoded[component])
            for key in ("records", "nan_dropped", "outside_valid_range"):
                totals[key] += stats[key]
            if stats["kept"] < MIN_SAMPLE_VALUES:
                skipped.append({"date": row["date"], "component": component, **stats})
                continue
            if min(kept) == max(kept):
                raise SystemExit(f"{row['date']} {component}: constant sample")
            payload = kept.tobytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_digests:
                raise SystemExit(f"{row['date']} {component}: duplicate of {seen_digests[digest]}")
            seen_digests[digest] = f"{row['date']} {component}"
            year_dir = sample_root / row["date"][:4]
            year_dir.mkdir(parents=True, exist_ok=True)
            out = year_dir / f"icon_ivm_a_{row['date']}_{row['version']}_{component}.bin"
            out.write_bytes(payload)
            totals["kept"] += stats["kept"]
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(out.relative_to(data_root)),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(payload),
                "value_count": len(kept),
                "date": row["date"],
                "component": component,
                "source_variable": var,
                "source_key": row["key"],
                "source_version": row["version"],
                "data_version": plan["data_version"],
                "source_records": stats["records"],
                "nan_fill_dropped": stats["nan_dropped"],
                "outside_valid_range_kept": stats["outside_valid_range"],
                "min": min(kept),
                "max": max(kept),
                "sha256": digest,
            })
    control = check_control(downloads, rows, decoded_by_date)
    with open(index_dir / "samples.jsonl", "w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    stats_out = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sources_sha256": SOURCES_SHA256,
        "samples": len(index_rows),
        "total_size_bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "values": sum(r["value_count"] for r in index_rows),
        "totals": totals,
        "skipped_below_min_values": skipped,
        "control": control,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats_out, indent=1) + "\n", encoding="utf-8")
    print(f"build_ok samples={stats_out['samples']} bytes={stats_out['total_size_bytes']} "
          f"values={stats_out['values']} skipped={len(skipped)} nan_dropped={totals['nan_dropped']} "
          f"outside_valid_range_kept={totals['outside_valid_range']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-license")
    p.add_argument("file")
    for name in ("meta-plan", "inventory", "build"):
        p = sub.add_parser(name)
        p.add_argument("--downloads", required=True)
        p.add_argument("--recipe-dir", required=True)
        if name == "build":
            p.add_argument("--data-root", required=True)
    args = parser.parse_args()
    try:
        return {"check-license": cmd_check_license, "meta-plan": cmd_meta_plan,
                "inventory": cmd_inventory, "build": cmd_build}[args.cmd](args)
    except H5Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
