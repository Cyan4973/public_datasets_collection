#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gleif_lei_records"
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
export GLEIF_MIN_RETAINED_RECORDS="${GLEIF_MIN_RETAINED_RECORDS:-5000}"
python3 - <<'PY'
from __future__ import annotations

import datetime as dt
import json
import math
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "gleif_lei_records"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["GLEIF_MIN_RETAINED_RECORDS"])
epoch = dt.date(1970, 1, 1)


def parse_days(value: object) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError("missing date")
    token = value[:10]
    parsed = dt.date.fromisoformat(token)
    return (parsed - epoch).days


def list_count(value: object, field: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, list):
        raise ValueError(f"{field} is not a list")
    if len(value) > 0xFFFF:
        raise ValueError(f"{field} count overflows uint16")
    return len(value)


page_dir = download_dir / "pages"
page_files = sorted(page_dir.glob("page_*.json"))
if not page_files:
    legacy = download_dir / "gleif_lei_records.json"
    if legacy.is_file():
        page_files = [legacy]
if not page_files:
    raise SystemExit(f"missing local GLEIF pages under {page_dir}; run download.sh first")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

series_meta = {
    "gleif_entity_creation_days_i32": ("int", 32, 4, "i", "required"),
    "gleif_initial_registration_days_i32": ("int", 32, 4, "i", "required"),
    "gleif_last_update_days_i32": ("int", 32, 4, "i", "required"),
    "gleif_next_renewal_days_i32": ("int", 32, 4, "i", "optional"),
    "gleif_legal_address_line_count_u16": ("uint", 16, 2, "H", "required"),
    "gleif_other_names_count_u16": ("uint", 16, 2, "H", "required"),
    "gleif_other_validation_authority_count_u16": ("uint", 16, 2, "H", "required"),
}
values: dict[str, list[int]] = {series_id: [] for series_id in series_meta}
seen: set[str] = set()
source_records = 0
skipped = 0
duplicates = 0

for page_file in page_files:
    obj = json.loads(page_file.read_text(encoding="utf-8"))
    data = obj.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"{page_file}: missing data list")
    source_records += len(data)
    for row in data:
        try:
            lei = str((row.get("attributes") or {}).get("lei") or row.get("id") or "")
            if lei and lei in seen:
                duplicates += 1
                continue
            attrs = row["attributes"]
            entity = attrs["entity"]
            reg = attrs["registration"]
            entity_creation = parse_days(entity["creationDate"])
            initial_registration = parse_days(reg["initialRegistrationDate"])
            last_update = parse_days(reg["lastUpdateDate"])
            legal_address_count = list_count((entity.get("legalAddress") or {}).get("addressLines"), "legalAddress.addressLines")
            other_names_count = list_count(entity.get("otherNames"), "entity.otherNames")
            other_validation_count = list_count(reg.get("otherValidationAuthorities"), "registration.otherValidationAuthorities")
            next_renewal_raw = reg.get("nextRenewalDate")
            next_renewal = parse_days(next_renewal_raw) if next_renewal_raw else None
        except Exception:
            skipped += 1
            continue
        if lei:
            seen.add(lei)
        values["gleif_entity_creation_days_i32"].append(entity_creation)
        values["gleif_initial_registration_days_i32"].append(initial_registration)
        values["gleif_last_update_days_i32"].append(last_update)
        values["gleif_legal_address_line_count_u16"].append(legal_address_count)
        values["gleif_other_names_count_u16"].append(other_names_count)
        values["gleif_other_validation_authority_count_u16"].append(other_validation_count)
        if next_renewal is not None:
            values["gleif_next_renewal_days_i32"].append(next_renewal)

retained = len(values["gleif_entity_creation_days_i32"])
if retained < min_retained:
    raise SystemExit(f"only {retained} retained records < GLEIF_MIN_RETAINED_RECORDS={min_retained}; rerun download.sh")

required_lengths = {
    len(values[series_id])
    for series_id, (_kind, _bits, _element_size, _code, requiredness) in series_meta.items()
    if requiredness == "required"
}
if required_lengths != {retained}:
    raise SystemExit(f"required series length mismatch: {required_lengths}")

rows = []
for series_id, (kind, bits, element_size, code, requiredness) in series_meta.items():
    series_values = values[series_id]
    if requiredness == "optional" and len(series_values) < 1000:
        continue
    if min(series_values) == max(series_values):
        continue
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
            "sample_geometry": "lei_record_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["lei_record" if requiredness == "required" else "lei_record_with_value"],
            "min": min(series_values),
            "max": max(series_values),
        }
    )

counts = [int(row["value_count"]) for row in rows]
byte_counts = [int(row["sample_size_bytes"]) for row in rows]
if len(rows) < 2:
    raise SystemExit(f"only {len(rows)} primary samples emitted")
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample values below floor: {statistics.median(counts)}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_pages": len(page_files),
            "source_records": source_records,
            "retained_records": retained,
            "skipped_records": skipped,
            "duplicate_records": duplicates,
            "primary_values": sum(counts),
            "primary_sample_bytes": sum(byte_counts),
            "median_primary_values": statistics.median(counts),
            "series": {
                row["series_id"]: {
                    "sample_count": 1,
                    "total_values": int(row["value_count"]),
                    "total_size_bytes": int(row["sample_size_bytes"]),
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
    f"values={sum(counts)} bytes={sum(byte_counts)} skipped={skipped} duplicates={duplicates}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
