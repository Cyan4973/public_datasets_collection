#!/usr/bin/env python3
"""Validate, build and verify The Well post-neutron-star-merger density snapshots.

Subcommands
  check-meta     validate the pinned Hugging Face revision/tree API responses
  check-headers  validate one curl header dump for an exact 206 byte range
  inspect-head   parse a file's fetched metadata ranges, validate the layout
  check-snapshot validate one fetched density snapshot (finite, >= 0, diverse)
  build          emit samples + index from local downloads only
  verify         independently re-derive and check the emitted samples

Network I/O is done by download.sh with curl; this module only parses local
files. Pure standard library.
"""

from __future__ import annotations

import argparse
import array
import collections
import hashlib
import json
import math
import re
import shutil
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from well_h5 import H5, H5Error, Sparse, is_f32le  # noqa: E402

DATASET_ID = "the_well_post_neutron_star_merger_density_f32"
SERIES_ID = "post_neutron_star_merger_density_f32"
REPO = "polymathic-ai/post_neutron_star_merger"
REVISION = "721253cd3220d158d3088c0cce4558dd444d1353"
LICENSE = "cc-by-4.0"
CARD_SHA256 = "77ae51977a87a5442d9ea0f37b50f68a8e1da273a69854d4a8769a22128bb635"

NR, NTH, NPH = 192, 128, 66
NT = 181
SNAPSHOT_VALUES = NR * NTH * NPH
SNAPSHOT_BYTES = SNAPSHOT_VALUES * 4
DUMPS = tuple(range(20, NT, 20))  # 20, 40, ..., 180

EXPECTED = {
    "file_size": 14_109_638_656,
    "head_range": (0, 65_535),
    "dims_range": (11_538_432, 11_541_093),
    "density_path": "/t0_fields/density",
    "density_shape": (1, NT, NR, NTH, NPH),
    "density_address": 16_777_216,
    "grid": (NR, NTH, NPH),
    "n_time": NT,
}

# Download-time sanity floors for any fetched snapshot (1,622,016 values).
MIN_DISTINCT = 100_000
MAX_MODE_FRACTION = 0.25
MAX_PHI_CONSTANT_ROW_FRACTION = 0.5
MIN_DYNAMIC_RANGE = 1.0e3
F32_INF_BITS = 0x7F800000

# Scope rule (evaluated on the fetched data in build and verify): a
# simulation file belongs to the family only if every selected dump holds an
# order-unity-normalized disk, i.e. its maximum density is >= 1e-2 code
# units. Files whose dumps all stay below are excluded; a mixed outcome is
# fatal. At the pinned revision this keeps scenarios 0, 1, 2, 3, 4, 7 (every
# dump max >= 0.057) and excludes 5 and 6 (every dump max <= 2.2e-5, a
# floor-dominated field whose top 1,000 values cover ~83% of cells).
DISK_MIN_MAX = 1.0e-2
EXPECTED_INCLUDED = (0, 1, 2, 3, 4, 7)

# Per-sample floors for emitted family samples. Realized: >= 1,321,525
# distinct values, modal value <= 3.6% of cells, <= 12.9% of (r, theta) rows
# constant along phi, >= 7.2 decades between max and min-positive.
FAMILY_MIN_DISTINCT_FRACTION = 0.5
FAMILY_MAX_MODE_FRACTION = 0.10
FAMILY_MAX_PHI_CONSTANT_ROW_FRACTION = 0.25
FAMILY_MIN_DYNAMIC_RANGE = 1.0e6


class RecipeError(RuntimeError):
    pass


# ----------------------------------------------------------------- sources
def load_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        row["scenario"] = int(row["scenario"])
        row["size_bytes"] = int(row["size_bytes"])
        rows.append(row)
    if [r["scenario"] for r in rows] != list(range(8)):
        raise RecipeError(f"sources.tsv must list scenarios 0..7 in order, got {[r['scenario'] for r in rows]}")
    return rows


