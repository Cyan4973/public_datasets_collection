#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ".data"
DATASET_IDS = [
    "google_fonts_ofl_ttf_u8",
]
MIN_VALUES = 10_000
MIN_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def fmt(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def percentile(values: list[int], pct: float) -> float | int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    frac = pos - lower
    if frac == 0:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def error_summary(dataset_id: str, reason: str) -> dict:
    return {
        "dataset_id": dataset_id,
        "status": "error",
        "reasons": [reason],
        "primary_samples": 0,
        "primary_values": 0,
        "primary_bytes": 0,
        "size_min": 0,
        "size_p10": 0,
        "size_p25": 0,
        "size_median": 0,
        "size_p75": 0,
        "size_p90": 0,
        "size_max": 0,
        "unique_sample_sizes": 0,
        "same_size_fraction": 0,
        "missing_files": 0,
    }


def load_manifest(recipe_dir: Path) -> dict:
    return tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))


def primary_series_ids(manifest: dict) -> set[str]:
    return {
        str(series["id"])
        for series in manifest.get("series", [])
        if str(series.get("role", "primary")).lower() == "primary"
    }


def expected_downloads(manifest: dict, data_root: Path) -> list[Path]:
    out = []
    for resource in manifest.get("resources", []):
        local_path = str(resource.get("local_path", ""))
        if local_path and not local_path.endswith("/"):
            out.append(data_root / local_path)
    return out


def require_downloads(recipe_dir: Path, data_root: Path) -> None:
    manifest = load_manifest(recipe_dir)
    missing = [path for path in expected_downloads(manifest, data_root) if not path.exists()]
    if missing:
        rels = "\n".join(f"- {path.relative_to(REPO_ROOT)}" for path in missing)
        raise SystemExit(f"missing local download(s) for {recipe_dir.name}; run download.sh first:\n{rels}")
    download_root = data_root / "downloads" / str(manifest.get("dataset_id") or recipe_dir.name)
    if not download_root.exists() or not any(download_root.iterdir()):
        raise SystemExit(f"missing local downloads for {recipe_dir.name}: {download_root.relative_to(REPO_ROOT)}")


def summarize_dataset(recipe_dir: Path, data_root: Path) -> dict:
    manifest = load_manifest(recipe_dir)
    dataset_id = str(manifest.get("dataset_id") or recipe_dir.name)
    primary_ids = primary_series_ids(manifest)
    index_path = data_root / "index" / dataset_id / "samples.jsonl"
    if not index_path.exists():
        raise SystemExit(f"missing sample index for {dataset_id}: {index_path.relative_to(REPO_ROOT)}")

    sizes = []
    values = []
    missing_files = 0
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row["series_id"]) not in primary_ids:
            continue
        sample_path = data_root / row["sample_path"]
        if not sample_path.exists():
            missing_files += 1
            continue
        actual_size = sample_path.stat().st_size
        declared_size = int(row["sample_size_bytes"])
        declared_values = int(row["value_count"])
        if actual_size != declared_size:
            raise SystemExit(f"{dataset_id}: size mismatch for {sample_path.relative_to(REPO_ROOT)}")
        sizes.append(declared_size)
        values.append(declared_values)

    if not sizes:
        raise SystemExit(f"{dataset_id}: no primary samples")
    counts = Counter(sizes)
    total_bytes = sum(sizes)
    total_values = sum(values)
    reasons = []
    if missing_files:
        reasons.append("missing_sample_files")
    if total_values < MIN_VALUES:
        reasons.append("value_floor")
    if total_bytes < MIN_BYTES:
        reasons.append("byte_floor")
    if statistics.median(values) < MIN_MEDIAN_VALUES:
        reasons.append("median_sample_floor")
    if total_bytes > MAX_PRIMARY_BYTES:
        reasons.append("primary_size_cap")
    if len(counts) < 2:
        reasons.append("identical_sample_sizes")

    return {
        "dataset_id": dataset_id,
        "status": "ok" if not reasons else "needs_attention",
        "reasons": reasons,
        "primary_samples": len(sizes),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "size_min": min(sizes),
        "size_p10": percentile(sizes, 0.10),
        "size_p25": percentile(sizes, 0.25),
        "size_median": statistics.median(sizes),
        "size_p75": percentile(sizes, 0.75),
        "size_p90": percentile(sizes, 0.90),
        "size_max": max(sizes),
        "unique_sample_sizes": len(counts),
        "same_size_fraction": max(counts.values()) / len(sizes),
        "missing_files": missing_files,
    }


