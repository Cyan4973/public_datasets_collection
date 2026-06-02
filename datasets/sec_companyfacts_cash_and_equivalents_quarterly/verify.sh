#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="sec_companyfacts_cash_and_equivalents_quarterly"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT

say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

say "download_root=${DOWNLOAD_ROOT}"
say "filtered_root=${FILTERED_ROOT}"
say "index_root=${INDEX_ROOT}"
say "samples_root=${SAMPLES_ROOT}"
say "log_file=${LOG_FILE}"

DATASET_ID="${DATASET_ID}" DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import csv, json, os
from decimal import Decimal
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

fact_name = "CashAndCashEquivalentsAtCarryingValue"
companies = [
    ("apple", "0000320193"),
    ("microsoft", "0000789019"),
    ("alphabet", "0001652044"),
    ("amazon", "0001018724"),
    ("meta", "0001326801"),
]
series_defs = [
    {"series_id": "cash_and_equivalents_i64", "numeric_kind": "int", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_quarter_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]

def parse_int_value(raw: object) -> int:
    dec = Decimal(str(raw))
    if dec != dec.to_integral_value():
        raise ValueError(raw)
    return int(dec)

def choose_record(existing: dict | None, candidate: dict) -> dict:
    if existing is None:
        return candidate
    existing_key = (str(existing.get("end", "")), str(existing.get("filed", "")))
    candidate_key = (str(candidate.get("end", "")), str(candidate.get("filed", "")))
    if candidate_key >= existing_key:
        return candidate
    return existing

stats_path = filtered_root / "company_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")
with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_company = {row["company_id"]: row for row in stats_rows}
expected_records = {}

for company_id, cik in companies:
    raw_path = download_root / f"{company_id}.json"
    if not raw_path.is_file():
        raise SystemExit(f"missing raw JSON: {raw_path}")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    rows = payload["facts"]["us-gaap"][fact_name]["units"]["USD"]
    row_count = len(rows)
    skipped_null = 0
    skipped_parse = 0
    selected: dict[tuple[int, int], dict] = {}
    for row in rows:
        raw_value = row.get("val")
        raw_year = row.get("fy")
        raw_quarter = str(row.get("fp", "")).strip().upper()
        if raw_value in ("", None) or raw_year in ("", None) or raw_quarter == "":
            skipped_null += 1
            continue
        if raw_quarter not in {"Q1", "Q2", "Q3", "Q4"}:
            skipped_parse += 1
            continue
        try:
            year = int(raw_year)
            value = parse_int_value(raw_value)
        except (ArithmeticError, ValueError):
            skipped_parse += 1
            continue
        if year < 1900 or year > 2100:
            skipped_parse += 1
            continue
        quarter = int(raw_quarter[1])
        key = (year, quarter)
        selected[key] = choose_record(selected.get(key), {"val": value, "end": row.get("end", ""), "filed": row.get("filed", "")})
    ordered = sorted((year, quarter, data["val"]) for (year, quarter), data in selected.items())
    kept_count = len(ordered)
    start_period = f"{ordered[0][0]}Q{ordered[0][1]}" if ordered else ""
    end_period = f"{ordered[-1][0]}Q{ordered[-1][1]}" if ordered else ""
    stats_row = stats_by_company.get(company_id)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {company_id}")
    for field, expected in [("row_count", row_count), ("kept_count", kept_count), ("skipped_null_count", skipped_null), ("skipped_parse_count", skipped_parse)]:
        if int(stats_row[field]) != expected:
            raise SystemExit(f"stats mismatch for {company_id} field {field}: stats={stats_row[field]} raw={expected}")
    if stats_row["start_period"] != start_period or stats_row["end_period"] != end_period:
        raise SystemExit(f"period-range mismatch for {company_id}")
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{company_id}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = kept_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], company_id)] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": kept_count,
            "company_id": company_id,
            "cik": cik,
            "fact_name": fact_name,
        }

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        sample_path = record.get("sample_path")
        sample_key = Path(sample_path).stem if isinstance(sample_path, str) else ""
        key = (record.get("series_id"), sample_key)
        if key in index_records:
            raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
        index_records[key] = record
if set(index_records) != set(expected_records):
    raise SystemExit(f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_records)}")
for key, expected in expected_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise SystemExit(f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}")
print("verified raw inventory, generated sample sizes, stats, and sample index")
PY

say "verified raw inventory, generated sample sizes, stats, and sample index"
