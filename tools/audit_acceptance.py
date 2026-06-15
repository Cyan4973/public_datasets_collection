#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / ".data"
INDEX_ROOT = DATA_ROOT / "index"
DATASETS_ROOT = REPO_ROOT / "datasets"
REPORTS_ROOT = REPO_ROOT / "reports"

MIN_VALUES = 10000
MIN_SAMPLE_BYTES = 100 * 1024
MIN_MEDIAN_SAMPLE_VALUES = 1000

SERIES_ROLE_PRIMARY = "primary"
SERIES_ROLE_AUXILIARY = "auxiliary"


def infer_series_role(series_id: str) -> str:
    return SERIES_ROLE_PRIMARY


def load_series_roles(manifest_path: Path) -> tuple[dict[str, str], list[str]]:
    document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    roles: dict[str, str] = {}
    inferred_auxiliary: list[str] = []
    for series in document.get("series", []):
        series_id = str(series.get("id", "")).strip()
        if not series_id:
            continue
        role = str(series.get("role", "")).strip().lower()
        if role not in {SERIES_ROLE_PRIMARY, SERIES_ROLE_AUXILIARY}:
            role = infer_series_role(series_id)
            if role == SERIES_ROLE_AUXILIARY:
                inferred_auxiliary.append(series_id)
        roles[series_id] = role
    return roles, sorted(inferred_auxiliary)


def classify(
    primary_values: int,
    primary_bytes: int,
    primary_sample_rows: int,
    median_primary_sample_value_count: float,
) -> tuple[str, list[str]]:
    if primary_sample_rows == 0:
        return "broken", ["missing_primary_payload"]
    reasons = []
    if primary_values < MIN_VALUES and primary_bytes < MIN_SAMPLE_BYTES:
        reasons.append("aggregate_floor")
    if median_primary_sample_value_count < MIN_MEDIAN_SAMPLE_VALUES:
        reasons.append("median_sample_floor")
    if reasons:
        return "below_floor", reasons
    return "ok", []


