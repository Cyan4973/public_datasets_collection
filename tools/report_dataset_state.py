#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import tomllib
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ".data"
MIN_VALUES = 10_000
MIN_SAMPLE_BYTES = 100 * 1024
MIN_MEDIAN_SAMPLE_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def fmt_num(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


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


def same_size_fraction(values: list[int]) -> float:
    if not values:
        return 0
    return max(Counter(values).values()) / len(values)


def load_manifest(recipe_dir: Path) -> dict:
    manifest_path = recipe_dir / "manifest.toml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing manifest: {manifest_path}")
    return tomllib.loads(manifest_path.read_text(encoding="utf-8"))


def series_roles(manifest: dict) -> dict[str, str]:
    roles = {}
    for series in manifest.get("series", []):
        series_id = str(series.get("id", "")).strip()
        if not series_id:
            continue
        role = str(series.get("role", "primary")).strip().lower()
        roles[series_id] = role if role in {"primary", "auxiliary"} else "primary"
    return roles


def summarize_rows(rows: list[dict], roles: dict[str, str]) -> tuple[dict, list[dict]]:
    by_series: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_series[str(row["series_id"])].append(row)

    series_summaries = []
    primary_values = 0
    primary_bytes = 0
    primary_sample_value_counts = []
    primary_sample_sizes = []

    for series_id in sorted(by_series):
        series_rows = by_series[series_id]
        role = roles.get(series_id, "primary")
        sizes = [int(row["sample_size_bytes"]) for row in series_rows]
        counts = [int(row["value_count"]) for row in series_rows]
        bytes_total = sum(sizes)
        values_total = sum(counts)
        if role == "primary":
            primary_values += values_total
            primary_bytes += bytes_total
            primary_sample_sizes.extend(sizes)
            primary_sample_value_counts.extend(counts)
        numeric_kinds = sorted({str(row["numeric_kind"]) for row in series_rows})
        bit_widths = sorted({int(row["bit_width"]) for row in series_rows})
        paths = [str(row["sample_path"]) for row in series_rows]
        missing_files = sum(1 for row in series_rows if row.get("_missing_file"))
        series_summaries.append(
            {
                "series_id": series_id,
                "role": role,
                "numeric_kind": ",".join(numeric_kinds),
                "bit_width": ",".join(str(width) for width in bit_widths),
                "samples": len(series_rows),
                "values_total": values_total,
                "bytes_total": bytes_total,
                "min_values": min(counts) if counts else 0,
                "p10_values": percentile(counts, 0.10),
                "p25_values": percentile(counts, 0.25),
                "median_values": statistics.median(counts) if counts else 0,
                "p75_values": percentile(counts, 0.75),
                "p90_values": percentile(counts, 0.90),
                "max_values": max(counts) if counts else 0,
                "min_bytes": min(sizes) if sizes else 0,
                "p10_bytes": percentile(sizes, 0.10),
                "p25_bytes": percentile(sizes, 0.25),
                "median_bytes": statistics.median(sizes) if sizes else 0,
                "p75_bytes": percentile(sizes, 0.75),
                "p90_bytes": percentile(sizes, 0.90),
                "max_bytes": max(sizes) if sizes else 0,
                "same_size_fraction": same_size_fraction(sizes),
                "first_sample_path": paths[0] if paths else "",
                "missing_files": missing_files,
            }
        )

    primary_median_values = statistics.median(primary_sample_value_counts) if primary_sample_value_counts else 0
    primary_median_bytes = statistics.median(primary_sample_sizes) if primary_sample_sizes else 0
    reasons = []
    if not primary_sample_value_counts:
        reasons.append("missing_primary_payload")
    if primary_values < MIN_VALUES:
        reasons.append("value_floor")
    if primary_bytes < MIN_SAMPLE_BYTES:
        reasons.append("byte_floor")
    if primary_median_values < MIN_MEDIAN_SAMPLE_VALUES:
        reasons.append("median_sample_floor")
    if primary_bytes > MAX_PRIMARY_BYTES:
        reasons.append("primary_size_cap")
    if any(series["missing_files"] for series in series_summaries):
        reasons.append("missing_sample_files")
    dataset_summary = {
        "primary_values": primary_values,
        "primary_bytes": primary_bytes,
        "primary_samples": len(primary_sample_value_counts),
        "primary_min_values": min(primary_sample_value_counts) if primary_sample_value_counts else 0,
        "primary_p10_values": percentile(primary_sample_value_counts, 0.10),
        "primary_p25_values": percentile(primary_sample_value_counts, 0.25),
        "primary_median_values": primary_median_values,
        "primary_p75_values": percentile(primary_sample_value_counts, 0.75),
        "primary_p90_values": percentile(primary_sample_value_counts, 0.90),
        "primary_max_values": max(primary_sample_value_counts) if primary_sample_value_counts else 0,
        "primary_min_bytes": min(primary_sample_sizes) if primary_sample_sizes else 0,
        "primary_p10_bytes": percentile(primary_sample_sizes, 0.10),
        "primary_p25_bytes": percentile(primary_sample_sizes, 0.25),
        "primary_median_bytes": primary_median_bytes,
        "primary_p75_bytes": percentile(primary_sample_sizes, 0.75),
        "primary_p90_bytes": percentile(primary_sample_sizes, 0.90),
        "primary_max_bytes": max(primary_sample_sizes) if primary_sample_sizes else 0,
        "primary_same_size_fraction": same_size_fraction(primary_sample_sizes),
        "status": "ok" if not reasons else "needs_attention",
        "reasons": reasons,
    }
    return dataset_summary, series_summaries


