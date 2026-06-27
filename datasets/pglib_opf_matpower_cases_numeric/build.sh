#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="pglib_opf_matpower_cases_numeric"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLE_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLE_DIR
export PGLIB_MIN_VALUES="${PGLIB_MIN_VALUES:-1000}"
export PGLIB_MAX_PRIMARY_BYTES="${PGLIB_MAX_PRIMARY_BYTES:-1000000000}"
export PGLIB_MAX_CASES="${PGLIB_MAX_CASES:-0}"
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import re
import shutil
import statistics
import struct
import tarfile
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
ROOT = Path(os.environ["REPO_ROOT"])
DATA_DIR = os.environ["DATA_DIR"]
DATA_ROOT = ROOT / DATA_DIR
DOWNLOAD_DIR = Path(os.environ["DOWNLOAD_DIR"])
EXTRACT_DIR = Path(os.environ["EXTRACT_DIR"])
FILTER_DIR = Path(os.environ["FILTER_DIR"])
INDEX_DIR = Path(os.environ["INDEX_DIR"])
SAMPLE_DIR = Path(os.environ["SAMPLE_DIR"])
MIN_VALUES = int(os.environ["PGLIB_MIN_VALUES"])
MAX_PRIMARY_BYTES = int(os.environ["PGLIB_MAX_PRIMARY_BYTES"])
MAX_CASES = int(os.environ["PGLIB_MAX_CASES"])
FIELDS = {
    "bus": "bus_matrix_f64",
    "branch": "branch_matrix_f64",
    "gen": "gen_matrix_f64",
    "gencost": "gencost_matrix_f64",
}
TOKEN_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eEdD][+-]?\d+)?$")


def slugify(value: str) -> str:
    value = value.rsplit(".", 1)[0]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def ensure_source_tree() -> Path:
    source = EXTRACT_DIR / "source"
    if any(source.rglob("pglib_opf_case*.m")):
        return source
    archive = DOWNLOAD_DIR / "pglib-opf.tar.gz"
    if not archive.is_file():
        raise SystemExit(
            f"missing local archive {archive}; run download.sh before build.sh"
        )
    tmp = EXTRACT_DIR / "source.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(source, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            target = (tmp / member.name).resolve()
            if not str(target).startswith(str(tmp.resolve()) + os.sep):
                raise SystemExit(f"unsafe archive member path: {member.name}")
        tar.extractall(tmp)
    tmp.rename(source)
    return source


def parse_matrix(text: str, field: str) -> tuple[int, int, list[float]]:
    start_re = re.compile(r"\bmpc\." + re.escape(field) + r"\s*=\s*\[")
    in_block = False
    row_tokens: list[str] = []
    rows: list[list[float]] = []

    def finalize_row() -> None:
        nonlocal row_tokens
        if not row_tokens:
            return
        parsed: list[float] = []
        for token in row_tokens:
            normalized = token.replace("D", "E").replace("d", "e")
            if not TOKEN_RE.fullmatch(normalized):
                raise ValueError(f"nonnumeric token in mpc.{field}: {token!r}")
            value = float(normalized)
            if not math.isfinite(value):
                raise ValueError(f"non-finite token in mpc.{field}: {token!r}")
            parsed.append(value)
        rows.append(parsed)
        row_tokens = []

    def feed(segment: str) -> None:
        nonlocal row_tokens
        segment = segment.replace("...", " ")
        parts = segment.split(";")
        for idx, part in enumerate(parts):
            cleaned = (
                part.replace(",", " ")
                .replace("[", " ")
                .replace("]", " ")
                .strip()
            )
            if cleaned:
                row_tokens.extend(cleaned.split())
            if idx < len(parts) - 1:
                finalize_row()

    for raw_line in text.splitlines():
        line = raw_line.split("%", 1)[0]
        if not in_block:
            match = start_re.search(line)
            if not match:
                continue
            in_block = True
            line = line[match.end():]
        if "]" in line:
            before = line.split("]", 1)[0]
            feed(before)
            finalize_row()
            in_block = False
            break
        feed(line)

    if in_block:
        raise ValueError(f"unterminated mpc.{field} matrix")
    if not rows:
        raise ValueError(f"missing mpc.{field} matrix")
    width = len(rows[0])
    if width == 0:
        raise ValueError(f"empty mpc.{field} row")
    for idx, row in enumerate(rows, 1):
        if len(row) != width:
            raise ValueError(
                f"inconsistent mpc.{field} width at row {idx}: {len(row)} != {width}"
            )
    values = [value for row in rows for value in row]
    return len(rows), width, values