# ------------------------------------------------------------ API metadata
def check_meta(revision_json: Path, tree_json: Path, readme: Path, sources: list[dict]) -> None:
    info = json.loads(revision_json.read_text(encoding="utf-8"))
    if info.get("id") != REPO or info.get("sha") != REVISION:
        raise RecipeError(f"unexpected repository/revision {info.get('id')!r} {info.get('sha')!r}")
    if info.get("private") or info.get("gated") not in (False, None):
        raise RecipeError(f"repository is private or gated: private={info.get('private')} gated={info.get('gated')}")
    card_license = (info.get("cardData") or {}).get("license")
    if card_license != LICENSE or f"license:{LICENSE}" not in (info.get("tags") or []):
        raise RecipeError(f"dataset card license changed: cardData={card_license!r} tags={info.get('tags')}")
    siblings = {s.get("rfilename") for s in info.get("siblings") or []}
    hdf5 = sorted(p for p in siblings if p and p.endswith(".hdf5"))
    if hdf5 != sorted(r["repo_path"] for r in sources):
        raise RecipeError(f"revision HDF5 listing differs from sources.tsv: {hdf5}")

    tree = json.loads(tree_json.read_text(encoding="utf-8"))
    files = {e["path"]: e for e in tree if e.get("type") == "file"}
    for row in sources:
        entry = files.get(row["repo_path"])
        if entry is None:
            raise RecipeError(f"tree API lacks {row['repo_path']}")
        lfs = entry.get("lfs") or {}
        if int(entry.get("size", -1)) != row["size_bytes"] or int(lfs.get("size", -1)) != row["size_bytes"]:
            raise RecipeError(f"size changed for {row['repo_path']}: {entry.get('size')}")
        if lfs.get("oid") != row["lfs_sha256"]:
            raise RecipeError(f"LFS sha256 changed for {row['repo_path']}: {lfs.get('oid')}")
        if entry.get("xetHash") not in (None, row["xet_hash"]):
            raise RecipeError(f"xet hash changed for {row['repo_path']}: {entry.get('xetHash')}")

    card = readme.read_bytes()
    if hashlib.sha256(card).hexdigest() != CARD_SHA256:
        raise RecipeError(f"dataset card at the pinned revision changed: sha256={hashlib.sha256(card).hexdigest()}")
    text = card.decode("utf-8")
    front = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not front or not re.search(rf"^license:\s*{re.escape(LICENSE)}\s*$", front.group(1), flags=re.MULTILINE):
        raise RecipeError("README front matter does not declare license: cc-by-4.0")
    if "Post neutron star merger" not in text or "192" not in text or "nubhlight" not in text.lower():
        raise RecipeError("README does not describe the post-neutron-star-merger nubhlight dataset")
    print(f"meta_validation=ok repo={REPO} revision={REVISION} license={LICENSE} files={len(sources)}")


# ------------------------------------------------------------ HTTP headers
def check_headers(text: str, start: int, end: int, total: int, identities: set[str]) -> None:
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    responses = [b for b in blocks if not re.match(r"^HTTP/\S+\s+200\s+Connection established", b, re.IGNORECASE)]
    if not responses:
        raise RecipeError("no HTTP response in header dump")
    final = responses[-1]
    status = re.match(r"^HTTP/\S+\s+(\d+)", final)
    if not status or status.group(1) != "206":
        raise RecipeError(f"expected HTTP 206 for range {start}-{end}, got {status.group(1) if status else '?'}")
    content_range = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, re.IGNORECASE | re.MULTILINE)
    if not content_range or tuple(map(int, content_range.groups())) != (start, end, total):
        raise RecipeError(f"Content-Range mismatch: expected {start}-{end}/{total}, got {content_range.groups() if content_range else None}")
    seen = set()
    for block in responses:
        for name in ("etag", "x-linked-etag", "x-xet-hash"):
            for match in re.finditer(rf"^{name}:\s*\"?([0-9a-fA-F]{{64}})\"?\s*$", block, re.IGNORECASE | re.MULTILINE):
                seen.add(match.group(1).lower())
    if not seen & identities:
        raise RecipeError(f"response chain carries no pinned content identity (saw {sorted(seen)})")


# ------------------------------------------------------------ HDF5 layout
def _increasing(values: list[float]) -> bool:
    return all(math.isfinite(v) for v in values) and all(b > a for a, b in zip(values, values[1:]))


