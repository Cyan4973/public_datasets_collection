#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / ".data"
INDEX_ROOT = DATA_ROOT / "index"
DATASETS_ROOT = REPO_ROOT / "datasets"
REPORTS_ROOT = REPO_ROOT / "reports"

MIN_VALUES = 10000
MIN_SAMPLE_BYTES = 100 * 1024
MIN_MEDIAN_SAMPLE_VALUES = 1000


def classify(total_values: int, total_bytes: int, sample_rows: int, median_sample_value_count: float) -> tuple[str, list[str]]:
    if total_values == 0 or total_bytes == 0 or sample_rows == 0:
        return "broken", ["missing_or_empty_index"]
    reasons = []
    if total_values < MIN_VALUES and total_bytes < MIN_SAMPLE_BYTES:
        reasons.append("aggregate_floor")
    if median_sample_value_count < MIN_MEDIAN_SAMPLE_VALUES:
        reasons.append("median_sample_floor")
    if reasons:
        return "below_floor", reasons
    return "ok", []


def format_stat(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def main() -> int:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for manifest in sorted(DATASETS_ROOT.glob("*/manifest.toml")):
        dataset_id = manifest.parent.name
        index_path = INDEX_ROOT / dataset_id / "samples.jsonl"
        total_values = 0
        total_bytes = 0
        sample_rows = 0
        sample_sizes = []
        sample_value_counts = []
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                value_count = int(obj.get("value_count", 0))
                total_values += value_count
                sample_size_bytes = int(obj.get("sample_size_bytes", 0))
                total_bytes += sample_size_bytes
                sample_rows += 1
                sample_sizes.append(sample_size_bytes)
                sample_value_counts.append(value_count)
        median_sample_size_bytes = statistics.median(sample_sizes) if sample_sizes else 0
        median_sample_value_count = statistics.median(sample_value_counts) if sample_value_counts else 0
        status, failure_reasons = classify(total_values, total_bytes, sample_rows, median_sample_value_count)
        rows.append(
            {
                "dataset_id": dataset_id,
                "status": status,
                "total_values": total_values,
                "total_sample_bytes": total_bytes,
                "sample_rows": sample_rows,
                "median_sample_value_count": median_sample_value_count,
                "median_sample_size_bytes": median_sample_size_bytes,
                "has_index": index_path.exists(),
                "failure_reasons": ",".join(failure_reasons),
            }
        )

    rows.sort(
        key=lambda row: (
            row["status"],
            row["total_values"],
            row["total_sample_bytes"],
            row["median_sample_value_count"],
            row["median_sample_size_bytes"],
            row["dataset_id"],
        )
    )

    tsv_path = REPORTS_ROOT / "accepted_recipe_audit.tsv"
    with tsv_path.open("w", encoding="utf-8") as fh:
        fh.write(
            "dataset_id\tstatus\ttotal_values\ttotal_sample_bytes\tsample_rows\tmedian_sample_value_count\tmedian_sample_size_bytes\thas_index\tfailure_reasons\n"
        )
        for row in rows:
            fh.write(
                f"{row['dataset_id']}\t{row['status']}\t{row['total_values']}\t{row['total_sample_bytes']}\t{row['sample_rows']}\t{format_stat(row['median_sample_value_count'])}\t{format_stat(row['median_sample_size_bytes'])}\t{int(row['has_index'])}\t{row['failure_reasons']}\n"
            )

    broken = [row for row in rows if row["status"] == "broken"]
    below = [row for row in rows if row["status"] == "below_floor"]
    ok = [row for row in rows if row["status"] == "ok"]

    md_path = REPORTS_ROOT / "accepted_recipe_audit.md"
    with md_path.open("w", encoding="utf-8") as fh:
        fh.write("# Accepted Recipe Audit\n\n")
        fh.write(
            f"Acceptance floor: at least `{MIN_VALUES}` numeric values total or at least `{MIN_SAMPLE_BYTES}` bytes of generated sample payload, plus median generated sample size at least `{MIN_MEDIAN_SAMPLE_VALUES}` values.\n\n"
        )
        fh.write(f"- `ok`: {len(ok)}\n")
        fh.write(f"- `below_floor`: {len(below)}\n")
        fh.write(f"- `broken`: {len(broken)}\n\n")

        if broken:
            fh.write("## Broken\n\n")
            fh.write("| dataset_id | total_values | total_sample_bytes | sample_rows | median_sample_value_count | median_sample_size_bytes | reasons |\n")
            fh.write("|---|---:|---:|---:|---:|---:|---|\n")
            for row in broken:
                fh.write(
                    f"| `{row['dataset_id']}` | {row['total_values']} | {row['total_sample_bytes']} | {row['sample_rows']} | {format_stat(row['median_sample_value_count'])} | {format_stat(row['median_sample_size_bytes'])} | `{row['failure_reasons']}` |\n"
                )
            fh.write("\n")

        if below:
            fh.write("## Below Floor\n\n")
            fh.write("| dataset_id | total_values | total_sample_bytes | sample_rows | median_sample_value_count | median_sample_size_bytes | reasons |\n")
            fh.write("|---|---:|---:|---:|---:|---:|---|\n")
            for row in below:
                fh.write(
                    f"| `{row['dataset_id']}` | {row['total_values']} | {row['total_sample_bytes']} | {row['sample_rows']} | {format_stat(row['median_sample_value_count'])} | {format_stat(row['median_sample_size_bytes'])} | `{row['failure_reasons']}` |\n"
                )
            fh.write("\n")

    print(f"wrote {tsv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