def load_index(index_path: Path, data_root: Path) -> list[dict]:
    rows = []
    if not index_path.exists():
        return rows
    for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        sample_path = data_root / row["sample_path"]
        row["_missing_file"] = not sample_path.exists()
        if sample_path.exists():
            actual_size = sample_path.stat().st_size
            if actual_size != int(row["sample_size_bytes"]):
                row["_size_mismatch"] = actual_size
        row["_line_number"] = line_number
        rows.append(row)
    return rows


def recipe_dirs_from_args(paths: list[str]) -> list[Path]:
    result = []
    for raw_path in paths:
        path = (REPO_ROOT / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
        if path.is_dir() and (path / "manifest.toml").exists():
            result.append(path)
        elif path.is_dir():
            result.extend(sorted(child for child in path.iterdir() if child.is_dir() and (child / "manifest.toml").exists()))
        else:
            raise FileNotFoundError(f"not a recipe dir or root containing recipes: {path}")
    return sorted(dict.fromkeys(result))


def write_reports(dataset_reports: list[dict], output_md: Path, output_tsv: Path) -> None:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_tsv.parent.mkdir(parents=True, exist_ok=True)

    with output_tsv.open("w", encoding="utf-8") as fh:
        fh.write(
            "dataset_id\tstatus\treasons\tseries_id\trole\tnumeric_kind\tbit_width\tsamples\tvalues_total\tbytes_total\tmin_values\tp10_values\tp25_values\tmedian_values\tp75_values\tp90_values\tmax_values\tmin_bytes\tp10_bytes\tp25_bytes\tmedian_bytes\tp75_bytes\tp90_bytes\tmax_bytes\tsame_size_fraction\tmissing_files\tfirst_sample_path\n"
        )
        for report in dataset_reports:
            dataset_id = report["dataset_id"]
            ds = report["dataset"]
            for series in report["series"]:
                fh.write(
                    f"{dataset_id}\t{ds['status']}\t{','.join(ds['reasons'])}\t{series['series_id']}\t{series['role']}\t{series['numeric_kind']}\t{series['bit_width']}\t{series['samples']}\t{series['values_total']}\t{series['bytes_total']}\t{series['min_values']}\t{fmt_num(series['p10_values'])}\t{fmt_num(series['p25_values'])}\t{fmt_num(series['median_values'])}\t{fmt_num(series['p75_values'])}\t{fmt_num(series['p90_values'])}\t{series['max_values']}\t{series['min_bytes']}\t{fmt_num(series['p10_bytes'])}\t{fmt_num(series['p25_bytes'])}\t{fmt_num(series['median_bytes'])}\t{fmt_num(series['p75_bytes'])}\t{fmt_num(series['p90_bytes'])}\t{series['max_bytes']}\t{series['same_size_fraction']:.6f}\t{series['missing_files']}\t{series['first_sample_path']}\n"
                )

    with output_md.open("w", encoding="utf-8") as fh:
        fh.write("# Dataset State Report\n\n")
        fh.write(
            f"Acceptance floor used by this report: at least `{MIN_VALUES}` primary values, at least `{MIN_SAMPLE_BYTES}` primary bytes, median primary sample size at least `{MIN_MEDIAN_SAMPLE_VALUES}` values, and primary output at most `{MAX_PRIMARY_BYTES}` bytes.\n\n"
        )
        for report in dataset_reports:
            dataset_id = report["dataset_id"]
            ds = report["dataset"]
            fh.write(f"## `{dataset_id}`\n\n")
            fh.write(f"- status: `{ds['status']}`\n")
            fh.write(f"- reasons: `{','.join(ds['reasons']) if ds['reasons'] else 'none'}`\n")
            fh.write(f"- primary_samples: {ds['primary_samples']}\n")
            fh.write(f"- primary_values: {ds['primary_values']}\n")
            fh.write(f"- primary_bytes: {ds['primary_bytes']}\n")
            fh.write(
                f"- primary_value_count_range: {ds['primary_min_values']} / {fmt_num(ds['primary_median_values'])} / {ds['primary_max_values']} min/median/max\n"
            )
            fh.write(
                f"- primary_size_range_bytes: {ds['primary_min_bytes']} / {fmt_num(ds['primary_median_bytes'])} / {ds['primary_max_bytes']} min/median/max\n"
            )
            fh.write(
                f"- primary_size_distribution_bytes: {ds['primary_min_bytes']} / {fmt_num(ds['primary_p10_bytes'])} / {fmt_num(ds['primary_p25_bytes'])} / {fmt_num(ds['primary_median_bytes'])} / {fmt_num(ds['primary_p75_bytes'])} / {fmt_num(ds['primary_p90_bytes'])} / {ds['primary_max_bytes']} min/p10/p25/median/p75/p90/max\n"
            )
            fh.write(f"- primary_same_size_fraction: {ds['primary_same_size_fraction']:.6f}\n\n")
            fh.write("| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |\n")
            fh.write("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
            for series in report["series"]:
                fh.write(
                    f"| `{series['series_id']}` | {series['role']} | {series['numeric_kind']} | {series['bit_width']} | {series['samples']} | {series['values_total']} | {series['bytes_total']} | {series['min_values']} / {fmt_num(series['p10_values'])} / {fmt_num(series['p25_values'])} / {fmt_num(series['median_values'])} / {fmt_num(series['p75_values'])} / {fmt_num(series['p90_values'])} / {series['max_values']} | {series['min_bytes']} / {fmt_num(series['p10_bytes'])} / {fmt_num(series['p25_bytes'])} / {fmt_num(series['median_bytes'])} / {fmt_num(series['p75_bytes'])} / {fmt_num(series['p90_bytes'])} / {series['max_bytes']} | {series['same_size_fraction']:.6f} | {series['missing_files']} |\n"
                )
            fh.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report sample/index state for dataset recipes.")
    parser.add_argument("recipes", nargs="+", help="Recipe directories or roots containing recipe dirs.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Data directory relative to repo root. Default: .data")
    parser.add_argument("--output-md", default="reports/dataset_state_report.md", help="Markdown output path.")
    parser.add_argument("--output-tsv", default="reports/dataset_state_report.tsv", help="TSV output path.")
    args = parser.parse_args()

    data_root = REPO_ROOT / args.data_dir
    dataset_reports = []
    for recipe_dir in recipe_dirs_from_args(args.recipes):
        manifest = load_manifest(recipe_dir)
        dataset_id = str(manifest.get("dataset_id") or recipe_dir.name)
        roles = series_roles(manifest)
        index_path = data_root / "index" / dataset_id / "samples.jsonl"
        rows = load_index(index_path, data_root)
        dataset_summary, series_summaries = summarize_rows(rows, roles)
        if not rows:
            dataset_summary["status"] = "not_built"
            dataset_summary["reasons"] = ["missing_sample_index"]
        dataset_reports.append(
            {
                "dataset_id": dataset_id,
                "recipe_dir": str(recipe_dir.relative_to(REPO_ROOT)),
                "index_path": str(index_path.relative_to(REPO_ROOT)),
                "dataset": dataset_summary,
                "series": series_summaries,
            }
        )

    output_md = REPO_ROOT / args.output_md
    output_tsv = REPO_ROOT / args.output_tsv
    write_reports(dataset_reports, output_md, output_tsv)
    print(f"wrote {output_md.relative_to(REPO_ROOT)}")
    print(f"wrote {output_tsv.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