def inspect_head(head: bytes, dims: bytes, expected: dict = EXPECTED) -> dict:
    """Parse the fetched metadata ranges and validate the pinned layout."""
    h0, h1 = expected["head_range"]
    d0, d1 = expected["dims_range"]
    if len(head) != h1 - h0 + 1 or len(dims) != d1 - d0 + 1:
        raise RecipeError(f"metadata range sizes {len(head)}/{len(dims)} differ from the pinned ranges")
    view = Sparse([(h0, head), (d0, dims)], expected["file_size"])
    try:
        h5 = H5(view)
        tree = h5.tree()
        root_attrs = h5.attributes(h5.messages(h5.root_header))
        need = [expected["density_path"], "/dimensions/time", "/dimensions/log_r", "/dimensions/theta",
                "/dimensions/phi", "/scalars/a", "/scalars/mbh"]
        missing = [p for p in need if p not in tree]
        if missing:
            raise RecipeError(f"missing HDF5 objects {missing}")
        dens = h5.dataset(tree[expected["density_path"]])
        if tuple(dens["shape"]) != expected["density_shape"]:
            raise RecipeError(f"density shape {dens['shape']} != {expected['density_shape']}")
        if not is_f32le(dens["datatype"]):
            raise RecipeError(f"density datatype is not IEEE F32LE: {bytes(dens['datatype']).hex()}")
        if dens["filters"]:
            raise RecipeError(f"density has a filter pipeline {dens['filters']}")
        if dens["layout_class"] != 1:
            raise RecipeError(f"density layout class {dens['layout_class']} is not contiguous")
        nvalues = math.prod(expected["density_shape"])
        if dens["address"] != expected["density_address"] or dens["size"] != nvalues * 4:
            raise RecipeError(f"density storage {dens['address']}+{dens['size']} differs from the pinned layout")
        if dens["address"] + dens["size"] > expected["file_size"]:
            raise RecipeError("density storage runs past end of file")

        def vector(path: str, length: int | None) -> list[float]:
            info = h5.dataset(tree[path])
            if not is_f32le(info["datatype"]) or info["filters"] or info["layout_class"] != 1:
                raise RecipeError(f"{path} is not an unfiltered contiguous F32LE dataset")
            shape = tuple(info["shape"])
            if (length is None and shape != ()) or (length is not None and shape != (length,)):
                raise RecipeError(f"{path} shape {shape} unexpected")
            if not (d0 <= info["address"] and info["address"] + info["size"] <= d1 + 1):
                raise RecipeError(f"{path} storage lies outside the pinned dims range")
            return [float(v) for v in h5.read_values(info)]

        grid = expected["grid"]
        time = vector("/dimensions/time", expected["n_time"])
        log_r = vector("/dimensions/log_r", grid[0])
        theta = vector("/dimensions/theta", grid[1])
        phi = vector("/dimensions/phi", grid[2])
        spin = vector("/scalars/a", None)[0]
        mbh_g = vector("/scalars/mbh", None)[0]
    except H5Error as exc:
        raise RecipeError(f"HDF5 metadata error: {exc}") from exc
    for name, values in (("time", time), ("log_r", log_r), ("theta", theta), ("phi", phi)):
        if not _increasing(values):
            raise RecipeError(f"/dimensions/{name} is not finite and strictly increasing")
    if not (theta[0] == 0.0 and theta[-1] == 1.0 and phi[0] == 0.0 and abs(phi[-1] - 2 * math.pi) < 1e-5):
        raise RecipeError("theta/phi code-coordinate extents changed")
    if not (0.0 <= spin < 1.0 and mbh_g > 0 and math.isfinite(mbh_g)):
        raise RecipeError(f"implausible black-hole scalars a={spin} mbh={mbh_g}")
    a_attr, m_attr = root_attrs.get("a"), root_attrs.get("mbh")
    if not isinstance(a_attr, float) or not isinstance(m_attr, float) or abs(a_attr - spin) > 1e-6:
        raise RecipeError(f"root attributes a/mbh missing or inconsistent: {a_attr!r} {m_attr!r}")
    return {
        "superblock_version": h5.superblock_version,
        "density_address": dens["address"],
        "density_size": dens["size"],
        "density_shape": list(dens["shape"]),
        "time": time,
        "log_r_extent": [log_r[0], log_r[-1]],
        "bh_spin_a": a_attr,
        "bh_mass_msun": m_attr,
        "bh_mass_grams_f32": mbh_g,
    }


def snapshot_offset(layout: dict, dump: int) -> int:
    return int(layout["density_address"]) + dump * SNAPSHOT_BYTES


# --------------------------------------------------------- snapshot checks
def f32_from_bits(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits))[0]


