#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dataone_solr"
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
export DATAONE_SOLR_MIN_RETAINED_RECORDS="${DATAONE_SOLR_MIN_RETAINED_RECORDS:-5000}"
export DATAONE_SOLR_MIN_REPLICA_RECORDS="${DATAONE_SOLR_MIN_REPLICA_RECORDS:-1000}"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import statistics
import struct
from datetime import datetime, timezone
from pathlib import Path

DATASET_ID = "dataone_solr"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["DATAONE_SOLR_MIN_RETAINED_RECORDS"])
min_replica_records = int(os.environ["DATAONE_SOLR_MIN_REPLICA_RECORDS"])


def load_source_docs() -> tuple[list[dict], int]:
    page_dir = download_dir / "pages"
    page_files = sorted(page_dir.glob("page_*.json"))
    if page_files:
        docs: list[dict] = []
        for page_file in page_files:
            obj = json.loads(page_file.read_text(encoding="utf-8"))
            response = obj.get("response")
            if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
                raise SystemExit(f"{page_file}: missing response.docs list")
            docs.extend(response["docs"])
        return docs, len(page_files)

    legacy = download_dir / "dataone_solr.json"
    if legacy.is_file():
        obj = json.loads(legacy.read_text(encoding="utf-8"))
        response = obj.get("response")
        if isinstance(response, dict) and isinstance(response.get("docs"), list):
            return response["docs"], 1
    raise SystemExit(f"missing local DataONE Solr data under {download_dir}; run download.sh first")


def parse_timestamp(value: object, field: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing {field}")
    token = value.strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    parsed = datetime.fromisoformat(token)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = int(parsed.timestamp())
    if seconds < 0 or seconds > 0xFFFFFFFF:
        raise ValueError(f"{field} epoch seconds out of uint32 range: {seconds}")
    milliseconds = seconds * 1000 + parsed.microsecond // 1000
    year = parsed.year
    if year < 1000 or year > 3000:
        raise ValueError(f"{field} year out of plausible range: {year}")
    return seconds, milliseconds, year


def as_uint(value: object, field: str, max_value: int) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > max_value:
        raise ValueError(f"{field} out of range [0, {max_value}]: {parsed}")
    return parsed


source_docs, source_pages = load_source_docs()
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

series_meta = {
    "dataone_size": ("uint", 64, 8, "Q", "Object size in bytes."),
    "dataone_number_replicas": ("uint", 16, 2, "H", "Replica count reported by DataONE when present."),
    "dataone_date_uploaded": ("uint", 32, 4, "I", "Upload timestamp as UTC epoch seconds."),
    "dataone_update_date": ("uint", 32, 4, "I", "Update timestamp as UTC epoch seconds."),
    "dataone_date_modified": ("uint", 64, 8, "Q", "Modified timestamp as UTC epoch milliseconds."),
    "dataone_uploaded_year": ("uint", 16, 2, "H", "Upload calendar year derived from dateUploaded."),
    "dataone_modified_year": ("uint", 16, 2, "H", "Modified calendar year derived from dateModified."),
}
values: dict[str, list[int]] = {series_id: [] for series_id in series_meta}
seen_ids: set[str] = set()
source_records = 0
skipped_required = 0
skipped_replica = 0
duplicates = 0

for row in source_docs:
    source_records += 1
    try:
        record_id = str(row.get("id") or "")
        if record_id and record_id in seen_ids:
            duplicates += 1
            continue
        size = as_uint(row["size"], "size", 0xFFFFFFFFFFFFFFFF)
        uploaded_seconds, _uploaded_ms, uploaded_year = parse_timestamp(row["dateUploaded"], "dateUploaded")
        update_seconds, _update_ms, _update_year = parse_timestamp(row["updateDate"], "updateDate")
        _modified_seconds, modified_ms, modified_year = parse_timestamp(row["dateModified"], "dateModified")
    except Exception:
        skipped_required += 1
        continue

    if record_id:
        seen_ids.add(record_id)
    values["dataone_size"].append(size)
    values["dataone_date_uploaded"].append(uploaded_seconds)
    values["dataone_update_date"].append(update_seconds)
    values["dataone_date_modified"].append(modified_ms)
    values["dataone_uploaded_year"].append(uploaded_year)
    values["dataone_modified_year"].append(modified_year)

    try:
        replica_count = as_uint(row["numberReplicas"], "numberReplicas", 0xFFFF)
    except Exception:
        skipped_replica += 1
    else:
        values["dataone_number_replicas"].append(replica_count)

retained = len(values["dataone_size"])
if retained < min_retained:
    raise SystemExit(f"only {retained} retained rows < DATAONE_SOLR_MIN_RETAINED_RECORDS={min_retained}; rerun download.sh")

required_series = [series_id for series_id in series_meta if series_id != "dataone_number_replicas"]
required_lengths = {len(values[series_id]) for series_id in required_series}
if required_lengths != {retained}:
    raise SystemExit(f"required series length mismatch: {sorted(required_lengths)}")
if len(values["dataone_number_replicas"]) < min_replica_records:
    raise SystemExit(
        "only "
        f"{len(values['dataone_number_replicas'])} numberReplicas rows "
        f"< DATAONE_SOLR_MIN_REPLICA_RECORDS={min_replica_records}; rerun download.sh"
    )

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
    natural_record_count = retained if series_id != "dataone_number_replicas" else len(series_values)
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
            "sample_geometry": "dataone_solr_record_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["dataone_solr_record"],
            "natural_record_kind": "dataone_solr_doc",
            "natural_record_count": natural_record_count,
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
            "source_pages": source_pages,
            "source_records": source_records,
            "retained_records": retained,
            "skipped_required_records": skipped_required,
            "skipped_number_replicas": skipped_replica,
            "duplicate_records": duplicates,
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
    f"replica_records={len(values['dataone_number_replicas'])} "
    f"values={sum(counts)} bytes={sum(byte_counts)} "
    f"skipped_required={skipped_required} skipped_number_replicas={skipped_replica} duplicates={duplicates}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
