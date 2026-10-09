#!/usr/bin/env python3
"""Compression-behavior similarity between numeric families.

Two families are similar when BOTH hold for the same existing family:
1. compression equivalence: its trained OpenZL compressor compresses the
   candidate nearly as well as the candidate's own compressor does (the
   downstream near-duplicate test, zl_classifier/scripts/group_compressors.py);
2. statistical proximity: their feature fingerprints are close. Fingerprints
   use the Transformer's numeric features (libfeature_extract.so, V2) plus
   order-0, order-1 conditional, delta and byte-lane entropies, normalized to
   be scale-free and taken as the median over samples.
Both are measured on bytes, so no name or tag can change the outcome.

For every family the tool trains a Pareto set with `zli train` on half the
samples, keeps the member with the best ratio on the other (held-out) half as
the family's compressor, and records that ratio. A candidate is measured by
compressing its held-out half with every library compressor of the same width.

Commands:
  zlsim.py build-library [--widths 8,16,32,64] [--jobs 48] [--sources downstream,local]
  zlsim.py measure <dataset_id> [--jobs 32]              # local recipe, every primary series
  zlsim.py calibrate [--jobs 48]                          # the autocollect acceptances, in order
  zlsim.py gate <recipe_dir> [--jobs 16]                  # production breadth test (JSON; exit 3 if redundant)
  zlsim.py adopt <dataset_id>                             # move an accepted candidate into the library

Gate rule (calibrated 2026-10-08 on 282 same-material mirror pairs vs 11,755
random pairs): a series is redundant if an existing family of the same width
is within REDUNDANT_LOSS compression loss AND REDUNDANT_DISTANCE percentile
feature distance. A recipe is redundant when all its primary series are.
State lives under .data/zlsim/ (library/<width>/<key>/winner.zc + meta.json).
"""
from __future__ import annotations

import argparse
import array
import collections
import concurrent.futures
import csv
import ctypes
import math
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / ".data"
ZLSIM_DIR = DATA_ROOT / "zlsim"
LIBRARY_DIR = ZLSIM_DIR / "library"
CANDIDATE_DIR = ZLSIM_DIR / "candidates"
REDUNDANT_LOSS = 0.03
REDUNDANT_DISTANCE = 0.05      # ~p85-90 of same-material pairs, <p1 of unrelated pairs
STRONG_DISTANCE = 0.12         # ~p5 of unrelated pairs
GATE_NEIGHBORS = 10
FILL_WARNING_SHARE = 0.8
WORK_DIR = ZLSIM_DIR / "work"
DOWNSTREAM = REPO_ROOT.parent / "training_data" / "numeric_datasets"
ZLI = Path(os.environ.get("ZLSIM_ZLI", REPO_ROOT.parent / "zl_classifier" / "zli"))
PROFILES = {8: "serial", 16: "le-u16", 32: "le-u32", 64: "le-u64"}
WIDTHS = (8, 16, 32, 64)
FEATURE_LIB = Path(os.environ.get("ZLSIM_FEATURE_LIB", REPO_ROOT.parent / "transformer" / "training" / "feature_native" / "libfeature_extract.so"))
FEATURE_SAMPLES = 12
FEATURE_ELEMENTS = 262_144
SIDE_BYTES = 16 * 1024 * 1024
SIDE_FILES = 48
TRAIN_TIMEOUT_S = 30 * 60
PARETO_TIMEOUT_S = int(os.environ.get("ZLSIM_PARETO_TIMEOUT_S", str(TRAIN_TIMEOUT_S)))
TRAIN_THREADS = int(os.environ.get("ZLSIM_TRAIN_THREADS", "2"))


def sample_files(directory: Path) -> list[Path]:
    """Sample files of a family, including nested layouts (per-year folders etc.)."""
    return sorted(path for path in directory.rglob("*") if path.is_file())


def element_bytes(width: int) -> int:
    return width // 8