def snapshot_stats(raw: bytes, grid: tuple[int, int, int] = (NR, NTH, NPH)) -> dict:
    nr, nth, nph = grid
    count = nr * nth * nph
    if len(raw) != count * 4:
        raise RecipeError(f"snapshot has {len(raw)} bytes, expected {count * 4}")
    bits = array.array("I")
    bits.frombytes(raw)
    if sys.byteorder != "little":
        bits.byteswap()
    hi, lo = max(bits), min(bits)
    # For IEEE binary32, "finite and non-negative (no -0.0)" is exactly
    # "bit pattern below the +inf pattern"; on that set the unsigned bit
    # order equals the numeric order, so min/max of the bits give min/max.
    if hi >= F32_INF_BITS:
        bad = sum(1 for b in bits if b >= F32_INF_BITS)
        raise RecipeError(f"{bad} values are negative, -0.0, infinite or NaN")
    distinct = collections.Counter(bits)
    mode_bits, mode_count = distinct.most_common(1)[0]
    constant_rows = 0
    for row in range(nr * nth):
        start = row * nph
        if bits[start : start + nph].count(bits[start]) == nph:
            constant_rows += 1
    positive_bits = [b for b in distinct if b > 0]
    if not positive_bits:
        raise RecipeError("snapshot has no positive values")
    min_positive_bits = lo if lo > 0 else min(positive_bits)
    return {
        "value_count": count,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "min": f32_from_bits(lo),
        "max": f32_from_bits(hi),
        "min_positive": f32_from_bits(min_positive_bits),
        "zero_values": distinct.get(0, 0),
        "distinct_values": len(distinct),
        "mode_value": f32_from_bits(mode_bits),
        "mode_value_count": mode_count,
        "phi_constant_rows": constant_rows,
        "phi_constant_row_fraction": round(constant_rows / (nr * nth), 6),
    }


def check_stats(stats: dict) -> None:
    count = stats["value_count"]
    if stats["distinct_values"] < MIN_DISTINCT:
        raise RecipeError(f"only {stats['distinct_values']} distinct values (< {MIN_DISTINCT})")
    if stats["mode_value_count"] > MAX_MODE_FRACTION * count:
        raise RecipeError(f"modal value covers {stats['mode_value_count']}/{count} cells")
    if stats["phi_constant_row_fraction"] > MAX_PHI_CONSTANT_ROW_FRACTION:
        raise RecipeError(f"{stats['phi_constant_row_fraction']:.1%} of (r, theta) rows are constant along phi")
    if not (stats["max"] > 0 and stats["max"] / stats["min_positive"] >= MIN_DYNAMIC_RANGE):
        raise RecipeError(f"dynamic range {stats['min_positive']}..{stats['max']} is degenerate")


def check_family_stats(stats: dict) -> None:
    """Stricter per-sample floors for snapshots that are emitted."""
    check_stats(stats)
    count = stats["value_count"]
    if stats["distinct_values"] < FAMILY_MIN_DISTINCT_FRACTION * count:
        raise RecipeError(f"family floor: {stats['distinct_values']} distinct values < {FAMILY_MIN_DISTINCT_FRACTION:.0%} of cells")
    if stats["mode_value_count"] > FAMILY_MAX_MODE_FRACTION * count:
        raise RecipeError(f"family floor: modal value covers {stats['mode_value_count']}/{count} cells")
    if stats["phi_constant_row_fraction"] > FAMILY_MAX_PHI_CONSTANT_ROW_FRACTION:
        raise RecipeError(f"family floor: {stats['phi_constant_row_fraction']:.1%} of rows constant along phi")
    if stats["max"] / stats["min_positive"] < FAMILY_MIN_DYNAMIC_RANGE:
        raise RecipeError(f"family floor: dynamic range {stats['min_positive']}..{stats['max']} < {FAMILY_MIN_DYNAMIC_RANGE:g}")
    if stats["max"] < DISK_MIN_MAX:
        raise RecipeError(f"family floor: max density {stats['max']} < {DISK_MIN_MAX}")


def public_stats(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if not k.startswith("_")}


def float_domain_max(raw: bytes) -> float:
    """Maximum via a float decode (independent of the bit-pattern path)."""
    floats = array.array("f")
    floats.frombytes(raw)
    if sys.byteorder != "little":
        floats.byteswap()
    if not all(map(math.isfinite, floats)):
        raise RecipeError("snapshot has non-finite values")
    return max(floats)


