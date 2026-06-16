#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_IDS = [
    "librispeech_dev_clean_i16",
]
MIN_VALUES = 10_000
MIN_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def percentile(values: list[int], pct: float) -> float | int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    if fraction == 0:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def fmt(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def run_script(recipe_dir: Path, script_name: str, data_dir: str) -> None:
    script = recipe_dir / script_name
    if not script.exists():
        raise SystemExit(f"missing script: {script.relative_to(REPO_ROOT)}")
    env = os.environ.copy()
    env["DATA_DIR"] = data_dir
    subprocess.run([str(script)], cwd=REPO_ROOT, check=True, env=env)


def load_roles(recipe_dir: Path) -> dict[str, str]:
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    roles = {}
    for series in manifest.get("series", []):
        series_id = str(series.get("id", "")).strip()
        role = str(series.get("role", "primary")).strip().lower()
        if series_id:
            roles[series_id] = role if role in {"primary", "auxiliary"} else "primary"
    return roles


def summarize_dataset(dataset_id: str, data_dir: str) -> dict:
    recipe_dir = REPO_ROOT / "staging" / dataset_id
    data_root = REPO_ROOT / data_dir
    index_path = data_root / "index" / dataset_id / "samples.jsonl"
    base = {
        "dataset_id": dataset_id,
        "status": "pending",
        "reasons": ["missing_sample_index"],
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
        "same_size_fraction": 0.0,
        "missing_files": 0,
        "series": [],
    }
    if not index_path.exists():
        return base

    roles = load_roles(recipe_dir)
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_series: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_series[str(row["series_id"])].append(row)

    primary_sizes: list[int] = []
    primary_values: list[int] = []
    series_summaries = []
    missing_files = 0
    bad_width_rows = 0
    for series_id, series_rows in sorted(by_series.items()):
        role = roles.get(series_id, "primary")
        sizes = []
        values = []
        kinds = set()
        widths = set()
        for row in series_rows:
            sample_path = data_root / row["sample_path"]
            declared_size = int(row["sample_size_bytes"])
            value_count = int(row["value_count"])
            actual_size = sample_path.stat().st_size if sample_path.exists() else -1
            if actual_size != declared_size:
                missing_files += 1
            if int(row["bit_width"]) != 16:
                bad_width_rows += 1
            sizes.append(declared_size)
            values.append(value_count)
            kinds.add(str(row["numeric_kind"]))
            widths.add(int(row["bit_width"]))
        if role == "primary":
            primary_sizes.extend(sizes)
            primary_values.extend(values)
        series_summaries.append(
            {
                "series_id": series_id,
                "role": role,
                "numeric_kind": ",".join(sorted(kinds)),
                "bit_width": ",".join(str(width) for width in sorted(widths)),
                "samples": len(series_rows),
                "values_total": sum(values),
                "bytes_total": sum(sizes),
                "min_bytes": min(sizes) if sizes else 0,
                "median_bytes": statistics.median(sizes) if sizes else 0,
                "max_bytes": max(sizes) if sizes else 0,
                "same_size_fraction": max(Counter(sizes).values()) / len(sizes) if sizes else 0.0,
            }
        )

    reasons = []
    primary_total_values = sum(primary_values)
    primary_total_bytes = sum(primary_sizes)
    if not primary_sizes:
        reasons.append("missing_primary_payload")
    if primary_total_values < MIN_VALUES:
        reasons.append("value_floor")
    if primary_total_bytes < MIN_BYTES:
        reasons.append("byte_floor")
    if primary_sizes and statistics.median(primary_values) < MIN_MEDIAN_VALUES:
        reasons.append("median_sample_floor")
    if primary_total_bytes > MAX_PRIMARY_BYTES:
        reasons.append("primary_size_cap")
    if missing_files:
        reasons.append("missing_or_size_mismatched_files")
    if bad_width_rows:
        reasons.append("non_16bit_rows")

    same_size_fraction = max(Counter(primary_sizes).values()) / len(primary_sizes) if primary_sizes else 0.0
    base.update(
        {
            "status": "ok" if not reasons else "needs_attention",
            "reasons": reasons,
            "primary_samples": len(primary_sizes),
            "primary_values": primary_total_values,
            "primary_bytes": primary_total_bytes,
            "size_min": min(primary_sizes) if primary_sizes else 0,
            "size_p10": percentile(primary_sizes, 0.10),
            "size_p25": percentile(primary_sizes, 0.25),
            "size_median": statistics.median(primary_sizes) if primary_sizes else 0,
            "size_p75": percentile(primary_sizes, 0.75),
            "size_p90": percentile(primary_sizes, 0.90),
            "size_max": max(primary_sizes) if primary_sizes else 0,
            "unique_sample_sizes": len(Counter(primary_sizes)),
            "same_size_fraction": same_size_fraction,
            "missing_files": missing_files,
            "series": series_summaries,
        }
    )
    return base


def write_reports(summaries: list[dict], report_prefix: Path) -> None:
    report_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = report_prefix.with_suffix(".json")
    tsv_path = report_prefix.with_suffix(".tsv")
    md_path = report_prefix.with_suffix(".md")

    json_path.write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = [
        "dataset_id",
        "status",
        "reasons",
        "primary_samples",
        "primary_values",
        "primary_bytes",
        "size_min",
        "size_p10",
        "size_p25",
        "size_median",
        "size_p75",
        "size_p90",
        "size_max",
        "unique_sample_sizes",
        "same_size_fraction",
        "missing_files",
    ]
    with tsv_path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(fields) + "\n")
        for summary in summaries:
            row = []
            for field in fields:
                value = summary[field]
                if field == "reasons":
                    value = ",".join(value)
                elif isinstance(value, float):
                    value = f"{value:.6f}"
                row.append(str(value))
            fh.write("\t".join(row) + "\n")

    lines = [
        "# 16-bit Hunt Dataset State",
        "",
        "Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.",
        "",
        "| dataset_id | status | primary samples | primary bytes | min / p10 / p25 / median / p75 / p90 / max sample bytes | unique sizes | same-size fraction | reasons |",
        "|---|---:|---:|---:|---|---:|---:|---|",
    ]
    for summary in summaries:
        dist = " / ".join(
            fmt(summary[key])
            for key in ["size_min", "size_p10", "size_p25", "size_median", "size_p75", "size_p90", "size_max"]
        )
        lines.append(
            f"| `{summary['dataset_id']}` | `{summary['status']}` | {summary['primary_samples']} | {summary['primary_bytes']} | {dist} | "
            f"{summary['unique_sample_sizes']} | {summary['same_size_fraction']:.6f} | {', '.join(summary['reasons']) or 'none'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build, verify, and summarize staged 16-bit dataset candidates.")
    parser.add_argument("--data-dir", default=".data", help="Local data directory relative to the repository root.")
    parser.add_argument("--download", action="store_true", help="Run per-dataset download.sh before build. Do not use from agent runs.")
    parser.add_argument("--skip-build", action="store_true", help="Only summarize existing sample indexes and payloads.")
    parser.add_argument("--report-prefix", default="reports/16bit_hunt_20260614_dataset_state", help="Report path prefix without extension.")
    args = parser.parse_args()

    for dataset_id in DATASET_IDS:
        recipe_dir = REPO_ROOT / "staging" / dataset_id
        if args.download:
            run_script(recipe_dir, "download.sh", args.data_dir)
        if not args.skip_build:
            run_script(recipe_dir, "build.sh", args.data_dir)
            run_script(recipe_dir, "verify.sh", args.data_dir)

    summaries = [summarize_dataset(dataset_id, args.data_dir) for dataset_id in DATASET_IDS]
    write_reports(summaries, REPO_ROOT / args.report_prefix)
    for summary in summaries:
        print(
            f"{summary['dataset_id']}: status={summary['status']} samples={summary['primary_samples']} "
            f"bytes={summary['primary_bytes']} sizes={summary['size_min']}/{fmt(summary['size_p10'])}/"
            f"{fmt(summary['size_p25'])}/{fmt(summary['size_median'])}/{fmt(summary['size_p75'])}/"
            f"{fmt(summary['size_p90'])}/{summary['size_max']} same_size={summary['same_size_fraction']:.6f} "
            f"reasons={','.join(summary['reasons']) or 'none'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
