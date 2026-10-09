#!/usr/bin/env python3
"""Plan, build and verify GWTC-3 C01:IMRPhenomXPHM posterior-sample columns.

Subcommands
-----------
validate-record  check the saved Zenodo record JSON (license, title, every
                 pinned file key/size/MD5 in sources.tsv)
plan             walk each pinned file's HDF5 metadata through the local
                 64 KiB block cache; list the metadata block ranges still
                 needed, then the one contiguous byte span holding the
                 C01:IMRPhenomXPHM/posterior_samples table (exit 3 while
                 anything is missing, 0 when complete)
build            decode the selected compound members of every table and
                 emit one raw little-endian float64 sample per (event, parameter)
verify           re-decode through an independent struct-based path,
                 byte-compare every sample, check index/manifest/control

The parser never touches the network; ``download.sh`` fetches with curl.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import sys
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blockstore import BLOCK_SIZE, BlockStore, MissingBlock  # noqa: E402
import pe_h5  # noqa: E402

DATASET_ID = "gwtc3_imrphenomxphm_posterior_samples_f64"
RECORD_ID = 8177023
RECORD_TITLE_PREFIX = "GWTC-3: Compact Binary Coalescences Observed by LIGO and Virgo During the Second Part of the Third Observing Run"
API = "https://zenodo.org/api/records"
ANALYSIS = "C01:IMRPhenomXPHM"
TABLE = "posterior_samples"
CONTROL_EVENT = "GW200322_091133"
MIN_ROWS = 1000
# Metadata range requests: bridge gaps of up to 2 blocks, cap a request at 64 blocks (4 MiB).
MAX_GAP_BLOCKS = 2
MAX_RUN_BLOCKS = 64
HEAD_PREFETCH_BLOCKS = 16

# (series id, compound member, unit, meaning).  One primary series per member.
PARAMETERS = [
    ("mass_1_source", "Msun", "source-frame primary (heavier) component mass"),
    ("mass_2_source", "Msun", "source-frame secondary component mass"),
    ("a_1", "dimensionless", "primary dimensionless spin magnitude"),
    ("a_2", "dimensionless", "secondary dimensionless spin magnitude"),
    ("tilt_1", "rad", "primary spin tilt w.r.t. orbital angular momentum at reference frequency"),
    ("tilt_2", "rad", "secondary spin tilt at reference frequency"),
    ("phi_12", "rad", "azimuthal angle between the two in-plane spin projections"),
    ("phi_jl", "rad", "azimuth of L around the total angular momentum J"),
    ("theta_jn", "rad", "inclination of J to the line of sight"),
    ("psi", "rad", "polarisation angle"),
    ("phase", "rad", "orbital phase at reference frequency"),
    ("luminosity_distance", "Mpc", "luminosity distance"),
    ("ra", "rad", "right ascension"),
    ("dec", "rad", "declination"),
    ("geocent_time", "s (GPS)", "coalescence time at the geocentre"),
    ("final_mass_source", "Msun", "source-frame remnant black-hole mass (NR-fit)"),
    ("final_spin", "dimensionless", "remnant black-hole dimensionless spin (NR-fit)"),
    ("log_likelihood", "nat", "log likelihood of the draw"),
]
MEMBERS = [p[0] for p in PARAMETERS]
# Loose physical sanity bounds per member (inclusive); a draw outside them is fatal.
# Mass/distance bounds are wide on purpose: weak events (e.g. GW200308_173609,
# GW200322_091133) have posterior tails to ~800 Msun and ~30 Gpc.
BOUNDS = {
    "mass_1_source": (0.5, 3000.0), "mass_2_source": (0.1, 3000.0),
    "a_1": (0.0, 1.0), "a_2": (0.0, 1.0),
    "tilt_1": (0.0, math.pi), "tilt_2": (0.0, math.pi),
    "phi_12": (0.0, 2 * math.pi), "phi_jl": (0.0, 2 * math.pi),
    "theta_jn": (0.0, math.pi), "psi": (0.0, 2 * math.pi), "phase": (0.0, 2 * math.pi),
    "luminosity_distance": (1.0, 100000.0),
    "ra": (0.0, 2 * math.pi), "dec": (-math.pi / 2, math.pi / 2),
    "geocent_time": (1256655618.0, 1269363618.0),  # O3b: 2019-11-01 to 2020-03-27 UTC
    "final_mass_source": (0.5, 5000.0), "final_spin": (0.0, 1.0),
    "log_likelihood": (-1e4, 1e5),
}

if sys.byteorder != "little":
    raise SystemExit("this tool assumes a little-endian host")


# ------------------------------------------------------------------ sources
def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != ["event", "key", "size", "md5", "rows", "members", "table_offset", "table_bytes"]:
        raise SystemExit(f"unexpected sources.tsv header {header}")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        for key in ("size", "rows", "members", "table_offset", "table_bytes"):
            row[key] = int(row[key])
        if row["key"] != f"IGWN-GWTC3p0-v2-{row['event']}_PEDataRelease_mixed_cosmo.h5":
            raise SystemExit(f"sources.tsv: key {row['key']} does not match event {row['event']}")
        if row["rows"] * row["members"] * 8 != row["table_bytes"]:
            raise SystemExit(f"sources.tsv: {row['event']} table bytes inconsistent")
        row["url"] = f"{API}/{RECORD_ID}/files/{row['key']}/content"
        rows.append(row)
    if not rows or len({r["event"] for r in rows}) != len(rows):
        raise SystemExit("sources.tsv is empty or has duplicate events")
    return rows


def table_path(downloads: Path, src: dict) -> Path:
    return downloads / "tables" / f"{src['event']}_{ANALYSIS.replace(':', '_')}_{TABLE}.bin"


# --------------------------------------------------------------- validation
def cmd_validate_record(args) -> int:
    sources = read_sources(Path(args.sources))
    rec = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if int(rec.get("id", 0)) != RECORD_ID:
        raise SystemExit(f"record id {rec.get('id')} != {RECORD_ID}")
    meta = rec.get("metadata") or {}
    if not str(meta.get("title", "")).startswith(RECORD_TITLE_PREFIX):
        raise SystemExit(f"unexpected record title {meta.get('title')!r}")
    lic = (meta.get("license") or {}).get("id")
    if lic != "cc-by-4.0":
        raise SystemExit(f"record license changed to {lic!r}")
    files = {f["key"]: f for f in rec.get("files", [])}
    for src in sources:
        item = files.get(src["key"])
        if item is None:
            raise SystemExit(f"{src['key']} missing from record")
        if int(item["size"]) != src["size"] or item.get("checksum") != f"md5:{src['md5']}":
            raise SystemExit(f"{src['key']}: size/checksum changed")
    print(f"record_ok id={RECORD_ID} license=cc-by-4.0 files_checked={len(sources)}")
    return 0


# -------------------------------------------------------------------- plan
def locate_table(f: pe_h5.H5File, src: dict) -> dict:
    """Resolve C01:IMRPhenomXPHM/posterior_samples and check it against sources.tsv."""
    if f.eof != src["size"]:
        raise SystemExit(f"{src['event']}: superblock EOF {f.eof} != pinned size {src['size']}")
    root = f.group_links(f.root_addr)
    if ANALYSIS not in root:
        raise SystemExit(f"{src['event']}: group {ANALYSIS} missing (groups: {sorted(root)})")
    group = f.group_links(root[ANALYSIS])
    if TABLE not in group:
        raise SystemExit(f"{src['event']}: {ANALYSIS}/{TABLE} missing")
    info = f.dataset(group[TABLE])
    dtype = info["dtype"]
    if dtype["kind"] != "compound":
        raise SystemExit(f"{src['event']}: {TABLE} is not a compound table")
    if info["layout_class"] != 1 or info["filters"]:
        raise SystemExit(f"{src['event']}: {TABLE} is not a contiguous unfiltered dataset")
    if info["shape"] != (src["rows"],) or len(dtype["members"]) != src["members"]:
        raise SystemExit(f"{src['event']}: shape {info['shape']} / members {len(dtype['members'])} != pinned")
    if (info["data_addr"], info["data_size"]) != (src["table_offset"], src["table_bytes"]):
        raise SystemExit(f"{src['event']}: table span {info['data_addr']}+{info['data_size']} != pinned")
    if dtype["size"] != 8 * src["members"]:
        raise SystemExit(f"{src['event']}: record size {dtype['size']} != 8 x members")
    by_name = {m["name"]: m for m in dtype["members"]}
    for name in MEMBERS:
        m = by_name.get(name)
        if m is None:
            raise SystemExit(f"{src['event']}: member {name} missing")
        if (m["kind"], m["size"], m["code"]) != ("float", 8, "d"):
            raise SystemExit(f"{src['event']}: member {name} is not IEEE float64 LE")
    info["offsets"] = {name: by_name[name]["offset"] for name in MEMBERS}
    info["all_members"] = [m["name"] for m in dtype["members"]]
    return info


def cmd_plan(args) -> int:
    sources = read_sources(Path(args.sources))
    downloads = Path(args.downloads)
    meta_requests: list[str] = []
    span_requests: list[str] = []
    complete = 0
    for src in sources:
        store = BlockStore(downloads / "blocks" / src["event"], src["size"], BLOCK_SIZE)
        missing: set[int] = set()
        info = None
        try:
            info = locate_table(pe_h5.H5File(store, src["size"]), src)
        except MissingBlock as exc:
            missing.add(exc.index)
            if exc.index == 0:
                # First contact: the superblock, root and analysis symbol tables
                # and most dataset headers sit in the file head, so fetch 1 MiB
                # at once instead of discovering it block by block.
                missing.update(range(min(HEAD_PREFETCH_BLOCKS, store.block_count())))
        for first, last in coalesce(sorted(missing)):
            start = store.block_span(first)[0]
            end = store.block_span(last)[1]
            meta_requests.append("\t".join([src["url"], str(start), str(end - 1), str(store.directory),
                                            str(first), str(src["size"])]))
        if info is None:
            continue
        out = table_path(downloads, src)
        if out.is_file() and out.stat().st_size == src["table_bytes"]:
            complete += 1
            continue
        span_requests.append("\t".join([src["url"], str(src["table_offset"]),
                                        str(src["table_offset"] + src["table_bytes"] - 1),
                                        str(out), str(src["size"])]))
    Path(args.meta_requests).write_text("".join(r + "\n" for r in meta_requests), encoding="utf-8")
    Path(args.span_requests).write_text("".join(r + "\n" for r in span_requests), encoding="utf-8")
    print(f"plan complete_events={complete}/{len(sources)} meta_requests={len(meta_requests)} "
          f"span_requests={len(span_requests)}")
    return 0 if not meta_requests and not span_requests else 3


def coalesce(indices: list[int], max_gap: int = MAX_GAP_BLOCKS, max_run: int = MAX_RUN_BLOCKS) -> list[tuple[int, int]]:
    """Merge sorted block indices into inclusive runs (gaps of up to max_gap blocks are bridged)."""
    runs: list[tuple[int, int]] = []
    for index in indices:
        if runs and index - runs[-1][1] <= max_gap + 1 and index - runs[-1][0] < max_run:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


# ------------------------------------------------------------------- decode
def open_event(src: dict, downloads: Path) -> tuple[BlockStore, dict, bytes]:
    store = BlockStore(downloads / "blocks" / src["event"], src["size"], BLOCK_SIZE)
    info = locate_table(pe_h5.H5File(store, src["size"]), src)
    path = table_path(downloads, src)
    if not path.is_file() or path.stat().st_size != src["table_bytes"]:
        raise SystemExit(f"{src['event']}: table span {path} missing or truncated; rerun download.sh")
    return store, info, path.read_bytes()


def extract_columns(info: dict, table: bytes) -> dict[str, array.array]:
    """Primary path: strided memoryview casts of the row-major record table."""
    rows = info["shape"][0]
    width = info["dtype"]["size"] // 8
    allv = memoryview(table).cast("d")
    if len(allv) != rows * width:
        raise SystemExit("table length does not match shape x record size")
    out = {}
    for name in MEMBERS:
        k = info["offsets"][name] // 8
        out[name] = array.array("d", allv[k::width])
    return out


def check_column(event: str, name: str, values) -> tuple[float, float]:
    lo_b, hi_b = BOUNDS[name]
    lo = hi = None
    for v in values:
        if not math.isfinite(v):
            raise SystemExit(f"{event} {name}: non-finite value")
        if lo is None or v < lo:
            lo = v
        if hi is None or v > hi:
            hi = v
    if lo is None or lo == hi:
        raise SystemExit(f"{event} {name}: empty or constant column")
    if lo < lo_b or hi > hi_b:
        raise SystemExit(f"{event} {name}: range [{lo}, {hi}] outside sanity bounds [{lo_b}, {hi_b}]")
    return lo, hi


def sample_rel(event: str, name: str) -> str:
    return f"samples/{DATASET_ID}/{name}/{event}.f64"


# --------------------------------------------------------------- check-tables
def cmd_check_tables(args) -> int:
    """Semantic payload check used by download.sh (writes nothing)."""
    sources = read_sources(Path(args.sources))
    downloads = Path(args.downloads)
    total_rows = 0
    for src in sources:
        _store, info, table = open_event(src, downloads)
        cols = extract_columns(info, table)
        for name in MEMBERS:
            check_column(src["event"], name, cols[name])
        total_rows += info["shape"][0]
    print(f"tables_ok events={len(sources)} rows={total_rows} members_checked={len(MEMBERS)}")
    return 0


# -------------------------------------------------------------------- build
def cmd_build(args) -> int:
    sources = read_sources(Path(args.sources))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    for name in MEMBERS:
        d = data_root / "samples" / DATASET_ID / name
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*"):
            old.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    index_rows = []
    event_stats = []
    for src in sources:
        store, info, table = open_event(src, downloads)
        cols = extract_columns(info, table)
        m1, m2 = cols["mass_1_source"], cols["mass_2_source"]
        if any(b > a * (1 + 1e-12) for a, b in zip(m1, m2)):
            raise SystemExit(f"{src['event']}: mass_2_source exceeds mass_1_source")
        rows = info["shape"][0]
        if rows < MIN_ROWS:
            raise SystemExit(f"{src['event']}: only {rows} rows")
        col_stats = {}
        for name in MEMBERS:
            values = cols[name]
            lo, hi = check_column(src["event"], name, values)
            raw = values.tobytes()
            rel = sample_rel(src["event"], name)
            (data_root / rel).write_bytes(raw)
            distinct = len(set(raw[i:i + 8] for i in range(0, len(raw), 8)))
            col_stats[name] = {"min": lo, "max": hi, "distinct": distinct}
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": name, "sample_path": rel,
                "numeric_kind": "float", "bit_width": 64, "endianness": "little",
                "element_size_bytes": 8, "sample_size_bytes": len(raw), "value_count": len(values),
                "role": "primary", "event": src["event"], "source_file": src["key"],
                "source_dataset": f"{ANALYSIS}/{TABLE}", "source_member": name,
                "min": lo, "max": hi, "sha256": hashlib.sha256(raw).hexdigest(),
            })
        event_stats.append({"event": src["event"], "source_file": src["key"], "rows": rows,
                            "table_members": len(info["all_members"]), "metadata_blocks_used": len(store.used),
                            "columns": col_stats})
        print(f"built {src['event']} rows={rows} members={len(info['all_members'])} "
              f"m1_src=[{col_stats['mass_1_source']['min']:.2f},{col_stats['mass_1_source']['max']:.2f}] "
              f"dL=[{col_stats['luminosity_distance']['min']:.0f},{col_stats['luminosity_distance']['max']:.0f}]",
              flush=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in index_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    totals: dict[str, dict] = {}
    for row in index_rows:
        t = totals.setdefault(row["series_id"], {"sample_count": 0, "total_size_bytes": 0, "value_count": 0})
        t["sample_count"] += 1
        t["total_size_bytes"] += row["sample_size_bytes"]
        t["value_count"] += row["value_count"]
    stats_path.write_text(json.dumps({"dataset_id": DATASET_ID, "analysis": ANALYSIS, "members": MEMBERS,
                                      "series_totals": totals, "events": event_stats},
                                     indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for sid in MEMBERS:
        t = totals[sid]
        print(f"series {sid} samples={t['sample_count']} bytes={t['total_size_bytes']} values={t['value_count']}")
    print(f"total samples={len(index_rows)} bytes={sum(t['total_size_bytes'] for t in totals.values())}")
    return 0


# ------------------------------------------------------------------- verify
def cmd_verify(args) -> int:
    sources = read_sources(Path(args.sources))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path: dict[str, dict] = {}
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row["sample_path"] in by_path:
            raise SystemExit(f"bad or duplicate index row {row.get('sample_path')}")
        by_path[row["sample_path"]] = row
    expected_paths = set()
    for src in sources:
        _store, info, table = open_event(src, downloads)
        n = info["shape"][0]
        rec = info["dtype"]["size"]
        # independent extraction path: per-row struct.unpack_from at the member byte offset
        for name in MEMBERS:
            off = info["offsets"][name]
            expected = b"".join(table[r * rec + off:r * rec + off + 8] for r in range(n))
            rel = sample_rel(src["event"], name)
            expected_paths.add(rel)
            check_sample(data_root, by_path.get(rel), rel, expected, name, n, src["event"])
        m1 = struct.unpack(f"<{n}d", (data_root / sample_rel(src["event"], "mass_1_source")).read_bytes())
        m2 = struct.unpack(f"<{n}d", (data_root / sample_rel(src["event"], "mass_2_source")).read_bytes())
        if any(b > a * (1 + 1e-12) for a, b in zip(m1, m2)):
            raise SystemExit(f"{src['event']}: mass ordering violated")
        print(f"verified {src['event']} rows={n}", flush=True)
    if set(by_path) != expected_paths:
        diff = sorted(set(by_path) ^ expected_paths)[:5]
        raise SystemExit(f"index rows do not match expected samples (e.g. {diff})")
    on_disk = set()
    for p in (data_root / "samples" / DATASET_ID).rglob("*"):
        if p.is_file():
            on_disk.add(str(p.relative_to(data_root)))
    stray = on_disk - expected_paths
    if stray:
        raise SystemExit(f"stray sample files: {sorted(stray)[:5]}")
    declared = {s["id"] for s in manifest["series"]}
    if declared != set(MEMBERS):
        raise SystemExit(f"manifest series {sorted(declared)} != emitted {sorted(MEMBERS)}")
    for series in manifest["series"]:
        sel = [r for r in rows if r["series_id"] == series["id"]]
        count, size = len(sel), sum(r["sample_size_bytes"] for r in sel)
        if count != series["sample_count"] or size != series["total_size_bytes"]:
            raise SystemExit(f"manifest {series['id']}: sample_count/total_size {series['sample_count']}/"
                             f"{series['total_size_bytes']} != realized {count}/{size}")
        if series.get("role") != "primary" or series.get("source_field") != f"{ANALYSIS}/{TABLE}.{series['id']}":
            raise SystemExit(f"manifest {series['id']}: role/source_field mismatch")
        print(f"manifest_ok {series['id']} samples={count} bytes={size}")
    verify_control(sources, downloads, Path(args.control))
    print(f"verify ok samples={len(rows)} bytes={sum(r['sample_size_bytes'] for r in rows)}")
    return 0


def check_sample(data_root: Path, row: dict | None, rel: str, expected: bytes, series: str, count: int,
                 event: str) -> None:
    if row is None:
        raise SystemExit(f"missing index row for {rel}")
    data = (data_root / rel).read_bytes()
    if data != expected:
        raise SystemExit(f"{rel}: sample bytes differ from re-decoded source")
    want = {"series_id": series, "numeric_kind": "float", "bit_width": 64, "endianness": "little",
            "element_size_bytes": 8, "sample_size_bytes": len(data), "value_count": count}
    for key, value in want.items():
        if row.get(key) != value:
            raise SystemExit(f"{rel}: index {key}={row.get(key)!r} != {value!r}")
    if row.get("sha256") != hashlib.sha256(data).hexdigest():
        raise SystemExit(f"{rel}: sha256 mismatch")
    if count < MIN_ROWS:
        raise SystemExit(f"{rel}: only {count} values")
    values = struct.unpack(f"<{count}d", data)
    lo, hi = check_column(event, series, values)
    if row.get("min") != lo or row.get("max") != hi:
        raise SystemExit(f"{rel}: index min/max mismatch")


def verify_control(sources: list[dict], downloads: Path, control: Path) -> None:
    src = next((s for s in sources if s["event"] == CONTROL_EVENT), None)
    if src is None:
        raise SystemExit("control event missing from sources.tsv")
    if not control.is_file():
        raise SystemExit(f"control file {control} missing; rerun download.sh")
    data = control.read_bytes()
    if len(data) != src["size"] or hashlib.md5(data).hexdigest() != src["md5"]:
        raise SystemExit("control file size/MD5 mismatch with pinned record")
    store = BlockStore(downloads / "blocks" / src["event"], src["size"], BLOCK_SIZE)
    checked = 0
    for index in range(store.block_count()):
        if store.present(index):
            start, end = store.block_span(index)
            if store.block(index) != data[start:end]:
                raise SystemExit(f"control: metadata block {index} differs from the whole file")
            checked += 1
    if checked == 0:
        raise SystemExit("control: no metadata blocks to compare")
    span = table_path(downloads, src).read_bytes()
    if span != data[src["table_offset"]:src["table_offset"] + src["table_bytes"]]:
        raise SystemExit("control: table span differs from the whole file")
    whole = pe_h5.H5File(data, src["size"])
    info = locate_table(whole, src)
    if whole.read_rows(info) != span:
        raise SystemExit("control: whole-file table decode differs from the range span")
    print(f"control_ok {src['event']} md5={src['md5']} metadata_blocks_matched={checked} table_span_matched=1")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate-record")
    p.add_argument("--sources", required=True)
    p.add_argument("--record", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--sources", required=True)
    p.add_argument("--downloads", required=True)
    p.add_argument("--meta-requests", required=True)
    p.add_argument("--span-requests", required=True)
    p = sub.add_parser("check-tables")
    p.add_argument("--sources", required=True)
    p.add_argument("--downloads", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--downloads", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--stats", required=True)
        p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
            p.add_argument("--control", required=True)
    args = ap.parse_args()
    return {"validate-record": cmd_validate_record, "plan": cmd_plan, "check-tables": cmd_check_tables,
            "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