# -------------------------------------------------------------- build/verify
def scenario_dir(downloads: Path, scenario: int) -> Path:
    return downloads / f"scenario_{scenario}"


def snapshot_name(dump: int) -> str:
    return f"density_dump{dump:03d}.f32le"


def sample_name(scenario: int, dump: int) -> str:
    return f"scenario_{scenario}_dump{dump:03d}.bin"


def local_layout(downloads: Path, scenario: int) -> dict:
    sdir = scenario_dir(downloads, scenario)
    return inspect_head((sdir / "head.bin").read_bytes(), (sdir / "dims.bin").read_bytes())


def scope_decision(downloads: Path, sources: list[dict]) -> dict[int, dict]:
    """Apply the disk-presence scope rule to every fetched file."""
    decisions: dict[int, dict] = {}
    for src in sources:
        sdir = scenario_dir(downloads, src["scenario"])
        maxima = [float_domain_max((sdir / snapshot_name(dump)).read_bytes()) for dump in DUMPS]
        above = [m >= DISK_MIN_MAX for m in maxima]
        if all(above):
            included = True
        elif not any(above):
            included = False
        else:
            raise RecipeError(f"scenario {src['scenario']}: mixed disk-presence outcome {maxima}; review the scope rule")
        decisions[src["scenario"]] = {"included": included, "dump_max": maxima}
    included = tuple(s for s, d in decisions.items() if d["included"])
    if included != EXPECTED_INCLUDED:
        raise RecipeError(f"scope rule now includes scenarios {included}, expected {EXPECTED_INCLUDED}")
    return decisions


def expected_rows(downloads: Path, sources: list[dict], data_root: Path, samples_dir: Path,
                  decisions: dict[int, dict]) -> list[dict]:
    rows = []
    for src in sources:
        if not decisions[src["scenario"]]["included"]:
            continue
        layout = local_layout(downloads, src["scenario"])
        for dump in DUMPS:
            path = samples_dir / SERIES_ID / sample_name(src["scenario"], dump)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(path.relative_to(data_root)),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": SNAPSHOT_BYTES,
                "value_count": SNAPSHOT_VALUES,
                "sample_shape": [NR, NTH, NPH],
                "sample_axes": ["log_r", "theta", "phi"],
                "scenario": src["scenario"],
                "split": src["split"],
                "source_url": f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{src['repo_path']}",
                "source_lfs_sha256": src["lfs_sha256"],
                "hdf5_dataset": "/t0_fields/density",
                "dump_index": dump,
                "code_time": layout["time"][dump],
                "source_byte_offset": snapshot_offset(layout, dump),
                "bh_spin_a": layout["bh_spin_a"],
                "bh_mass_msun": layout["bh_mass_msun"],
                "_download": str(scenario_dir(downloads, src["scenario"]) / snapshot_name(dump)),
            })
    return rows


def build(args) -> None:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    samples_dir = Path(args.samples_dir)
    sources = load_sources(Path(args.sources))
    out_dir = samples_dir / SERIES_ID
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions = scope_decision(downloads, sources)
    excluded_stats = {}
    for scenario, decision in decisions.items():
        print(f"scope scenario={scenario} included={decision['included']} "
              f"dump_max_range={min(decision['dump_max']):.3e}..{max(decision['dump_max']):.3e}")
        if not decision["included"]:
            sdir = scenario_dir(downloads, scenario)
            per_dump = [snapshot_stats((sdir / snapshot_name(d)).read_bytes()) for d in DUMPS]
            excluded_stats[str(scenario)] = {
                "distinct_values_min": min(s["distinct_values"] for s in per_dump),
                "distinct_values_max": max(s["distinct_values"] for s in per_dump),
                "max": max(s["max"] for s in per_dump),
                "min": min(s["min"] for s in per_dump),
                "phi_constant_row_fraction_max": max(s["phi_constant_row_fraction"] for s in per_dump),
            }
    rows = expected_rows(downloads, sources, data_root, samples_dir, decisions)
    index_rows = []
    hashes: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for row in rows:
        raw = Path(row["_download"]).read_bytes()
        stats = snapshot_stats(raw)
        check_family_stats(stats)
        if stats["sha256"] in hashes:
            raise RecipeError(f"{row['sample_path']} duplicates {hashes[stats['sha256']]}")
        hashes[stats["sha256"]] = row["sample_path"]
        tmp = data_root / (row["sample_path"] + ".part")
        tmp.write_bytes(raw)
        tmp.rename(data_root / row["sample_path"])
        aggregate.update(raw)
        out = {k: v for k, v in row.items() if not k.startswith("_")}
        out.update(public_stats(stats))
        index_rows.append(out)
        print(f"sample {row['sample_path']} t={row['code_time']:.1f} min={stats['min']:.3e} max={stats['max']:.3e} "
              f"distinct={stats['distinct_values']} phi_const_rows={stats['phi_constant_row_fraction']:.4f}")
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    tmp_index = index.with_suffix(".jsonl.part")
    tmp_index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows), encoding="utf-8")
    tmp_index.rename(index)
    summary = summarize(index_rows, aggregate.hexdigest())
    summary["scope_rule"] = {
        "rule": f"include a file only if every selected dump has max density >= {DISK_MIN_MAX} code units",
        "decisions": {str(s): d for s, d in decisions.items()},
        "included_scenarios": [s for s, d in decisions.items() if d["included"]],
        "excluded_scenario_stats": excluded_stats,
    }
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("sample_count", "total_values", "total_bytes", "aggregate_sha256")}, sort_keys=True))