class _V2(ctypes.Structure):
    _fields_ = (
        [(name, ctypes.c_uint64) for name in ("count", "max_run_length", "zero_count", "delta_up_count", "delta_down_count", "min_u", "max_u")]
        + [("min_s", ctypes.c_int64), ("max_s", ctypes.c_int64)]
        + [(name, ctypes.c_uint64) for name in ("max_abs_delta_u", "max_abs_delta_s", "range_u", "range_s", "cardinality_est",
                                               "pair_cardinality_est", "d8_cardinality_est", "min_lb0", "match4")]
        + [(name, ctypes.c_double) for name in ("sum_u", "sum_s", "delta_min_s", "delta_max_s", "mean_u", "mean_s", "mean_abs_dev_u",
                                               "mean_abs_dev_s", "mean_abs_delta_u", "zero_ratio", "delta_up_ratio", "delta_down_ratio",
                                               "sorted_gap_nmad", "sorted_gap_mode", "transition_gap_cv")]
        + [("elt_width", ctypes.c_size_t)]
    )


_FEATURE_FN = None


def _feature_fn():
    global _FEATURE_FN
    if _FEATURE_FN is None:
        lib = ctypes.CDLL(str(FEATURE_LIB))
        lib.NumericFeaturesV2_extract_from_bytes.restype = _V2
        lib.NumericFeaturesV2_extract_from_bytes.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        _FEATURE_FN = lib.NumericFeaturesV2_extract_from_bytes
    return _FEATURE_FN


def _entropy(counter: collections.Counter, total: int) -> float:
    return -sum(c / total * math.log2(c / total) for c in counter.values()) if total else 0.0