def format_stat(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def format_csv(values: list[str]) -> str:
    if not values:
        return "none"
    return ",".join(values)


def main() -> int:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for manifest in sorted(DATASETS_ROOT.glob("*/manifest.toml")):
        dataset_id = manifest.parent.name
        index_path = INDEX_ROOT / dataset_id / "samples.jsonl"
        series_roles, inferred_auxiliary = load_series_roles(manifest)

        primary_values = 0
        primary_bytes = 0
        primary_sample_rows = 0
        primary_sizes = []
        primary_value_counts = []

        auxiliary_values = 0
        auxiliary_bytes = 0
        auxiliary_sample_rows = 0

        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                series_id = str(obj.get("series_id", "")).strip()
                role = series_roles.get(series_id, infer_series_role(series_id))
                value_count = int(obj.get("value_count", 0))
                sample_size_bytes = int(obj.get("sample_size_bytes", 0))
                if role == SERIES_ROLE_AUXILIARY:
                    auxiliary_values += value_count
                    auxiliary_bytes += sample_size_bytes
                    auxiliary_sample_rows += 1
                    continue
                primary_values += value_count
                primary_bytes += sample_size_bytes
                primary_sample_rows += 1
                primary_sizes.append(sample_size_bytes)
                primary_value_counts.append(value_count)

        median_primary_sample_size_bytes = statistics.median(primary_sizes) if primary_sizes else 0
        median_primary_sample_value_count = statistics.median(primary_value_counts) if primary_value_counts else 0
        status, failure_reasons = classify(
            primary_values,
            primary_bytes,
            primary_sample_rows,
            median_primary_sample_value_count,
        )
        rows.append(
            {
                "dataset_id": dataset_id,
                "status": status,
                "primary_values": primary_values,
                "primary_sample_bytes": primary_bytes,
                "primary_sample_rows": primary_sample_rows,
                "median_primary_sample_value_count": median_primary_sample_value_count,
                "median_primary_sample_size_bytes": median_primary_sample_size_bytes,
                "auxiliary_values": auxiliary_values,
                "auxiliary_sample_bytes": auxiliary_bytes,
                "auxiliary_sample_rows": auxiliary_sample_rows,
                "has_index": index_path.exists(),
                "inferred_auxiliary_series": inferred_auxiliary,
                "failure_reasons": failure_reasons,
            }
        )

    rows.sort(
        key=lambda row: (
            row["status"],
            row["primary_values"],
            row["primary_sample_bytes"],
            row["median_primary_sample_value_count"],
            row["median_primary_sample_size_bytes"],
            row["dataset_id"],
        )
    )

    tsv_path = REPORTS_ROOT / "accepted_recipe_audit.tsv"
    with tsv_path.open("w", encoding="utf-8") as fh:
        fh.write(
            "dataset_id\tstatus\tprimary_values\tprimary_sample_bytes\tprimary_sample_rows\tmedian_primary_sample_value_count\tmedian_primary_sample_size_bytes\tauxiliary_values\tauxiliary_sample_bytes\tauxiliary_sample_rows\thas_index\tinferred_auxiliary_series\tfailure_reasons\n"
        )
        for row in rows:
            fh.write(
                f"{row['dataset_id']}\t{row['status']}\t{row['primary_values']}\t{row['primary_sample_bytes']}\t{row['primary_sample_rows']}\t{format_stat(row['median_primary_sample_value_count'])}\t{format_stat(row['median_primary_sample_size_bytes'])}\t{row['auxiliary_values']}\t{row['auxiliary_sample_bytes']}\t{row['auxiliary_sample_rows']}\t{int(row['has_index'])}\t{format_csv(row['inferred_auxiliary_series'])}\t{format_csv(row['failure_reasons'])}\n"
            )

    broken = [row for row in rows if row["status"] == "broken"]
    below = [row for row in rows if row["status"] == "below_floor"]
    ok = [row for row in rows if row["status"] == "ok"]

    md_path = REPORTS_ROOT / "accepted_recipe_audit.md"
    with md_path.open("w", encoding="utf-8") as fh:
        fh.write("# Accepted Recipe Audit\n\n")
        fh.write(
            f"Acceptance floor: at least `{MIN_VALUES}` primary values total or at least `{MIN_SAMPLE_BYTES}` primary sample bytes, plus median primary sample size at least `{MIN_MEDIAN_SAMPLE_VALUES}` values.\n\n"
        )
        fh.write("Auxiliary series do not count toward acceptance.\n\n")
        fh.write(f"- `ok`: {len(ok)}\n")
        fh.write(f"- `below_floor`: {len(below)}\n")
        fh.write(f"- `broken`: {len(broken)}\n\n")

        if broken:
            fh.write("## Broken\n\n")
            fh.write("| dataset_id | primary_values | primary_sample_bytes | primary_sample_rows | median_primary_sample_value_count | auxiliary_values | auxiliary_sample_rows | reasons |\n")
            fh.write("|---|---:|---:|---:|---:|---:|---:|---|\n")
            for row in broken:
                fh.write(
                    f"| `{row['dataset_id']}` | {row['primary_values']} | {row['primary_sample_bytes']} | {row['primary_sample_rows']} | {format_stat(row['median_primary_sample_value_count'])} | {row['auxiliary_values']} | {row['auxiliary_sample_rows']} | `{format_csv(row['failure_reasons'])}` |\n"
                )

        if broken and below:
            fh.write("\n")

        if below:
            fh.write("## Below Floor\n\n")
            fh.write("| dataset_id | primary_values | primary_sample_bytes | primary_sample_rows | median_primary_sample_value_count | auxiliary_values | auxiliary_sample_rows | reasons |\n")
            fh.write("|---|---:|---:|---:|---:|---:|---:|---|\n")
            for row in below:
                fh.write(
                    f"| `{row['dataset_id']}` | {row['primary_values']} | {row['primary_sample_bytes']} | {row['primary_sample_rows']} | {format_stat(row['median_primary_sample_value_count'])} | {row['auxiliary_values']} | {row['auxiliary_sample_rows']} | `{format_csv(row['failure_reasons'])}` |\n"
                )

    print(f"wrote {tsv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