def summarize(index_rows: list[dict], aggregate_sha256: str) -> dict:
    per_scenario = {}
    for r in index_rows:
        s = per_scenario.setdefault(str(r["scenario"]), {
            "split": r["split"], "bh_spin_a": r["bh_spin_a"], "bh_mass_msun": r["bh_mass_msun"],
            "samples": 0, "min": math.inf, "max": -math.inf, "distinct_min": math.inf,
            "phi_constant_row_fraction_max": 0.0})
        s["samples"] += 1
        s["min"] = min(s["min"], r["min"])
        s["max"] = max(s["max"], r["max"])
        s["distinct_min"] = min(s["distinct_min"], r["distinct_values"])
        s["phi_constant_row_fraction_max"] = max(s["phi_constant_row_fraction_max"], r["phi_constant_row_fraction"])
    distinct = sorted(r["distinct_values"] for r in index_rows)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "revision": REVISION,
        "dumps": list(DUMPS),
        "sample_count": len(index_rows),
        "total_values": sum(r["value_count"] for r in index_rows),
        "total_bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "aggregate_sha256": aggregate_sha256,
        "global_min": min(r["min"] for r in index_rows),
        "global_max": max(r["max"] for r in index_rows),
        "distinct_values_per_sample": {"min": distinct[0], "median": distinct[len(distinct) // 2], "max": distinct[-1]},
        "phi_constant_row_fraction_max": max(r["phi_constant_row_fraction"] for r in index_rows),
        "zero_values_total": sum(r["zero_values"] for r in index_rows),
        "per_scenario": per_scenario,
    }


def verify(args) -> None:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    samples_dir = Path(args.samples_dir)
    sources = load_sources(Path(args.sources))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1 or series[0].get("role") != "primary":
        raise RecipeError("manifest must declare exactly the one primary density series")
    series = series[0]
    decisions = scope_decision(downloads, sources)
    expected = expected_rows(downloads, sources, data_root, samples_dir, decisions)
    index_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index_rows) != len(expected):
        raise RecipeError(f"index has {len(index_rows)} rows, expected {len(expected)}")
    on_disk = sorted(str(p.relative_to(data_root)) for p in samples_dir.rglob("*") if p.is_file())
    if on_disk != sorted(r["sample_path"] for r in expected):
        raise RecipeError("sample directory contents differ from the expected sample set")
    hashes = set()
    aggregate = hashlib.sha256()
    total_bytes = 0
    for want, got in zip(expected, index_rows):
        for key, value in want.items():
            if key.startswith("_"):
                continue
            if got.get(key) != value:
                raise RecipeError(f"index field {key} for {want['sample_path']}: {got.get(key)!r} != {value!r}")
        sample = (data_root / want["sample_path"]).read_bytes()
        source = Path(want["_download"]).read_bytes()
        if sample != source:
            raise RecipeError(f"{want['sample_path']} differs from its downloaded source range")
        stats = public_stats(snapshot_stats(sample))
        check_family_stats(stats)
        for key, value in stats.items():
            if got.get(key) != value:
                raise RecipeError(f"recomputed {key} for {want['sample_path']}: {value!r} != index {got.get(key)!r}")
        # Second, float-domain decode path (independent of the bit tricks
        # used by snapshot_stats): finite, >= 0, no -0.0, same extrema.
        floats = array.array("f")
        floats.frombytes(sample)
        if sys.byteorder != "little":
            floats.byteswap()
        if not all(map(math.isfinite, floats)):
            raise RecipeError(f"{want['sample_path']} has non-finite values")
        lo, hi = min(floats), max(floats)
        if lo < 0 or any(v == 0.0 and math.copysign(1.0, v) < 0 for v in floats if v == 0.0):
            raise RecipeError(f"{want['sample_path']} has negative values")
        if (lo, hi) != (got["min"], got["max"]):
            raise RecipeError(f"{want['sample_path']} float-domain extrema {lo}/{hi} != index {got['min']}/{got['max']}")
        if stats["sha256"] in hashes:
            raise RecipeError(f"duplicate sample content {want['sample_path']}")
        hashes.add(stats["sha256"])
        aggregate.update(sample)
        total_bytes += len(sample)
    if series["sample_count"] != len(index_rows) or series["total_size_bytes"] != total_bytes:
        raise RecipeError(f"manifest totals {series['sample_count']}/{series['total_size_bytes']} != realized {len(index_rows)}/{total_bytes}")
    recorded = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if recorded.get("aggregate_sha256") != aggregate.hexdigest() or recorded.get("total_bytes") != total_bytes:
        raise RecipeError("ingest stats disagree with the verified samples")
    if recorded.get("scope_rule", {}).get("decisions") != {str(s): d for s, d in decisions.items()}:
        raise RecipeError("recorded scope-rule decisions disagree with the re-derived ones")
    if {r["scenario"] for r in index_rows} != set(EXPECTED_INCLUDED):
        raise RecipeError("index scenarios differ from the scope-rule outcome")
    print(f"verify_ok samples={len(index_rows)} bytes={total_bytes} aggregate_sha256={aggregate.hexdigest()}")


