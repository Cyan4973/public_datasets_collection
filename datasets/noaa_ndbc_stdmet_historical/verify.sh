#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_ndbc_stdmet_historical"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_ndbc_stdmet_historical"
INDEX_ROOT="${DATA_DIR}/index/noaa_ndbc_stdmet_historical"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_ndbc_stdmet_historical"
LOG_ROOT="${DATA_DIR}/logs/noaa_ndbc_stdmet_historical"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() {
  cp "${LOG_FILE}" "${LATEST_LOG}"
}
trap sync_latest_log EXIT

say() {
  printf '%s\n' "$*" | tee -a "${LOG_FILE}"
}

say "download_root=${DOWNLOAD_ROOT}"
say "filtered_root=${FILTERED_ROOT}"
say "index_root=${INDEX_ROOT}"
say "samples_root=${SAMPLES_ROOT}"
say "log_file=${LOG_FILE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" \
FILTERED_ROOT="${FILTERED_ROOT}" \
INDEX_ROOT="${INDEX_ROOT}" \
SAMPLES_ROOT="${SAMPLES_ROOT}" \
python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import csv
import gzip
import json
import os
from collections import defaultdict
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

stats_path = filtered_root / "station_element_year_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"

station_ids = [
    # Atlantic Ocean
    "41002", "41004", "41008", "41009", "41010",
    "41025", "41047", "41048",
    "44005", "44008", "44011", "44013", "44017",
    "44025", "44027",
    # Gulf of Mexico
    "42001", "42002", "42019", "42020", "42036",
    # Pacific Ocean
    "46002", "46005", "46006", "46011", "46012",
    "46013", "46014", "46022", "46025", "46026",
    "46028", "46042", "46047", "46059", "46069",
    # Hawaii / Pacific Islands
    "51001", "51002", "51003", "51004",
]
element_ids = ["WDIR", "WSPD", "GST", "WVHT", "PRES", "ATMP", "WTMP"]
series_defs = [
    {"series_id": "ndbc_value_f64", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
]

if failures_path.is_file() and failures_path.stat().st_size > 0:
    print(f"warning: download failures recorded in {failures_path} (some station-years may be missing)")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_key = {(row["station_id"], row["element_id"], row["year"]): row for row in stats_rows}

expected_records: dict[tuple[str, str], dict[str, object]] = {}
group_counts: dict[tuple[str, str], int] = defaultdict(int)


def normalize_header_tokens(tokens: list[str]) -> list[str]:
    return [token.lstrip("#").upper() for token in tokens]


for station_id in station_ids:
    per_group_year = {
        (element_id, year): {
            "row_count": 0,
            "kept_count": 0,
            "skipped_missing_count": 0,
            "skipped_parse_count": 0,
            "start_date": "",
            "end_date": "",
        }
        for element_id in element_ids
        for year in range(2019, 2024)
    }

    for year in range(2019, 2024):
        path = download_root / f"{station_id}h{year}.txt.gz"
        if not path.is_file():
            print(f"warning: skipping missing station-year file: {path}")
            continue
        if path.stat().st_size <= 0:
            raise SystemExit(f"empty raw file: {path}")

        header_tokens: list[str] | None = None
        with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                tokens = line.split()
                first = tokens[0].lstrip("#").upper()
                if first in {"YY", "YYYY"}:
                    header_tokens = normalize_header_tokens(tokens)
                    continue
                if header_tokens is None:
                    continue
                if first in {"YR", "YYYY", "YY"}:
                    continue

                header_map = {}
                for idx, name in enumerate(header_tokens):
                    if name not in header_map:
                        header_map[name] = idx
                year_col = "YYYY" if "YYYY" in header_map else "YY" if "YY" in header_map else None
                if year_col is None:
                    raise SystemExit(f"missing year column in {path}")
                required_date_cols = [year_col, "MM", "DD", "HH"]
                if not all(col in header_map for col in required_date_cols):
                    raise SystemExit(f"missing date columns in {path}")

                try:
                    obs_year = int(tokens[header_map[year_col]])
                    if year_col == "YY" and obs_year < 100:
                        obs_year += 1900 if obs_year >= 70 else 2000
                    obs_month = int(tokens[header_map["MM"]])
                    obs_day = int(tokens[header_map["DD"]])
                    obs_hour = int(tokens[header_map["HH"]])
                except (ValueError, IndexError):
                    for element_id in element_ids:
                        per_group_year[(element_id, year)]["skipped_parse_count"] += 1
                    continue

                date_value = f"{obs_year:04d}{obs_month:02d}{obs_day:02d}{obs_hour:02d}"
                for element_id in element_ids:
                    if element_id not in header_map:
                        continue
                    bucket = per_group_year[(element_id, year)]
                    bucket["row_count"] += 1
                    try:
                        raw_value = tokens[header_map[element_id]]
                    except IndexError:
                        bucket["skipped_parse_count"] += 1
                        continue
                    if raw_value.upper() == "MM":
                        bucket["skipped_missing_count"] += 1
                        continue
                    try:
                        float(raw_value)
                    except ValueError:
                        bucket["skipped_parse_count"] += 1
                        continue
                    if obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31 or obs_hour < 0 or obs_hour > 23:
                        bucket["skipped_parse_count"] += 1
                        continue

                    bucket["kept_count"] += 1
                    if bucket["start_date"] == "":
                        bucket["start_date"] = date_value
                    bucket["end_date"] = date_value
                    group_counts[(station_id, element_id)] += 1

    for element_id in element_ids:
        for year in range(2019, 2024):
            bucket = per_group_year[(element_id, year)]
            stats_row = stats_by_key.get((station_id, element_id, str(year)))
            if stats_row is None:
                raise SystemExit(f"missing stats row for {station_id} {element_id} {year}")
            for field in ["row_count", "kept_count", "skipped_missing_count", "skipped_parse_count"]:
                if int(stats_row[field]) != int(bucket[field]):
                    raise SystemExit(
                        f"stats mismatch for {station_id} {element_id} {year} field {field}: "
                        f"stats={stats_row[field]} raw={bucket[field]}"
                    )
            if stats_row["start_date"] != bucket["start_date"]:
                raise SystemExit(
                    f"start date mismatch for {station_id} {element_id} {year}: "
                    f"stats={stats_row['start_date']!r} raw={bucket['start_date']!r}"
                )
            if stats_row["end_date"] != bucket["end_date"]:
                raise SystemExit(
                    f"end date mismatch for {station_id} {element_id} {year}: "
                    f"stats={stats_row['end_date']!r} raw={bucket['end_date']!r}"
                )

for (station_id, element_id), value_count in sorted(group_counts.items()):
    sample_slug = f"{station_id}_{element_id}"
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{sample_slug}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = value_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(
                f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}"
            )
        expected_records[(series["series_id"], sample_slug)] = {
            "dataset_id": "noaa_ndbc_stdmet_historical",
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": value_count,
            "station_id": station_id,
            "element_id": element_id,
        }

index_records: dict[tuple[str, str], dict[str, object]] = {}
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
    raise SystemExit(
        f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_records)}"
    )

for key, expected in expected_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise SystemExit(
                f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}"
            )

print("verified raw inventory, generated sample sizes, stats, and sample index")
PY

say "verified raw inventory, generated sample sizes, stats, and sample index"
