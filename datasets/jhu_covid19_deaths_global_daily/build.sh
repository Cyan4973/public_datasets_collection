#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/jhu_covid19_deaths_global_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/jhu_covid19_deaths_global_daily"
INDEX_ROOT="${DATA_DIR}/index/jhu_covid19_deaths_global_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/jhu_covid19_deaths_global_daily"
LOG_ROOT="${DATA_DIR}/logs/jhu_covid19_deaths_global_daily"
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

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import array, csv, json, os, shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "jhu_covid19_deaths_global_daily"
entities = [
    ("us", "US"),
    ("india", "India"),
    ("brazil", "Brazil"),
    ("france", "France"),
    ("germany", "Germany"),
]
series_defs = [
    {"series_id": "death_counts_u32", "array_type": "I", "numeric_kind": "uint", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]
for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

path = download_root / "time_series_covid19_deaths_global.csv"
if not path.is_file():
    raise SystemExit(f"missing raw CSV: {path}")

stats_path = filtered_root / "country_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise SystemExit(f"missing CSV header in {path}")
    date_columns = reader.fieldnames[4:]
    parsed_dates = []
    for raw_date in date_columns:
        try:
            dt = datetime.strptime(raw_date, "%m/%d/%y")
        except ValueError:
            parsed_dates.append(None)
        else:
            parsed_dates.append(dt)
    rows = list(reader)

country_rows = defaultdict(list)
for row in rows:
    country_rows[str(row.get("Country/Region", "")).strip()].append(row)

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["entity_id", "row_count", "kept_count", "skipped_blank_count", "skipped_parse_count", "start_date", "end_date"])
    for entity_id, country_name in entities:
        matched_rows = country_rows.get(country_name, [])
        values = []
        years = []
        skipped_blank = 0
        skipped_parse = 0
        start_date = ""
        end_date = ""
        for idx, raw_date in enumerate(date_columns):
            dt = parsed_dates[idx]
            if dt is None:
                skipped_parse += 1
                continue
            total = 0
            valid = True
            saw_value = False
            for row in matched_rows:
                raw_value = str(row.get(raw_date, "")).strip()
                if raw_value == "":
                    continue
                saw_value = True
                try:
                    total += int(raw_value)
                except ValueError:
                    valid = False
                    break
            if not saw_value:
                skipped_blank += 1
                continue
            if not valid or total < 0:
                skipped_parse += 1
                continue
            values.append(total)
            years.append(dt.year)
            iso_date = dt.strftime("%Y-%m-%d")
            if start_date == "":
                start_date = iso_date
            end_date = iso_date
        writer.writerow([entity_id, len(date_columns), len(values), skipped_blank, skipped_parse, start_date, end_date])
        payloads = {
            "death_counts_u32": values,
        }
        for series in series_defs:
            payload = array.array(series["array_type"], payloads[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            out_path = samples_root / series["series_id"] / f"{entity_id}.bin"
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
                "entity_id": entity_id,
                "entity_name": country_name,
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
if not index_records:
    raise SystemExit("no country samples were produced")
PY

say "built samples under ${SAMPLES_ROOT}"
