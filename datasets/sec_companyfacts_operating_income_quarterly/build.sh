#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="sec_companyfacts_operating_income_quarterly"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/build.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/build.latest.log"

mkdir -p "${FILTERED_ROOT}" "${INDEX_ROOT}" "${SAMPLES_ROOT}" "${LOG_ROOT}"
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
import array, csv, json, os, shutil
from decimal import Decimal
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

fact_name = "OperatingIncomeLoss"
companies = [
    ("apple", "0000320193"),
    ("microsoft", "0000789019"),
    ("alphabet", "0001652044"),
    ("amazon", "0001018724"),
    ("meta", "0001326801"),
]
series_defs = [
    {"series_id": "operating_income_i64", "array_type": "q", "numeric_kind": "int", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
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

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "company_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["company_id", "cik", "row_count", "kept_count", "skipped_null_count", "skipped_parse_count", "start_period", "end_period"])
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
        values = [value for year, quarter, value in ordered]
        years = [year for year, quarter, value in ordered]
        start_period = f"{ordered[0][0]}Q{ordered[0][1]}" if ordered else ""
        end_period = f"{ordered[-1][0]}Q{ordered[-1][1]}" if ordered else ""
        writer.writerow([company_id, cik, row_count, len(ordered), skipped_null, skipped_parse, start_period, end_period])
        payloads = {
            "operating_income_i64": values,
        }
        for series in series_defs:
            payload = array.array(series["array_type"], payloads[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            out_path = samples_root / series["series_id"] / f"{company_id}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload.tobytes())
            index_records.append({
                "dataset_id": dataset_id,
                "series_id": series["series_id"],
                "sample_path": out_path.relative_to(data_root).as_posix(),
                "numeric_kind": series["numeric_kind"],
                "bit_width": series["bit_width"],
                "endianness": series["endianness"],
                "element_size_bytes": series["element_size_bytes"],
                "sample_size_bytes": out_path.stat().st_size,
                "value_count": len(payloads[series["series_id"]]),
                "company_id": company_id,
                "cik": cik,
                "fact_name": fact_name,
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
if not index_records:
    raise SystemExit("no company samples were produced")
PY

say "built samples under ${SAMPLES_ROOT}"
