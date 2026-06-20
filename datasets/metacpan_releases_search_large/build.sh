#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="metacpan_releases_search_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_re = re.compile(r"release_page_(\d+)\.json$")
page_paths = sorted(
    [p for p in page_dir.glob("release_page_*.json") if page_re.search(p.name)],
    key=lambda p: int(page_re.search(p.name).group(1)),
)
if not page_paths:
    raise SystemExit(f"no downloaded MetaCPAN pages found under {page_dir}")

# series_id -> (numeric_kind, bit_width, struct_code)
meta = {
    "metacpan_version_numified": ("float", 64, "d"),
    "metacpan_stat_size": ("uint", 32, "I"),
    "metacpan_stat_mtime": ("uint", 32, "I"),
    "metacpan_dependency_count": ("uint", 16, "H"),
    "metacpan_provides_count": ("uint", 16, "H"),
    "metacpan_tests_pass": ("uint", 32, "I"),
    "metacpan_tests_fail": ("uint", 32, "I"),
    "metacpan_tests_na": ("uint", 32, "I"),
    "metacpan_tests_unknown": ("uint", 32, "I"),
}
vals: dict[str, list] = {sid: [] for sid in meta}
if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
for sid in vals:
    (samples_dir / sid).mkdir(parents=True, exist_ok=True)


def as_uint(value: object, key: str, max_value: int) -> int:
    count = int(value)
    if count < 0 or count > max_value:
        raise ValueError(f"{key} out of range [0, {max_value}]: {count}")
    return count


def count_array(source: dict, key: str, max_value: int) -> int:
    value = source.get(key) or []
    if not isinstance(value, list):
        raise ValueError(f"{key} is not a list")
    return min(len(value), max_value)


rows_total = 0
rows_skipped = 0
seen_ids: set[str] = set()
for path in page_paths:
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    for hit in obj["hits"]["hits"]:
        rows_total += 1
        before = len(vals["metacpan_version_numified"])
        try:
            rid = hit["_id"]
            if rid in seen_ids:
                raise ValueError(f"duplicate MetaCPAN release id {rid}")
            seen_ids.add(rid)
            source = hit["_source"]
            stat = source.get("stat") or {}
            tests = source.get("tests") or {}
            vals["metacpan_version_numified"].append(float(source["version_numified"]))
            vals["metacpan_stat_size"].append(as_uint(stat.get("size") or 0, "stat.size", 0xFFFFFFFF))
            vals["metacpan_stat_mtime"].append(as_uint(stat.get("mtime") or 0, "stat.mtime", 0xFFFFFFFF))
            vals["metacpan_dependency_count"].append(count_array(source, "dependency", 0xFFFF))
            vals["metacpan_provides_count"].append(count_array(source, "provides", 0xFFFF))
            vals["metacpan_tests_pass"].append(as_uint(tests.get("pass") or 0, "tests.pass", 0xFFFFFFFF))
            vals["metacpan_tests_fail"].append(as_uint(tests.get("fail") or 0, "tests.fail", 0xFFFFFFFF))
            vals["metacpan_tests_na"].append(as_uint(tests.get("na") or 0, "tests.na", 0xFFFFFFFF))
            vals["metacpan_tests_unknown"].append(as_uint(tests.get("unknown") or 0, "tests.unknown", 0xFFFFFFFF))
        except Exception:
            for series_values in vals.values():
                while len(series_values) > before:
                    series_values.pop()
            rows_skipped += 1

kept_rows = len(vals["metacpan_version_numified"])
if len({len(series_values) for series_values in vals.values()}) != 1:
    raise SystemExit("series length mismatch after filtering")
if kept_rows == 0:
    raise SystemExit("no rows kept")

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
        {
            "dataset_id": "metacpan_releases_search_large",
            "series_id": sid,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "table_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "table_row_count": kept_rows,
            "table_column_count": len(meta),
            "natural_record_kind": "metacpan_release_row",
            "natural_record_count": kept_rows,
            "natural_record_values": len(meta),
        }
    )

primary_bytes = sum(row["sample_size_bytes"] for row in rows)
primary_values = sum(row["value_count"] for row in rows)
stats_out = {
    "dataset_id": "metacpan_releases_search_large",
    "downloaded_pages": len(page_paths),
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "rows_kept": kept_rows,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built rows_kept={kept_rows} rows_skipped={rows_skipped} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