def write_f64(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        for offset in range(0, len(values), 8192):
            chunk = values[offset : offset + 8192]
            fh.write(struct.pack("<" + "d" * len(chunk), *chunk))


source = ensure_source_tree()
case_files = sorted(source.rglob("pglib_opf_case*.m"))
if MAX_CASES > 0:
    case_files = case_files[:MAX_CASES]
if not case_files:
    raise SystemExit("no local pglib_opf_case*.m files found")

shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
shutil.rmtree(INDEX_DIR, ignore_errors=True)
FILTER_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)
for series_id in FIELDS.values():
    (SAMPLE_DIR / series_id).mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skip_counts: dict[str, int] = {}
total_primary_bytes = 0

for case_file in case_files:
    rel_case = case_file.relative_to(source)
    case_id = slugify(case_file.name)
    text = case_file.read_text(encoding="utf-8", errors="replace")
    case_record: dict[str, object] = {
        "case_file": str(rel_case),
        "case_id": case_id,
        "source_bytes": case_file.stat().st_size,
        "emitted": [],
        "skipped": [],
    }
    for field, series_id in FIELDS.items():
        try:
            row_count, column_count, values = parse_matrix(text, field)
        except ValueError as exc:
            reason = f"{field}:parse_error"
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
            case_record["skipped"].append({"field": field, "reason": str(exc)})
            continue

        value_count = len(values)
        if value_count < MIN_VALUES:
            reason = f"{field}:below_min_values"
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
            case_record["skipped"].append(
                {
                    "field": field,
                    "reason": reason,
                    "rows": row_count,
                    "columns": column_count,
                    "value_count": value_count,
                }
            )
            continue
        if min(values) == max(values):
            reason = f"{field}:constant"
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
            case_record["skipped"].append(
                {"field": field, "reason": reason, "value_count": value_count}
            )
            continue

        sample_size_bytes = value_count * 8
        if total_primary_bytes + sample_size_bytes > MAX_PRIMARY_BYTES:
            raise SystemExit(
                f"primary bytes exceed cap after {case_id}/{field}: "
                f"{total_primary_bytes + sample_size_bytes} > {MAX_PRIMARY_BYTES}"
            )

        rel_sample = (
            Path("samples")
            / DATASET_ID
            / series_id
            / f"{case_id}.{field}.f64.bin"
        )
        sample_path = DATA_ROOT / rel_sample
        write_f64(sample_path, values)
        total_primary_bytes += sample_size_bytes
        row = {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": str(rel_sample),
            "source_case_file": str(rel_case),
            "case_id": case_id,
            "matrix_field": field,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": sample_size_bytes,
            "value_count": value_count,
            "sample_format": "raw homogeneous float64 row-major matrix",
            "sample_geometry": "matpower_case_matrix",
            "sample_rank": 2,
            "sample_shape": [row_count, column_count],
            "sample_axes": ["row", "column"],
            "min": min(values),
            "max": max(values),
        }
        index_rows.append(row)
        case_record["emitted"].append(
            {
                "field": field,
                "series_id": series_id,
                "rows": row_count,
                "columns": column_count,
                "value_count": value_count,
                "sample_size_bytes": sample_size_bytes,
            }
        )
    records.append(case_record)

primary_counts = [int(row["value_count"]) for row in index_rows]
primary_bytes = [int(row["sample_size_bytes"]) for row in index_rows]
if len(index_rows) < 2:
    raise SystemExit(f"only {len(index_rows)} primary samples emitted")
if sum(primary_counts) < 10_000 and sum(primary_bytes) < 102_400:
    raise SystemExit(
        f"below aggregate floor: values={sum(primary_counts)} bytes={sum(primary_bytes)}"
    )
median_values = statistics.median(primary_counts)
if median_values < 1_000:
    raise SystemExit(f"median sample values below floor: {median_values}")

with (INDEX_DIR / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

series_stats: dict[str, dict[str, int]] = {}
for row in index_rows:
    series_id = str(row["series_id"])
    stats = series_stats.setdefault(series_id, {"sample_count": 0, "total_size_bytes": 0, "total_values": 0})
    stats["sample_count"] += 1
    stats["total_size_bytes"] += int(row["sample_size_bytes"])
    stats["total_values"] += int(row["value_count"])

stats = {
    "dataset_id": DATASET_ID,
    "source_case_count": len(case_files),
    "primary_sample_count": len(index_rows),
    "primary_values": sum(primary_counts),
    "primary_sample_bytes": sum(primary_bytes),
    "median_primary_values": median_values,
    "min_values_per_sample": MIN_VALUES,
    "series": series_stats,
    "skip_counts": skip_counts,
    "records": records,
}
(FILTER_DIR / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"built samples={len(index_rows)} bytes={sum(primary_bytes)} "
    f"median_values={int(median_values)} cases={len(case_files)} "
    f"series={series_stats}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
