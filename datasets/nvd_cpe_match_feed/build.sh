#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nvd_cpe_match_feed"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export NVD_CPE_MATCH_MIN_RETAINED_RECORDS="${NVD_CPE_MATCH_MIN_RETAINED_RECORDS:-5000}"
python3 - <<'PY'
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "nvd_cpe_match_feed"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["NVD_CPE_MATCH_MIN_RETAINED_RECORDS"])


def load_wrappers() -> list[dict]:
    combined_path = download_dir / "nvd_cpe_match_feed.json"
    if combined_path.is_file():
        obj = json.loads(combined_path.read_text(encoding="utf-8"))
        rows = obj.get("matchStrings")
        if not isinstance(rows, list):
            raise SystemExit(f"bad NVD CPE match payload: {combined_path}")
        return rows

    page_paths = sorted((download_dir / "pages").glob("page_*.json"))
    if page_paths:
        out = []
        for page_path in page_paths:
            obj = json.loads(page_path.read_text(encoding="utf-8"))
            rows = obj.get("matchStrings")
            if not isinstance(rows, list):
                raise SystemExit(f"bad NVD CPE match payload: {page_path}")
            out.extend(rows)
        return out

    raise SystemExit(f"missing local NVD CPE match payload under {download_dir}; run download.sh first")


def parse_timestamp(value: object, field: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{field} is not a timestamp string")
    token = value.strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(token)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    seconds = int(parsed.timestamp())
    if seconds < 0 or seconds > 0xFFFFFFFF:
        raise ValueError(f"{field} out of uint32 range: {seconds}")
    return seconds


series_meta = {
    "nvd_cpe_last_modified_at_u32": (
        "uint",
        32,
        4,
        "I",
        "NVD CPE match-string last-modified timestamp, seconds since Unix epoch.",
    ),
    "nvd_cpe_cpe_last_modified_at_u32": (
        "uint",
        32,
        4,
        "I",
        "Referenced CPE name last-modified timestamp, seconds since Unix epoch.",
    ),
    "nvd_cpe_match_count_u16": (
        "uint",
        16,
        2,
        "H",
        "Number of CPE name matches attached to one match string.",
    ),
}
values: dict[str, list[int]] = {series_id: [] for series_id in series_meta}
wrappers = load_wrappers()
seen = set()
skipped = 0

for wrapper in wrappers:
    try:
        if not isinstance(wrapper, dict):
            raise ValueError("wrapper is not an object")
        match = wrapper.get("matchString")
        if not isinstance(match, dict):
            raise ValueError("matchString is not an object")
        key = match.get("matchCriteriaId") or json.dumps(match, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        last_modified = parse_timestamp(match["lastModified"], "lastModified")
        cpe_last_modified = parse_timestamp(match["cpeLastModified"], "cpeLastModified")
        matches = match.get("matches", [])
        if matches is None:
            matches = []
        if not isinstance(matches, list):
            raise ValueError("matches is not a list")
        match_count = len(matches)
        if match_count > 0xFFFF:
            raise ValueError(f"match_count out of uint16 range: {match_count}")
    except Exception:
        skipped += 1
        continue
    values["nvd_cpe_last_modified_at_u32"].append(last_modified)
    values["nvd_cpe_cpe_last_modified_at_u32"].append(cpe_last_modified)
    values["nvd_cpe_match_count_u16"].append(match_count)

retained = len(values["nvd_cpe_last_modified_at_u32"])
if retained < min_retained:
    raise SystemExit(
        f"only {retained} retained rows < NVD_CPE_MATCH_MIN_RETAINED_RECORDS={min_retained}; rerun download.sh"
    )

lengths = {len(series_values) for series_values in values.values()}
if lengths != {retained}:
    raise SystemExit(f"series length mismatch: {sorted(lengths)}")

counts = [len(series_values) for series_values in values.values()]
byte_counts = [
    len(values[series_id]) * element_size
    for series_id, (_kind, _bits, element_size, _code, _description) in series_meta.items()
]
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample values below floor: {statistics.median(counts)}")
for series_id, series_values in values.items():
    if min(series_values) == max(series_values):
        raise SystemExit(f"constant sample after filtering: {series_id}")

index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)

rows = []
for series_id, (kind, bits, element_size, code, description) in series_meta.items():
    series_values = values[series_id]
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(series_values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(series_values), 8192):
            chunk = series_values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(series_values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "nvd_cpe_match_string_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["nvd_cpe_match_string"],
            "natural_record_kind": "nvd_cpe_match_string",
            "natural_record_count": retained,
            "natural_record_values": 1,
            "field_description": description,
            "min": min(series_values),
            "max": max(series_values),
        }
    )

counts = [int(row["value_count"]) for row in rows]
byte_counts = [int(row["sample_size_bytes"]) for row in rows]
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_records": len(wrappers),
            "retained_records": retained,
            "skipped_records": skipped,
            "primary_values": sum(counts),
            "primary_sample_bytes": sum(byte_counts),
            "median_primary_values": statistics.median(counts),
            "series": {
                row["series_id"]: {
                    "sample_count": 1,
                    "total_values": int(row["value_count"]),
                    "total_size_bytes": int(row["sample_size_bytes"]),
                    "min": int(row["min"]),
                    "max": int(row["max"]),
                }
                for row in rows
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(rows)} retained_records={retained} "
    f"values={sum(counts)} bytes={sum(byte_counts)} skipped={skipped}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
