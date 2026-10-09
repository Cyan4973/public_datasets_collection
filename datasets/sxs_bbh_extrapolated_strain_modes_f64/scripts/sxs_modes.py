#!/usr/bin/env python3
"""Plan, build and verify SXS:BBH Extrapolated_N2 strain-mode samples.

Subcommands
-----------
validate-record  check one saved Zenodo record JSON against its sims.tsv row
validate-meta    check one saved metadata.json (MD5, size, SXS identity)
plan             walk the HDF5 metadata of every pinned file through the local
                 block cache and list the 1 MiB range blocks still needed
                 (exit 3 while blocks are missing, 0 when complete)
build            decode the l<=4 N2 modes and emit raw little-endian samples
verify           re-decode independently and byte-compare every output

The parser never touches the network; ``download.sh`` fetches with curl.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blockstore import BLOCK_SIZE, BlockStore, MissingBlock  # noqa: E402
import sxs_h5  # noqa: E402

DATASET_ID = "sxs_bbh_extrapolated_strain_modes_f64"
GROUP = "Extrapolated_N2.dir"
L_MAX = 4
MODES = [(l, m) for l in range(2, L_MAX + 1) for m in range(-l, l + 1)]
PRIMARY = "sxs_bbh_rhoverm_n2_mode_reim_f64"
AUX_TIME = "sxs_bbh_rhoverm_n2_retarded_time_f64"
API = "https://zenodo.org/api/records"
# |h22| must peak within this window (in M) around the metadata common-horizon time.
PEAK_WINDOW = (-150.0, 250.0)
# Range requests: bridge gaps of up to 2 blocks (128 KiB), cap a request at 64 blocks (4 MiB).
MAX_GAP_BLOCKS = 2
MAX_RUN_BLOCKS = 64

if sys.byteorder != "little":
    raise SystemExit("this tool assumes a little-endian host")


def mode_name(l: int, m: int) -> str:
    return f"Y_l{l}_m{m}.dat"


def read_sims(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        for key in ("record_id", "lev", "h5_size", "meta_size"):
            row[key] = int(row[key])
        row["tag"] = row["sxs_id"].replace(":", "_")
        row["h5_url"] = f"{API}/{row['record_id']}/files/{row['h5_key']}/content"
        row["meta_url"] = f"{API}/{row['record_id']}/files/{row['meta_key']}/content"
        rows.append(row)
    if not rows or len({r["sxs_id"] for r in rows}) != len(rows):
        raise SystemExit("sims.tsv is empty or has duplicate simulations")
    return rows


def sim_by_tag(sims: list[dict], tag: str) -> dict:
    for row in sims:
        if row["tag"] == tag:
            return row
    raise SystemExit(f"unknown simulation tag {tag}")


# ---------------------------------------------------------------- validation
def cmd_validate_record(args) -> int:
    sim = sim_by_tag(read_sims(Path(args.sims)), args.tag)
    rec = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if int(rec.get("id", 0)) != sim["record_id"]:
        raise SystemExit(f"{sim['sxs_id']}: record id {rec.get('id')} != {sim['record_id']}")
    meta = rec.get("metadata") or {}
    if meta.get("title") != f"Binary black-hole simulation {sim['sxs_id']}":
        raise SystemExit(f"{sim['sxs_id']}: unexpected title {meta.get('title')!r}")
    lic = (meta.get("license") or {}).get("id")
    if lic != "cc-by-4.0":
        raise SystemExit(f"{sim['sxs_id']}: license changed to {lic!r}")
    files = {f["key"]: f for f in rec.get("files", [])}
    for key, size, md5 in ((sim["h5_key"], sim["h5_size"], sim["h5_md5"]),
                           (sim["meta_key"], sim["meta_size"], sim["meta_md5"])):
        item = files.get(key)
        if item is None:
            raise SystemExit(f"{sim['sxs_id']}: file {key} missing from record")
        if int(item["size"]) != size or item.get("checksum") != f"md5:{md5}":
            raise SystemExit(f"{sim['sxs_id']}: file {key} size/checksum changed")
    print(f"record_ok {sim['sxs_id']} record={sim['record_id']} license=cc-by-4.0 lev={sim['lev']}")
    return 0


def check_metadata(sim: dict, path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) != sim["meta_size"] or hashlib.md5(raw).hexdigest() != sim["meta_md5"]:
        raise SystemExit(f"{sim['sxs_id']}: metadata.json size/MD5 mismatch")
    meta = json.loads(raw)
    if sim["sxs_id"] not in (meta.get("alternative_names") or []):
        raise SystemExit(f"{sim['sxs_id']}: metadata.json does not name the simulation")
    if not str(meta.get("simulation_name", "")).endswith(f"/Lev{sim['lev']}"):
        raise SystemExit(f"{sim['sxs_id']}: metadata.json is not for Lev{sim['lev']}")
    return meta


def cmd_validate_meta(args) -> int:
    sim = sim_by_tag(read_sims(Path(args.sims)), args.tag)
    check_metadata(sim, Path(args.meta))
    print(f"metadata_ok {sim['sxs_id']} lev={sim['lev']}")
    return 0


# ---------------------------------------------------------------------- plan
def open_sim(sim: dict, downloads: Path) -> tuple[BlockStore, sxs_h5.H5File]:
    store = BlockStore(downloads / "blocks" / sim["tag"], sim["h5_size"], BLOCK_SIZE)
    return store, sxs_h5.H5File(store, sim["h5_size"])


def cmd_plan(args) -> int:
    sims = read_sims(Path(args.sims))
    downloads = Path(args.downloads)
    requests: list[str] = []
    complete = 0
    for sim in sims:
        store = BlockStore(downloads / "blocks" / sim["tag"], sim["h5_size"], BLOCK_SIZE)
        missing: set[int] = set()
        try:
            f = sxs_h5.H5File(store, sim["h5_size"])
            if f.eof != sim["h5_size"]:
                raise SystemExit(f"{sim['sxs_id']}: superblock EOF {f.eof} != pinned size")
            group = f.resolve(GROUP)
            deferred: list = []
            links = f.group_links(group, (MissingBlock,), deferred)
            f.attributes(group)
            if deferred:
                missing.update(exc.index for exc in deferred)
                links = None
        except MissingBlock as exc:
            missing.add(exc.index)
            links = None
        if links is not None:
            spans: list[tuple[int, int]] = []
            meta_ok = True
            for l, m in MODES:
                name = mode_name(l, m)
                if name not in links:
                    raise SystemExit(f"{sim['sxs_id']}: {GROUP}/{name} missing")
                try:
                    info = f.dataset(links[name])
                    if info["layout_class"] == 2:
                        spans += [(addr, size) for size, _mask, _off, addr in
                                  f.chunk_entries(info["chunk_btree"], len(info["shape"]))]
                    else:
                        spans.append((info["data_addr"], info["data_size"]))
                except MissingBlock as exc:
                    missing.add(exc.index)
                    meta_ok = False
            if meta_ok:
                for addr, size in spans:
                    for index in store.blocks_for(addr, size):
                        if not store.present(index):
                            missing.add(index)
        if not missing:
            complete += 1
        for first, last in coalesce(sorted(missing)):
            start = store.block_span(first)[0]
            end = store.block_span(last)[1]
            requests.append("\t".join([sim["h5_url"], str(start), str(end - 1), str(store.directory),
                                       str(first), str(sim["h5_size"])]))
    Path(args.requests).write_text("".join(r + "\n" for r in requests), encoding="utf-8")
    print(f"plan complete_sims={complete}/{len(sims)} block_requests={len(requests)}")
    return 0 if not requests else 3


def coalesce(indices: list[int], max_gap: int = MAX_GAP_BLOCKS, max_run: int = MAX_RUN_BLOCKS) -> list[tuple[int, int]]:
    """Merge sorted block indices into inclusive runs (gaps of up to max_gap blocks are bridged)."""
    runs: list[tuple[int, int]] = []
    for index in indices:
        if runs and index - runs[-1][1] <= max_gap + 1 and index - runs[-1][0] < max_run:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


# --------------------------------------------------------------------- decode
def decode_sim(sim: dict, downloads: Path) -> dict:
    store, f = open_sim(sim, downloads)
    if f.eof != sim["h5_size"]:
        raise SystemExit(f"{sim['sxs_id']}: superblock EOF mismatch")
    group = f.resolve(GROUP)
    links = f.group_links(group)
    attrs = f.attributes(group)
    modes = {}
    time_bytes = None
    rows = None
    for l, m in MODES:
        info = f.dataset(links[mode_name(l, m)])
        if info["dtype"] != {"kind": "float", "size": 8, "code": "d"}:
            raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: datatype is not float64 LE")
        shape = info["shape"]
        if len(shape) != 2 or shape[1] != 3 or shape[0] < 1000:
            raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: unexpected shape {shape}")
        if rows is None:
            rows = shape[0]
        elif shape[0] != rows:
            raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: row count {shape[0]} != {rows}")
        values = array.array("d")
        values.frombytes(f.read_array_bytes(info))
        t = values[0::3]
        reim = array.array("d", bytes(16 * rows))
        reim[0::2] = values[1::3]
        reim[1::2] = values[2::3]
        tb = t.tobytes()
        if time_bytes is None:
            time_bytes = tb
        elif tb != time_bytes:
            raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: time column differs from Y_l2_m-2")
        modes[(l, m)] = reim
    times = array.array("d")
    times.frombytes(time_bytes)
    return {"attrs": attrs, "modes": modes, "time": times, "rows": rows, "blocks_used": len(store.used)}


def physics_checks(sim: dict, meta: dict, decoded: dict) -> dict:
    times = decoded["time"]
    if not all(math.isfinite(x) for x in times):
        raise SystemExit(f"{sim['sxs_id']}: non-finite time value")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise SystemExit(f"{sim['sxs_id']}: time column is not strictly increasing")
    for (l, m), reim in decoded["modes"].items():
        if not all(math.isfinite(x) for x in reim):
            raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: non-finite value")
        if min(reim) == max(reim):
            raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: constant mode")
    h22 = decoded["modes"][(2, 2)]
    amp2 = [h22[2 * i] ** 2 + h22[2 * i + 1] ** 2 for i in range(decoded["rows"])]
    ipk = max(range(len(amp2)), key=amp2.__getitem__)
    peak_t, peak_amp = times[ipk], math.sqrt(amp2[ipk])
    cht = meta.get("common_horizon_time")
    if not isinstance(cht, (int, float)):
        raise SystemExit(f"{sim['sxs_id']}: metadata has no common_horizon_time")
    dt = peak_t - cht
    if not (PEAK_WINDOW[0] <= dt <= PEAK_WINDOW[1]):
        raise SystemExit(f"{sim['sxs_id']}: |h22| peak at t={peak_t:.2f} is {dt:+.2f} M from common horizon")
    if not (0.02 <= peak_amp <= 0.6):
        raise SystemExit(f"{sim['sxs_id']}: implausible |h22| peak {peak_amp}")
    com = meta.get("com_parameters")
    com_checked = False
    if isinstance(com, dict):
        for key in ("space_translation", "boost_velocity"):
            got, want = decoded["attrs"].get(key), com.get(key)
            if not isinstance(got, list) or not isinstance(want, list) or len(got) != len(want) or any(
                abs(a - b) > 1e-12 + 1e-9 * abs(b) for a, b in zip(got, want)
            ):
                raise SystemExit(f"{sim['sxs_id']}: N2 {key} {got} != metadata {want}")
        com_checked = True
    return {"h22_peak_time": peak_t, "h22_peak_amp": peak_amp, "common_horizon_time": cht,
            "peak_minus_common_horizon": dt, "com_parameters_checked": com_checked}


def sample_name(sim: dict, l: int | None = None, m: int | None = None) -> str:
    base = f"{sim['tag']}_Lev{sim['lev']}"
    return f"{base}_time.f64" if l is None else f"{base}_l{l}_m{m}.f64"


def stats_of(values: array.array) -> tuple[float, float]:
    return min(values), max(values)


# ---------------------------------------------------------------------- build
def cmd_build(args) -> int:
    sims = read_sims(Path(args.sims))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    samples = Path(args.samples_dir)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    for sub in (PRIMARY, AUX_TIME):
        d = samples / sub
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.f64"):
            old.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    index_rows = []
    sim_stats = []
    for sim in sims:
        meta = check_metadata(sim, downloads / "metadata" / f"{sim['tag']}.json")
        decoded = decode_sim(sim, downloads)
        phys = physics_checks(sim, meta, decoded)
        common = {"sxs_id": sim["sxs_id"], "record_id": sim["record_id"], "lev": sim["lev"],
                  "source_file": sim["h5_key"], "source_group": GROUP}
        for (l, m), reim in decoded["modes"].items():
            raw = reim.tobytes()
            out = samples / PRIMARY / sample_name(sim, l, m)
            out.write_bytes(raw)
            lo, hi = stats_of(reim)
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": PRIMARY,
                "sample_path": str(out.relative_to(data_root)),
                "numeric_kind": "float", "bit_width": 64, "endianness": "little",
                "element_size_bytes": 8, "sample_size_bytes": len(raw), "value_count": len(reim),
                "role": "primary", "shape": [decoded["rows"], 2], "axes": ["time_step", "re_im"],
                **common, "source_dataset": f"{GROUP}/{mode_name(l, m)}", "l": l, "m": m,
                "min": lo, "max": hi, "sha256": hashlib.sha256(raw).hexdigest(),
            })
        raw = decoded["time"].tobytes()
        out = samples / AUX_TIME / sample_name(sim)
        out.write_bytes(raw)
        lo, hi = stats_of(decoded["time"])
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": AUX_TIME,
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "float", "bit_width": 64, "endianness": "little",
            "element_size_bytes": 8, "sample_size_bytes": len(raw), "value_count": len(decoded["time"]),
            "role": "auxiliary", "shape": [decoded["rows"]], "axes": ["time_step"],
            **common, "source_dataset": f"{GROUP}/{mode_name(2, -2)}[:, 0]",
            "min": lo, "max": hi, "sha256": hashlib.sha256(raw).hexdigest(),
        })
        sim_stats.append({**common, "rows": decoded["rows"], "blocks_used": decoded["blocks_used"],
                          "reference_mass_ratio": meta.get("reference_mass_ratio"),
                          "reference_eccentricity": meta.get("reference_eccentricity"), **phys})
        print(f"built {sim['sxs_id']} Lev{sim['lev']} rows={decoded['rows']} "
              f"h22_peak={phys['h22_peak_amp']:.4f} at t-t_CH={phys['peak_minus_common_horizon']:+.1f}M "
              f"blocks={decoded['blocks_used']}", flush=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in index_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    totals = {}
    for row in index_rows:
        t = totals.setdefault(row["series_id"], {"sample_count": 0, "total_size_bytes": 0, "value_count": 0})
        t["sample_count"] += 1
        t["total_size_bytes"] += row["sample_size_bytes"]
        t["value_count"] += row["value_count"]
    stats_path.write_text(json.dumps({"dataset_id": DATASET_ID, "modes": [list(x) for x in MODES],
                                      "series_totals": totals, "simulations": sim_stats},
                                     indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for sid, t in sorted(totals.items()):
        print(f"series {sid} samples={t['sample_count']} bytes={t['total_size_bytes']} values={t['value_count']}")
    return 0


# --------------------------------------------------------------------- verify
def cmd_verify(args) -> int:
    sims = read_sims(Path(args.sims))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {}
    for row in rows:
        if row["dataset_id"] != DATASET_ID or row["sample_path"] in by_path:
            raise SystemExit(f"bad or duplicate index row {row['sample_path']}")
        by_path[row["sample_path"]] = row
    expected_paths = set()
    for sim in sims:
        meta = check_metadata(sim, downloads / "metadata" / f"{sim['tag']}.json")
        store, f = open_sim(sim, downloads)
        group = f.resolve(GROUP)
        links = f.group_links(group)
        time_ref = None
        for l, m in MODES:
            info = f.dataset(links[mode_name(l, m)])
            raw = f.read_array_bytes(info)
            n = info["shape"][0]
            # independent extraction path: struct row-unpacking instead of array slicing
            reim = bytearray()
            tcol = bytearray()
            for r in range(n):
                tcol += raw[24 * r:24 * r + 8]
                reim += raw[24 * r + 8:24 * r + 24]
            if time_ref is None:
                time_ref = bytes(tcol)
            elif bytes(tcol) != time_ref:
                raise SystemExit(f"{sim['sxs_id']} l{l}m{m}: time column mismatch")
            rel = f"samples/{DATASET_ID}/{PRIMARY}/{sample_name(sim, l, m)}"
            expected_paths.add(rel)
            check_sample(data_root, by_path.get(rel), rel, bytes(reim), PRIMARY, 2 * n)
        rel = f"samples/{DATASET_ID}/{AUX_TIME}/{sample_name(sim)}"
        expected_paths.add(rel)
        check_sample(data_root, by_path.get(rel), rel, time_ref, AUX_TIME, len(time_ref) // 8)
        tv = struct.unpack(f"<{len(time_ref) // 8}d", time_ref)
        if any(b <= a for a, b in zip(tv, tv[1:])):
            raise SystemExit(f"{sim['sxs_id']}: time not strictly increasing")
        h22 = struct.unpack(f"<{2 * len(tv)}d", (data_root / f"samples/{DATASET_ID}/{PRIMARY}/{sample_name(sim, 2, 2)}").read_bytes())
        amps = [math.hypot(h22[2 * i], h22[2 * i + 1]) for i in range(len(tv))]
        ipk = amps.index(max(amps))
        dt = tv[ipk] - meta["common_horizon_time"]
        if not (PEAK_WINDOW[0] <= dt <= PEAK_WINDOW[1]) or not (0.02 <= amps[ipk] <= 0.6):
            raise SystemExit(f"{sim['sxs_id']}: |h22| peak check failed (dt={dt}, amp={amps[ipk]})")
        print(f"verified {sim['sxs_id']} rows={len(tv)} h22_peak={amps[ipk]:.4f} dt={dt:+.1f}M", flush=True)
    if set(by_path) != expected_paths:
        extra = sorted(set(by_path) - expected_paths)[:5]
        raise SystemExit(f"index rows do not match expected samples (extra/missing e.g. {extra})")
    for sub in (PRIMARY, AUX_TIME):
        on_disk = {f"samples/{DATASET_ID}/{sub}/{p.name}" for p in (data_root / "samples" / DATASET_ID / sub).glob("*")}
        stray = on_disk - expected_paths
        if stray:
            raise SystemExit(f"stray sample files: {sorted(stray)[:5]}")
    for series in manifest["series"]:
        sel = [r for r in rows if r["series_id"] == series["id"]]
        count, size = len(sel), sum(r["sample_size_bytes"] for r in sel)
        if count != series["sample_count"] or size != series["total_size_bytes"]:
            raise SystemExit(f"manifest {series['id']}: sample_count/total_size {series['sample_count']}/"
                             f"{series['total_size_bytes']} != realized {count}/{size}")
        print(f"manifest_ok {series['id']} samples={count} bytes={size}")
    control = Path(args.control) if args.control else None
    if control is not None and control.exists():
        verify_control(sims, downloads, control)
    else:
        raise SystemExit("control file missing; rerun download.sh")
    print(f"verify ok samples={len(rows)}")
    return 0


def check_sample(data_root: Path, row: dict | None, rel: str, expected: bytes, series: str, count: int) -> None:
    if row is None:
        raise SystemExit(f"missing index row for {rel}")
    path = data_root / rel
    data = path.read_bytes()
    if data != expected:
        raise SystemExit(f"{rel}: sample bytes differ from re-decoded source")
    want = {"series_id": series, "numeric_kind": "float", "bit_width": 64, "endianness": "little",
            "element_size_bytes": 8, "sample_size_bytes": len(data), "value_count": count}
    for key, value in want.items():
        if row.get(key) != value:
            raise SystemExit(f"{rel}: index {key}={row.get(key)!r} != {value!r}")
    if row.get("sha256") != hashlib.sha256(data).hexdigest():
        raise SystemExit(f"{rel}: sha256 mismatch")
    values = struct.unpack(f"<{count}d", data)
    if not all(math.isfinite(v) for v in values):
        raise SystemExit(f"{rel}: non-finite values")
    lo, hi = min(values), max(values)
    if lo == hi:
        raise SystemExit(f"{rel}: constant sample")
    if row.get("min") != lo or row.get("max") != hi:
        raise SystemExit(f"{rel}: index min/max mismatch")


def verify_control(sims: list[dict], downloads: Path, control: Path) -> None:
    tag = control.name.split(".")[0]
    sim = sim_by_tag(sims, tag)
    data = control.read_bytes()
    if len(data) != sim["h5_size"] or hashlib.md5(data).hexdigest() != sim["h5_md5"]:
        raise SystemExit(f"control {control}: size/MD5 mismatch with pinned record")
    store = BlockStore(downloads / "blocks" / tag, sim["h5_size"], BLOCK_SIZE)
    checked = 0
    for index in range(store.block_count()):
        if store.present(index):
            start, end = store.block_span(index)
            if store.block(index) != data[start:end]:
                raise SystemExit(f"control: range block {index} of {tag} differs from the whole file")
            checked += 1
    if checked == 0:
        raise SystemExit("control: no range blocks to compare")
    print(f"control_ok {sim['sxs_id']} md5={sim['h5_md5']} range_blocks_matched={checked}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate-record")
    p.add_argument("--sims", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--record", required=True)
    p = sub.add_parser("validate-meta")
    p.add_argument("--sims", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--meta", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--sims", required=True)
    p.add_argument("--downloads", required=True)
    p.add_argument("--requests", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sims", required=True)
        p.add_argument("--downloads", required=True)
        p.add_argument("--samples-dir", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--stats", required=True)
        p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
            p.add_argument("--control", default="")
    args = ap.parse_args()
    return {"validate-record": cmd_validate_record, "validate-meta": cmd_validate_meta,
            "plan": cmd_plan, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
