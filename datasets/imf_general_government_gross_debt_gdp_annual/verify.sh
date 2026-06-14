#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="imf_general_government_gross_debt_gdp_annual"
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
import csv, json, os, re
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

indicator_id = "GGXWDG_NGDP"
countries = ["USA", "CHN", "IND", "BRA", "DEU", "JPN", "MEX", "ZAF"]
series_defs = [
    {"series_id": "general_government_gross_debt_gdp_f32", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]

def year_map(node):
    if not isinstance(node, dict) or not node:
        return None
    good = {}
    for key, value in node.items():
        if not re.fullmatch(r"\d{4}", str(key)):
            return None
        if value in ("", None):
            continue
        try:
            good[int(str(key))] = float(value)
        except (TypeError, ValueError):
            return None
    return good if good else None

def collect_candidates(node, indicator: str, country: str):
    found = []
    if isinstance(node, dict):
        if indicator in node:
            found.extend(collect_candidates(node[indicator], indicator, country))
        if country in node:
            found.extend(collect_candidates(node[country], indicator, country))
        if "values" in node:
            found.extend(collect_candidates(node["values"], indicator, country))
        ym = year_map(node)
        if ym:
            found.append(ym)
        for value in node.values():
            found.extend(collect_candidates(value, indicator, country))
    elif isinstance(node, list):
        for value in node:
            found.extend(collect_candidates(value, indicator, country))
    return found

stats_path = filtered_root / "country_stats.tsv"
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
stats_by_country = {row["country_code"]: row for row in stats_rows}
expected_records = {}

for country_code in countries:
    raw_path = download_root / f"{country_code}.json"
    if not raw_path.is_file():
        raise SystemExit(f"missing raw JSON: {raw_path}")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    candidates = collect_candidates(payload, indicator_id, country_code)
    if not candidates:
        raise SystemExit(f"no year map found in {raw_path}")
    selected = max(candidates, key=lambda item: len(item))
    row_count = len(selected)
    skipped_null = 0
    skipped_parse = 0
    kept_years = []
    for year, value in sorted(selected.items()):
        if value is None:
            skipped_null += 1
            continue
        if year < 1900 or year > 2100:
            skipped_parse += 1
            continue
        kept_years.append(year)
    kept_count = len(kept_years)
    start_year = str(kept_years[0]) if kept_years else ""
    end_year = str(kept_years[-1]) if kept_years else ""
    stats_row = stats_by_country.get(country_code)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {country_code}")
    for field, expected in [("row_count", row_count), ("kept_count", kept_count), ("skipped_null_count", skipped_null), ("skipped_parse_count", skipped_parse)]:
        if int(stats_row[field]) != expected:
            raise SystemExit(f"stats mismatch for {country_code} field {field}: stats={stats_row[field]} raw={expected}")
    if stats_row["start_year"] != start_year or stats_row["end_year"] != end_year:
        raise SystemExit(f"year-range mismatch for {country_code}")
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{country_code}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = kept_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], country_code)] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": kept_count,
            "country_code": country_code,
            "indicator_id": indicator_id,
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
