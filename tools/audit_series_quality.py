#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / ".data"
INDEX_ROOT = DATA_ROOT / "index"
DATASETS_ROOT = REPO_ROOT / "datasets"
REPORTS_ROOT = REPO_ROOT / "reports"
MINORITY_THRESHOLD = 0.001

FMT_MAP = {
    ("uint", 8): "B",
    ("int", 8): "b",
    # For F16/BF16 degeneracy checks, raw 16-bit words are enough: constant
    # payloads remain constant, and binary-sparse payloads remain binary-sparse.
    ("float", 16): "H",
    ("uint", 16): "H",
    ("int", 16): "h",
    ("uint", 32): "I",
    ("int", 32): "i",
    ("float", 32): "f",
    ("uint", 64): "Q",
    ("int", 64): "q",
    ("float", 64): "d",
}


def iter_values(sample_path: Path, kind: str, bit_width: int, value_count: int):
    fmt = FMT_MAP[(kind, bit_width)]
    raw = sample_path.read_bytes()
    expected_size = struct.calcsize(fmt) * value_count
    if len(raw) != expected_size:
        raise ValueError(f"size_mismatch actual={len(raw)} expected={expected_size}")
    yield from (value[0] for value in struct.iter_unpack("<" + fmt, raw))


def classify_sample(sample_path: Path, kind: str, bit_width: int, value_count: int) -> tuple[str, str]:
    if value_count == 0:
        return "broken", "empty_series"
    counts = {}
    for value in iter_values(sample_path, kind, bit_width, value_count):
        counts[value] = counts.get(value, 0) + 1
        if len(counts) > 2:
            return "ok", ""
    if len(counts) == 1:
        return "constant", f"constant_value={next(iter(counts))}"
    a, b = counts.values()
    minority = min(a, b) / value_count
    if minority < MINORITY_THRESHOLD:
        return "binary_sparse", f"minority_fraction={minority:.8f}"
    return "ok", ""


def main() -> int:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for manifest in sorted(DATASETS_ROOT.glob("*/manifest.toml")):
        dataset_id = manifest.parent.name
        index_path = INDEX_ROOT / dataset_id / "samples.jsonl"
        if not index_path.exists():
            continue
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            sample_path = DATA_ROOT / row["sample_path"]
            if not sample_path.is_file():
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "series_id": row["series_id"],
                        "status": "broken",
                        "detail": "missing_sample",
                        "value_count": row["value_count"],
                    }
                )
                continue
            try:
                status, detail = classify_sample(
                    sample_path,
                    row["numeric_kind"],
                    int(row["bit_width"]),
                    int(row["value_count"]),
                )
            except (KeyError, ValueError) as error:
                status, detail = "broken", str(error)
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "series_id": row["series_id"],
                    "status": status,
                    "detail": detail,
                    "value_count": row["value_count"],
                }
            )

    flagged = [row for row in rows if row["status"] != "ok"]
    flagged.sort(key=lambda row: (row["status"], row["dataset_id"], row["series_id"]))

    tsv_path = REPORTS_ROOT / "degenerate_series_audit.tsv"
    with tsv_path.open("w", encoding="utf-8") as fh:
        fh.write("dataset_id\tseries_id\tstatus\tdetail\tvalue_count\n")
        for row in flagged:
            fh.write(
                f"{row['dataset_id']}\t{row['series_id']}\t{row['status']}\t{row['detail']}\t{row['value_count']}\n"
            )

    md_path = REPORTS_ROOT / "degenerate_series_audit.md"
    with md_path.open("w", encoding="utf-8") as fh:
        fh.write("# Degenerate Series Audit\n\n")
        fh.write(f"- constant or empty series are rejected\n")
        fh.write(f"- binary series with minority fraction below `{MINORITY_THRESHOLD}` are rejected unless explicitly justified\n\n")
        fh.write(f"- flagged series: {len(flagged)}\n\n")
        if flagged:
            fh.write("| dataset_id | series_id | status | detail | value_count |\n")
            fh.write("|---|---|---|---|---:|\n")
            for row in flagged:
                fh.write(
                    f"| `{row['dataset_id']}` | `{row['series_id']}` | {row['status']} | `{row['detail']}` | {row['value_count']} |\n"
                )

    print(f"wrote {tsv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