def sample_features(raw: bytes, width: int) -> dict[str, float]:
    """Scale-free fingerprint of one sample: Transformer V2 features plus
    explicit entropies, each mapped to roughly [0, 1]."""
    element = width // 8
    raw = raw[: len(raw) // element * element]
    v2 = _feature_fn()(raw, len(raw), element)
    n = max(int(v2.count), 2)
    log_n = math.log2(n + 1)
    bits = lambda value: math.log2(float(value) + 1) / width  # noqa: E731
    values = array.array({1: "B", 2: "H", 4: "I", 8: "Q"}[element])
    values.frombytes(raw)
    h0 = _entropy(collections.Counter(values), len(values))
    pairs = collections.Counter(zip(values, values[1:]))
    h_pairs = _entropy(pairs, max(len(values) - 1, 1))
    mask = (1 << width) - 1
    deltas = collections.Counter((b - a) & mask for a, b in zip(values, values[1:]))
    lanes, lane_h1 = [], []
    for k in range(element):
        lane = raw[k::element]
        h_lane = _entropy(collections.Counter(lane), len(lane))
        lanes.append(h_lane / 8)
        # Order-1 conditional entropy within the lane: 65,536 pair bins, well
        # sampled even when whole values are all distinct.
        lane_h1.append(max(0.0, _entropy(collections.Counter(zip(lane, lane[1:])), max(len(lane) - 1, 1)) - h_lane) / 8)
    return {
        "card_frac": math.log2(v2.cardinality_est + 1) / log_n,
        "card_bits": bits(v2.cardinality_est),
        "pair_card_frac": math.log2(v2.pair_cardinality_est + 1) / log_n,
        "d8_card_frac": math.log2(v2.d8_cardinality_est + 1) / math.log2(len(raw) + 1),
        "range_u_bits": bits(v2.range_u),
        "range_s_bits": bits(v2.range_s),
        "mad_s_bits": bits(v2.mean_abs_dev_s),
        "mean_abs_delta_bits": bits(v2.mean_abs_delta_u),
        "max_abs_delta_bits": bits(v2.max_abs_delta_s),
        "zero_ratio": v2.zero_ratio,
        "delta_up_ratio": v2.delta_up_ratio,
        "delta_flat_ratio": max(0.0, 1.0 - v2.delta_up_ratio - v2.delta_down_ratio),
        "run_frac": math.log2(v2.max_run_length + 1) / log_n,
        "trailing_zero_bits": v2.min_lb0 / width,
        "match4_rate": min(1.0, v2.match4 / n),
        "sorted_gap_nmad": math.log1p(max(v2.sorted_gap_nmad, 0.0)) / 4,
        "sorted_gap_mode": min(1.0, max(v2.sorted_gap_mode, 0.0)),
        "transition_gap_cv": math.log1p(max(v2.transition_gap_cv, 0.0)) / 4,
        "h0_bits": h0 / width,
        "h1_cond_bits": max(0.0, h_pairs - h0) / width,
        "h_delta_bits": _entropy(deltas, max(len(values) - 1, 1)) / width,
        "lane_entropy_mean": sum(lanes) / len(lanes),
        "lane_entropy_spread": max(lanes) - min(lanes),
        "lane_h1_cond_mean": sum(lane_h1) / len(lane_h1),
    }


def family_features(sample_dir: Path, width: int) -> dict[str, float]:
    """Median fingerprint over up to FEATURE_SAMPLES samples (bounded prefix each)."""
    element = width // 8
    files = [path for path in sample_files(sample_dir) if path.stat().st_size >= element * 64]
    step = max(1, len(files) // FEATURE_SAMPLES)
    rows = []
    for path in files[::step][:FEATURE_SAMPLES]:
        with path.open("rb") as fh:
            rows.append(sample_features(fh.read(FEATURE_ELEMENTS * element), width))
    if not rows:
        return {}
    return {key: sorted(row[key] for row in rows)[len(rows) // 2] for key in rows[0]}


def feature_distance(a: dict[str, float], b: dict[str, float]) -> float:
    """Mean absolute difference over shared features (each roughly in [0, 1])."""
    keys = [key for key in a if key in b]
    return sum(abs(a[key] - b[key]) for key in keys) / len(keys) if keys else 1.0


def baseline_ids() -> set[str]:
    return set(json.loads((REPO_ROOT / "pipeline" / "baseline.json").read_text())["accepted_ids"])


def local_families(dataset_id: str, recipe_dir: Path | None = None) -> list[dict]:
    """Primary series of a local recipe that have built samples."""
    manifest = (recipe_dir or REPO_ROOT / "datasets" / dataset_id) / "manifest.toml"
    try:
        document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    families = []
    for series in document.get("series", []):
        if not isinstance(series, dict) or series.get("role", "primary") == "auxiliary":
            continue
        width = series.get("bit_width")
        output = series.get("output_path")
        if width not in WIDTHS or not output:
            continue
        sample_dir = DATA_ROOT / output
        if sample_dir.is_dir() and sample_files(sample_dir):
            families.append({"key": f"local:{dataset_id}:{series.get('id')}", "dataset_id": dataset_id, "width": width, "dir": sample_dir})
    return families


def downstream_families(width: int) -> list[dict]:
    root = DOWNSTREAM / f"{width}bit" / "datasets"
    if not root.is_dir():
        return []
    families = []
    for family in sorted(root.iterdir()):
        if family.is_dir() and any(path.is_file() for path in family.iterdir()):
            families.append({"key": f"downstream:{family.name}", "dataset_id": "", "width": width, "dir": family})
    return families


def safe_name(key: str) -> str:
    return key.replace("/", "_").replace(":", "__")


def split_family(family: dict, work: Path) -> tuple[Path, Path]:
    """Train/eval directories: alternate files, bounded in count and bytes; a
    single file is split into two halves at an element boundary."""
    train, evaluate = work / "train", work / "eval"
    train.mkdir(parents=True, exist_ok=True)
    evaluate.mkdir(parents=True, exist_ok=True)
    element = element_bytes(family["width"])
    files = [path for path in sample_files(family["dir"]) if path.stat().st_size >= element * 64]
    if not files:
        raise ValueError("no usable sample files")

    def place(source: Path, target_dir: Path, start: int, length: int) -> int:
        length -= length % element
        if length <= 0:
            return 0
        target = target_dir / f"{len(list(target_dir.iterdir())):05d}.bin"
        with source.open("rb") as src, target.open("wb") as dst:
            src.seek(start)
            dst.write(src.read(length))
        return length

    if len(files) == 1:
        size = files[0].stat().st_size
        half = (size // 2) // element * element
        place(files[0], train, 0, min(half, SIDE_BYTES))
        place(files[0], evaluate, half, min(size - half, SIDE_BYTES))
        return train, evaluate
    sides = {train: files[0::2], evaluate: files[1::2]}
    for target_dir, side_files in sides.items():
        step = max(1, len(side_files) // SIDE_FILES)
        budget = SIDE_BYTES
        for path in side_files[::step][:SIDE_FILES]:
            if budget <= 0:
                break
            budget -= place(path, target_dir, 0, min(path.stat().st_size, max(budget, element * 1024)))
    return train, evaluate


def compressed_ratio(compressor: Path, eval_dir: Path, scratch: Path) -> float | None:
    original = compressed = 0
    for path in sorted(eval_dir.iterdir()):
        target = scratch / (path.name + ".zl")
        result = subprocess.run([str(ZLI), "compress", str(path), "--compressor", str(compressor), "--output", str(target), "--force"],
                                capture_output=True, timeout=300)
        if result.returncode != 0 or not target.exists():
            return None
        original += path.stat().st_size
        compressed += target.stat().st_size
        target.unlink()
    return original / compressed if compressed else None


def train_family(family: dict, base_dir: Path | None = None) -> dict:
    """Train a Pareto set on the train half and keep the best member on the eval half."""
    out_dir = (base_dir or LIBRARY_DIR) / str(family["width"]) / safe_name(family["key"])
    meta_path = out_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    work = Path(tempfile.mkdtemp(prefix="zlsim_", dir=WORK_DIR))
    started = time.monotonic()
    try:
        train, evaluate = split_family(family, work)
        pareto = work / "pareto"
        mode = "pareto"
        try:
            result = subprocess.run([str(ZLI), "train", "--profile", PROFILES[family["width"]], str(train), "--output", str(pareto),
                                     "--pareto-frontier", "--threads", str(TRAIN_THREADS)],
                                    capture_output=True, text=True, timeout=PARETO_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            # Hard families: one greedy compressor on a smaller train half,
            # shrinking again if training is still too slow.
            result = None
            for budget_bytes, timeout_s in ((4 * 1024 * 1024, TRAIN_TIMEOUT_S), (1024 * 1024, 20 * 60)):
                mode = f"greedy_fallback_{budget_bytes // (1024 * 1024)}mb"
                shutil.rmtree(pareto, ignore_errors=True)
                small = work / f"train_{budget_bytes}"
                small.mkdir()
                budget = budget_bytes
                for path in sorted(train.iterdir()):
                    if budget <= 0:
                        break
                    chunk = path.read_bytes()[:budget]
                    chunk = chunk[: len(chunk) // element_bytes(family["width"]) * element_bytes(family["width"])]
                    (small / path.name).write_bytes(chunk)
                    budget -= len(chunk)
                pareto.mkdir()
                try:
                    result = subprocess.run([str(ZLI), "train", "--profile", PROFILES[family["width"]], str(small), "--output", str(pareto / "0.zc"),
                                             "--threads", str(max(TRAIN_THREADS, 4))],
                                            capture_output=True, text=True, timeout=timeout_s)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if result is None:
                raise RuntimeError("zli train timed out at every fallback tier")
        candidates = sorted(pareto.glob("*.zc")) if pareto.is_dir() else []
        if result.returncode != 0 or not candidates:
            raise RuntimeError(f"zli train failed rc={result.returncode} mode={mode}: {result.stderr[-300:]}")
        scratch = work / "scratch"
        scratch.mkdir()
        best, best_ratio = None, 0.0
        for compressor in candidates:
            ratio = compressed_ratio(compressor, evaluate, scratch)
            if ratio and ratio > best_ratio:
                best, best_ratio = compressor, ratio
        if best is None:
            raise RuntimeError("no Pareto member compressed the eval half")
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(best, out_dir / "winner.zc")
        meta = {
            "key": family["key"], "dataset_id": family["dataset_id"], "width": family["width"], "own_ratio": best_ratio,
            "features": family_features(evaluate, family["width"]),
            "train_mode": mode, "pareto_size": len(candidates), "eval_bytes": sum(p.stat().st_size for p in evaluate.iterdir()),
            "seconds": round(time.monotonic() - started), "source_dir": str(family["dir"]),
        }
        meta_path.write_text(json.dumps(meta, indent=1))
        return meta
    except Exception as exc:  # noqa: BLE001
        return {"key": family["key"], "width": family["width"], "error": str(exc)[:400]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def library(width: int, exclude_dataset: str = "") -> list[dict]:
    root = LIBRARY_DIR / str(width)
    entries = []
    if root.is_dir():
        for meta_path in root.glob("*/meta.json"):
            meta = json.loads(meta_path.read_text())
            if exclude_dataset and meta.get("dataset_id") == exclude_dataset:
                continue
            entries.append({**meta, "compressor": meta_path.parent / "winner.zc"})
    return entries


def measure_family(family: dict, jobs: int, extra: list[dict] | None = None, exclude_ids: set[str] | None = None) -> dict:
    """Own held-out ratio versus the best library compressor of the same width."""
    own = train_family(family)
    if "error" in own:
        return own
    work = Path(tempfile.mkdtemp(prefix="zlsim_m_", dir=WORK_DIR))
    try:
        _, evaluate = split_family(family, work)
        entries = [entry for entry in library(family["width"], exclude_dataset=family["dataset_id"])
                   if entry["key"] != family["key"] and entry.get("dataset_id") not in (exclude_ids or set())]
        entries += extra or []

        def cross(entry: dict) -> tuple[str, float | None]:
            scratch = Path(tempfile.mkdtemp(dir=work))
            try:
                return entry["key"], compressed_ratio(entry["compressor"], evaluate, scratch)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            ratios = dict(item for item in pool.map(cross, entries) if item[1])
        own_ratio = own["own_ratio"]
        mine = own.get("features") or {}
        per_entry = []
        for entry in entries:
            if entry["key"] not in ratios:
                continue
            per_entry.append({
                "key": entry["key"],
                # Positive: this existing compressor is that much worse than the family's own.
                "loss": round(1 - ratios[entry["key"]] / own_ratio, 4),
                "distance": round(feature_distance(mine, entry.get("features") or {}), 4),
            })
        by_loss = sorted(per_entry, key=lambda item: item["loss"])
        by_distance = sorted(per_entry, key=lambda item: item["distance"])
        # Joint score: the existing family closest on both axes at once.
        by_joint = sorted(per_entry, key=lambda item: max(item["loss"], 0) + item["distance"])
        return {
            "key": family["key"], "width": family["width"], "own_ratio": round(own_ratio, 4), "library_size": len(per_entry),
            "nearest_compression": by_loss[:3], "nearest_features": by_distance[:3], "nearest_joint": by_joint[:3],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rank_tables(width: int) -> tuple[list[str], dict[str, list[float]]]:
    """Per-feature sorted columns over the library, minus near-constant features."""
    peers = [entry for entry in library(width) if entry.get("features")]
    keys = list(peers[0]["features"]) if peers else []
    columns = {key: sorted(entry["features"][key] for entry in peers if key in entry["features"]) for key in keys}
    keep = [key for key in keys if columns[key] and columns[key][int(0.95 * (len(columns[key]) - 1))] - columns[key][int(0.05 * (len(columns[key]) - 1))] > 0.02]
    return keep, columns


def percentile_distance(a: dict, b: dict, tables: tuple[list[str], dict[str, list[float]]]) -> float:
    import bisect
    keep, columns = tables
    keys = [key for key in keep if key in a and key in b]
    if not keys:
        return 1.0
    pct = lambda key, value: (bisect.bisect_left(columns[key], value) + bisect.bisect_right(columns[key], value)) / 2 / len(columns[key])  # noqa: E731
    return sum(abs(pct(key, a[key]) - pct(key, b[key])) for key in keys) / len(keys)


def mode_share(sample_dir: Path, width: int) -> float:
    """Largest single-value share over a few samples (fill / no-data dominance)."""
    element = width // 8
    files = sample_files(sample_dir)
    shares = []
    for path in files[:: max(1, len(files) // 6)][:6]:
        values = array.array({1: "B", 2: "H", 4: "I", 8: "Q"}[element])
        with path.open("rb") as fh:
            raw = fh.read(FEATURE_ELEMENTS * element)
        values.frombytes(raw[: len(raw) // element * element])
        if values:
            shares.append(collections.Counter(values).most_common(1)[0][1] / len(values))
    return max(shares) if shares else 0.0


def gate_recipe(recipe_dir: Path, jobs: int) -> dict:
    """Production breadth test for a built recipe (staging or datasets)."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    dataset_id = recipe_dir.name
    families = local_families(dataset_id, recipe_dir)
    report = {"dataset_id": dataset_id, "thresholds": {"loss": REDUNDANT_LOSS, "distance": REDUNDANT_DISTANCE}, "series": []}
    for family in families:
        own = train_family(family, CANDIDATE_DIR)
        if "error" in own:
            report["series"].append({"key": family["key"], "error": own["error"]})
            continue
        tables = rank_tables(family["width"])
        peers = [entry for entry in library(family["width"], exclude_dataset=dataset_id) if entry.get("features")]
        near = sorted(peers, key=lambda entry: percentile_distance(own["features"], entry["features"], tables))[:GATE_NEIGHBORS]
        work = Path(tempfile.mkdtemp(prefix="zlsim_g_", dir=WORK_DIR))
        try:
            _, evaluate = split_family(family, work)

            def cross(entry: dict) -> dict:
                scratch = Path(tempfile.mkdtemp(dir=work))
                try:
                    ratio = compressed_ratio(entry["compressor"], evaluate, scratch)
                finally:
                    shutil.rmtree(scratch, ignore_errors=True)
                return {
                    "key": entry["key"],
                    "distance": round(percentile_distance(own["features"], entry["features"], tables), 4),
                    "loss": round(1 - ratio / own["own_ratio"], 4) if ratio else None,
                }

            with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
                neighbors = list(pool.map(cross, near))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        matches = [n for n in neighbors if n["loss"] is not None and n["loss"] <= REDUNDANT_LOSS and n["distance"] <= REDUNDANT_DISTANCE]
        nearest = min((n["distance"] for n in neighbors), default=1.0)
        report["series"].append({
            "key": family["key"], "width": family["width"], "own_ratio": round(own["own_ratio"], 4),
            "redundant": bool(matches), "match": min(matches, key=lambda n: n["distance"]) if matches else None,
            "nearest_distance": round(nearest, 4), "neighbors": neighbors, "mode_share": round(mode_share(family["dir"], family["width"]), 4),
        })
    measured = [series for series in report["series"] if "error" not in series]
    report["redundant"] = bool(measured) and all(series["redundant"] for series in measured)
    if not measured:
        report["verdict"] = "ERROR"
    elif report["redundant"]:
        report["verdict"] = "WEAK"
    elif max(series["nearest_distance"] for series in measured if not series["redundant"]) >= STRONG_DISTANCE:
        report["verdict"] = "STRONG"
    else:
        report["verdict"] = "OK"
    report["fill_warnings"] = [series["key"] for series in measured if series["mode_share"] >= FILL_WARNING_SHARE]
    return report


def adopt(dataset_id: str) -> int:
    """Move an accepted candidate's trained entries into the library."""
    moved = 0
    for meta_path in CANDIDATE_DIR.glob("*/*/meta.json"):
        meta = json.loads(meta_path.read_text())
        if meta.get("dataset_id") != dataset_id:
            continue
        target = LIBRARY_DIR / str(meta["width"]) / meta_path.parent.name
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(meta_path.parent), str(target))
        moved += 1
    return moved


def cmd_gate(args) -> int:
    report = gate_recipe(Path(args.recipe_dir).resolve(), args.jobs)
    print(json.dumps(report, indent=1))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 3 if report["redundant"] else (2 if report["verdict"] == "ERROR" else 0)


def cmd_adopt(args) -> int:
    print(f"adopted {adopt(args.dataset_id)} series of {args.dataset_id}")
    return 0


def cmd_build_library(args) -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    widths = [int(width) for width in args.widths.split(",")]
    sources = set(args.sources.split(","))
    families = []
    for width in widths:
        if "downstream" in sources:
            families += downstream_families(width)
    if "local" in sources:
        for dataset_id in sorted(baseline_ids()):
            families += [family for family in local_families(dataset_id) if family["width"] in widths]
    print(f"training {len(families)} families with {args.jobs} jobs", flush=True)
    done = errors = 0
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
        for meta in pool.map(train_family, families):
            done += 1
            if "error" in meta:
                errors += 1
                print(f"ERROR {meta['key']}: {meta['error']}", flush=True)
            if done % 50 == 0:
                print(f"{done}/{len(families)} done, {errors} errors", flush=True)
    print(f"library built: {done} families, {errors} errors", flush=True)
    return 0


def cmd_measure(args) -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for family in local_families(args.dataset_id):
        print(json.dumps(measure_family(family, args.jobs)), flush=True)
    return 0


def cmd_calibrate(args) -> int:
    """Measure each autocollect acceptance against the library as it stood
    before it: downstream and baseline families plus earlier acceptances.
    All acceptances are trained first (in parallel); each measurement then
    excludes itself and every later acceptance."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    with (REPO_ROOT / "pipeline" / "candidates.tsv").open(encoding="utf-8", newline="") as fh:
        accepted = [row for row in csv.DictReader(fh, delimiter="\t") if row["status"] == "accepted"]
    accepted.sort(key=lambda row: row["updated"])
    order = [row["candidate_id"] for row in accepted]
    families = [(row, family) for row in accepted for family in local_families(row["candidate_id"])]
    print(f"training {len(families)} series of {len(accepted)} acceptances", flush=True)
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
        for meta in pool.map(train_family, [family for _, family in families]):
            if "error" in meta:
                print(f"ERROR {meta['key']}: {meta['error']}", flush=True)
    out_path = ZLSIM_DIR / "calibration.jsonl"
    seen = set()
    if out_path.exists():
        seen = {json.loads(line)["key"] for line in out_path.read_text().splitlines() if line.strip()}
    for row, family in families:
        if family["key"] in seen:
            continue
        later = set(order[order.index(row["candidate_id"]):])
        result = measure_family(family, args.jobs, exclude_ids=later)
        result.update(dataset_id=row["candidate_id"], breadth=row.get("breadth", ""), novelty_kind=row.get("novelty_kind", ""))
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result) + "\n")
        print(json.dumps(result)[:300], flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-library")
    build.add_argument("--widths", default="8,16,32,64")
    build.add_argument("--sources", default="downstream,local")
    build.add_argument("--jobs", type=int, default=48)
    measure = sub.add_parser("measure")
    measure.add_argument("dataset_id")
    measure.add_argument("--jobs", type=int, default=32)
    calibrate = sub.add_parser("calibrate")
    calibrate.add_argument("--jobs", type=int, default=48)
    gate = sub.add_parser("gate")
    gate.add_argument("recipe_dir")
    gate.add_argument("--jobs", type=int, default=16)
    gate.add_argument("--output", default="", help="also write the JSON report to this file")
    adopt_parser = sub.add_parser("adopt")
    adopt_parser.add_argument("dataset_id")
    args = parser.parse_args()
    if not ZLI.exists():
        print(f"zli not found at {ZLI}; set ZLSIM_ZLI")
        return 1
    return {"build-library": cmd_build_library, "measure": cmd_measure, "calibrate": cmd_calibrate,
            "gate": cmd_gate, "adopt": cmd_adopt}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