def write_reports(summaries: list[dict], output_json: Path, output_tsv: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with output_tsv.open("w", encoding="utf-8") as fh:
        fh.write(
            "dataset_id\tstatus\treasons\tprimary_samples\tprimary_values\tprimary_bytes\tsize_min\tsize_p10\tsize_p25\tsize_median\tsize_p75\tsize_p90\tsize_max\tunique_sample_sizes\tsame_size_fraction\tmissing_files\n"
        )
        for summary in summaries:
            fh.write(
                f"{summary['dataset_id']}\t{summary['status']}\t{','.join(summary['reasons']) or 'none'}\t{summary['primary_samples']}\t{summary['primary_values']}\t{summary['primary_bytes']}\t{summary['size_min']}\t{fmt(summary['size_p10'])}\t{fmt(summary['size_p25'])}\t{fmt(summary['size_median'])}\t{fmt(summary['size_p75'])}\t{fmt(summary['size_p90'])}\t{summary['size_max']}\t{summary['unique_sample_sizes']}\t{summary['same_size_fraction']:.6f}\t{summary['missing_files']}\n"
            )


def normalize_text_report(path: Path) -> None:
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 2026-06-14 staged 8-bit variety benchmark locally.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--datasets", nargs="+", choices=DATASET_IDS, default=DATASET_IDS, help="Subset of staged datasets to process.")
    parser.add_argument("--download", action="store_true", help="Run each download.sh before build/verify.")
    parser.add_argument("--keep-going", action="store_true", help="Continue to later datasets after a dataset fails.")
    parser.add_argument("--skip-build", action="store_true", help="Only summarize existing indexes and samples.")
    parser.add_argument("--output-json", default="reports/8bit_variety_hunt_20260614_benchmark.json")
    parser.add_argument("--output-tsv", default="reports/8bit_variety_hunt_20260614_benchmark.tsv")
    parser.add_argument("--state-md", default="reports/8bit_variety_hunt_20260614_dataset_state.md")
    parser.add_argument("--state-tsv", default="reports/8bit_variety_hunt_20260614_dataset_state.tsv")
    args = parser.parse_args()

    data_root = REPO_ROOT / args.data_dir
    recipe_dirs = [REPO_ROOT / "staging" / dataset_id for dataset_id in args.datasets]
    completed_recipe_dirs = []
    summaries = []
    for recipe_dir in recipe_dirs:
        dataset_id = recipe_dir.name
        try:
            if args.download:
                run(["bash", str(recipe_dir / "download.sh")])
            else:
                require_downloads(recipe_dir, data_root)
            if not args.skip_build:
                run(["bash", str(recipe_dir / "build.sh")])
                run(["bash", str(recipe_dir / "verify.sh")])
            summaries.append(summarize_dataset(recipe_dir, data_root))
            completed_recipe_dirs.append(recipe_dir)
        except (subprocess.CalledProcessError, SystemExit) as exc:
            reason = f"failed:{exc}"
            summaries.append(error_summary(dataset_id, reason))
            print(f"{dataset_id}: {reason}", file=sys.stderr)
            if not args.keep_going:
                write_reports(summaries, REPO_ROOT / args.output_json, REPO_ROOT / args.output_tsv)
                return 1

    if completed_recipe_dirs:
        run(
            [
                sys.executable,
                "tools/report_dataset_state.py",
                *(str(recipe.relative_to(REPO_ROOT)) for recipe in completed_recipe_dirs),
                "--data-dir",
                args.data_dir,
                "--output-md",
                args.state_md,
                "--output-tsv",
                args.state_tsv,
            ]
        )
        normalize_text_report(REPO_ROOT / args.state_md)
    write_reports(summaries, REPO_ROOT / args.output_json, REPO_ROOT / args.output_tsv)
    for summary in summaries:
        print(
            f"{summary['dataset_id']}: status={summary['status']} samples={summary['primary_samples']} bytes={summary['primary_bytes']} "
            f"sizes={summary['size_min']}/{fmt(summary['size_p10'])}/{fmt(summary['size_p25'])}/{fmt(summary['size_median'])}/"
            f"{fmt(summary['size_p75'])}/{fmt(summary['size_p90'])}/{summary['size_max']} same_size_fraction={summary['same_size_fraction']:.6f}"
        )
    failed = [summary for summary in summaries if summary["status"] != "ok"]
    if failed:
        for summary in failed:
            print(f"{summary['dataset_id']} failed benchmark: {','.join(summary['reasons'])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