# --------------------------------------------------------------------- cli
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check-meta")
    p.add_argument("--revision-json", required=True)
    p.add_argument("--tree-json", required=True)
    p.add_argument("--readme", required=True)
    p.add_argument("--sources", required=True)

    p = sub.add_parser("check-headers")
    p.add_argument("--headers", required=True)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--total", type=int, required=True)
    p.add_argument("--identity", action="append", required=True)

    p = sub.add_parser("inspect-head")
    p.add_argument("--head", required=True)
    p.add_argument("--dims", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("snapshot-offset")
    p.add_argument("--layout", required=True)
    p.add_argument("--dump", type=int, required=True)

    p = sub.add_parser("check-snapshot")
    p.add_argument("--file", required=True)

    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--downloads", required=True)
        p.add_argument("--samples-dir", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--stats", required=True)
        p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)

    args = parser.parse_args()
    try:
        if args.cmd == "check-meta":
            check_meta(Path(args.revision_json), Path(args.tree_json), Path(args.readme), load_sources(Path(args.sources)))
        elif args.cmd == "check-headers":
            check_headers(Path(args.headers).read_text(encoding="iso-8859-1"), args.start, args.end, args.total,
                          {i.lower() for i in args.identity})
        elif args.cmd == "inspect-head":
            layout = inspect_head(Path(args.head).read_bytes(), Path(args.dims).read_bytes())
            out = Path(args.out)
            out.with_suffix(".part").write_text(json.dumps(layout, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            out.with_suffix(".part").rename(out)
            print(f"layout_ok density={layout['density_address']}+{layout['density_size']} "
                  f"times={len(layout['time'])} a={layout['bh_spin_a']} mbh={layout['bh_mass_msun']}")
        elif args.cmd == "snapshot-offset":
            layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
            if not (0 <= args.dump < NT):
                raise RecipeError(f"dump {args.dump} out of range")
            print(snapshot_offset(layout, args.dump))
        elif args.cmd == "check-snapshot":
            stats = snapshot_stats(Path(args.file).read_bytes())
            check_stats(stats)
            print(f"snapshot_ok min={stats['min']:.4e} max={stats['max']:.4e} distinct={stats['distinct_values']} "
                  f"phi_const_rows={stats['phi_constant_row_fraction']:.4f}")
        elif args.cmd == "build":
            build(args)
        elif args.cmd == "verify":
            verify(args)
    except (RecipeError, H5Error) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
