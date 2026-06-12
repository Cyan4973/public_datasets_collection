#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / ".data"
INDEX_ROOT = DATA_ROOT / "index"
DATASETS_ROOT = REPO_ROOT / "datasets"
REPORTS_ROOT = REPO_ROOT / "reports"

MIN_VALUES = 10000
MIN_SAMPLE_BYTES = 100 * 1024


def classify(total_values: int, total_bytes: int) -> str:
    if total_values == 0 or total_bytes == 0:
        return "broken"
    if total_values < MIN_VALUES and total_bytes < MIN_SAMPLE_BYTES:
        return "below_floor"
    return "ok"


def main() -> int:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for manifest in sorted(DATASETS_ROOT.glob("*/manifest.toml")):
        dataset_id = manifest.parent.name
        index_path = INDEX_ROOT / dataset_id / "samples.jsonl"
        total_values = 0
        total_bytes = 0
        sample_rows = 0
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                total_values += int(obj.get("value_count", 0))
                total_bytes += int(obj.get("sample_size_bytes", 0))
                sample_rows += 1
        status = classify(total_values, total_bytes)
        rows.append(
            {
                "dataset_id": dataset_id,
                "status": status,
                "total_values": total_values,
                "total_sample_bytes": total_bytes,
                "sample_rows": sample_rows,
                "has_index": index_path.exists(),
            }
        )

    rows.sort(key=lambda row: (row["status"], row["total_values"], row["total_sample_bytes"], row["dataset_id"]))

    tsv_path = REPORTS_ROOT / "accepted_recipe_audit.tsv"
    with tsv_path.open("w", encoding="utf-8") as fh:
        fh.write(
            "dataset_id\tstatus\ttotal_values\ttotal_sample_bytes\tsample_rows\thas_index\n"
        )
        for row in rows:
            fh.write(
                f"{row['dataset_id']}\t{row['status']}\t{row['total_values']}\t{row['total_sample_bytes']}\t{row['sample_rows']}\t{int(row['has_index'])}\n"
            )

    broken = [row for row in rows if row["status"] == "broken"]
    below = [row for row in rows if row["status"] == "below_floor"]
    ok = [row for row in rows if row["status"] == "ok"]

    md_path = REPORTS_ROOT / "accepted_recipe_audit.md"
    with md_path.open("w", encoding="utf-8") as fh:
        fh.write("# Accepted Recipe Audit\n\n")
        fh.write(
            f"Acceptance floor: at least `{MIN_VALUES}` numeric values total or at least `{MIN_SAMPLE_BYTES}` bytes of generated sample payload.\n\n"
        )
        fh.write(f"- `ok`: {len(ok)}\n")
        fh.write(f"- `below_floor`: {len(below)}\n")
        fh.write(f"- `broken`: {len(broken)}\n\n")

        if broken:
            fh.write("## Broken\n\n")
            fh.write("| dataset_id | total_values | total_sample_bytes | sample_rows |\n")
            fh.write("|---|---:|---:|---:|\n")
            for row in broken:
                fh.write(
                    f"| `{row['dataset_id']}` | {row['total_values']} | {row['total_sample_bytes']} | {row['sample_rows']} |\n"
                )
            fh.write("\n")

        if below:
            fh.write("## Below Floor\n\n")
            fh.write("| dataset_id | total_values | total_sample_bytes | sample_rows |\n")
            fh.write("|---|---:|---:|---:|\n")
            for row in below:
                fh.write(
                    f"| `{row['dataset_id']}` | {row['total_values']} | {row['total_sample_bytes']} | {row['sample_rows']} |\n"
                )
            fh.write("\n")

    print(f"wrote {tsv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
