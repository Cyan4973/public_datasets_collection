#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jhu_covid19_confirmed_us_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_VALUES_PER_SAMPLE="${JHU_COVID19_CONFIRMED_US_MIN_VALUES_PER_SAMPLE:-1000}"
MAX_SAMPLES="${JHU_COVID19_CONFIRMED_US_MAX_SAMPLES:-100000}"
MAX_PRIMARY_BYTES="${JHU_COVID19_CONFIRMED_US_MAX_PRIMARY_BYTES:-1000000000}"

echo "download_dir=$DOWNLOAD_DIR"
echo "filter_dir=$FILTER_DIR"
echo "index_dir=$INDEX_DIR"
echo "samples_dir=$SAMPLES_DIR"
echo "min_values_per_sample=$MIN_VALUES_PER_SAMPLE"
echo "max_samples=$MAX_SAMPLES"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_VALUES_PER_SAMPLE MAX_SAMPLES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import struct
from collections import defaultdict
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_values = int(os.environ["MIN_VALUES_PER_SAMPLE"])
max_samples = int(os.environ["MAX_SAMPLES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

dataset_id = "jhu_covid19_confirmed_us_daily"
series_id = "confirmed_cases_u32"
series_dir = samples_dir / series_id
if samples_dir.exists():
    shutil.rmtree(samples_dir)
series_dir.mkdir(parents=True, exist_ok=True)

csv_path = download_dir / "time_series_covid19_confirmed_US.csv"
if not csv_path.is_file():
    raise SystemExit(f"missing raw CSV: {csv_path}")

def parse_fips(raw: str) -> str | None:
    text = str(raw).strip()
    if text == "":
        return None
    try:
        value = int(float(text))
    except ValueError:
        return None
    if value <= 0:
        return None
    return f"{value:05d}"

with csv_path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise SystemExit(f"missing CSV header in {csv_path}")
    required = {"Admin2", "Country_Region", "FIPS", "Province_State"}
    missing = required.difference(reader.fieldnames)
    if missing:
        raise SystemExit(f"missing required columns in {csv_path}: {sorted(missing)}")
    date_columns = [field for field in reader.fieldnames if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", field or "")]
    if not date_columns:
        raise SystemExit(f"no date columns in {csv_path}")
    parsed_dates: list[datetime | None] = []
    for raw_date in date_columns:
        try:
            parsed_dates.append(datetime.strptime(raw_date, "%m/%d/%y"))
        except ValueError:
            parsed_dates.append(None)
    source_rows = list(reader)

groups: dict[str, dict[str, object]] = {}
skipped_rows = defaultdict(int)
for row in source_rows:
    country = str(row.get("Country_Region", "")).strip()
    state = str(row.get("Province_State", "")).strip()
    county = str(row.get("Admin2", "")).strip()
    fips = parse_fips(str(row.get("FIPS", "")).strip())
    if country != "US":
        skipped_rows["non_us"] += 1
        continue
    if fips is None:
        skipped_rows["missing_or_invalid_fips"] += 1
        continue
    if state == "" or county == "":
        skipped_rows["missing_state_or_county"] += 1
        continue
    county_l = county.lower()
    if county_l.startswith("unassigned") or county_l.startswith("out of "):
        skipped_rows["non_county_bucket"] += 1
        continue
    item = groups.setdefault(
        fips,
        {
            "county_name": county,
            "fips": fips,
            "rows": [],
            "state_name": state,
        },
    )
    if item["state_name"] != state or item["county_name"] != county:
        skipped_rows["duplicate_fips_identity_conflict"] += 1
        continue
    item["rows"].append(row)

accepted: list[dict[str, object]] = []
rejected: list[dict[str, object]] = []
for fips, item in sorted(groups.items(), key=lambda pair: (str(pair[1]["state_name"]), str(pair[1]["county_name"]), pair[0])):
    values: list[int] = []
    skipped_blank = 0
    skipped_parse = 0
    skipped_overflow = 0
    start_date = ""
    end_date = ""
    rows = item["rows"]
    assert isinstance(rows, list)
    for idx, raw_date in enumerate(date_columns):
        dt = parsed_dates[idx]
        if dt is None:
            skipped_parse += 1
            continue
        saw_value = False
        total = 0
        valid = True
        for row in rows:
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
        if total > 0xFFFFFFFF:
            skipped_overflow += 1
            continue
        values.append(total)
        iso_date = dt.strftime("%Y-%m-%d")
        if start_date == "":
            start_date = iso_date
        end_date = iso_date
    if len(values) < min_values:
        rejected.append({"county_name": item["county_name"], "fips": fips, "reason": "below_min_values", "state_name": item["state_name"], "value_count": len(values)})
        continue
    if len(set(values)) <= 1:
        rejected.append({"county_name": item["county_name"], "fips": fips, "reason": "constant", "state_name": item["state_name"], "value_count": len(values)})
        continue
    accepted.append(
        {
            "county_name": item["county_name"],
            "end_date": end_date,
            "fips": fips,
            "row_count": len(rows),
            "skipped_blank": skipped_blank,
            "skipped_overflow": skipped_overflow,
            "skipped_parse": skipped_parse,
            "start_date": start_date,
            "state_name": item["state_name"],
            "values": values,
        }
    )

accepted = accepted[:max_samples]
if not accepted:
    raise SystemExit("no county samples met the quality threshold")

stats_rows = []
index_rows: list[dict[str, object]] = []
primary_bytes = 0
for item in accepted:
    values = item["values"]
    assert isinstance(values, list)
    payload = struct.pack("<" + "I" * len(values), *values)
    primary_bytes += len(payload)
    if primary_bytes > max_primary_bytes:
        raise SystemExit(f"primary output exceeds cap: {primary_bytes} > {max_primary_bytes}")
    out = series_dir / f"fips_{item['fips']}_n{len(values):05d}.bin"
    out.write_bytes(payload)
    sample_path = out.relative_to(data_root).as_posix()
    index_rows.append(
        {
            "county_name": item["county_name"],
            "dataset_id": dataset_id,
            "endianness": "little",
            "element_size_bytes": 4,
            "fips": item["fips"],
            "natural_record_count": 1,
            "natural_record_kind": "jhu_county_daily_time_series",
            "natural_record_values": len(values),
            "numeric_kind": "uint",
            "role": "primary",
            "sample_geometry": "jhu_county_daily_time_series",
            "sample_path": sample_path,
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_size_bytes": len(payload),
            "series_id": series_id,
            "state_name": item["state_name"],
            "value_count": len(values),
            "bit_width": 32,
        }
    )
    stats_rows.append(
        [
            item["state_name"],
            item["county_name"],
            item["fips"],
            item["row_count"],
            len(values),
            item["skipped_blank"],
            item["skipped_parse"],
            item["skipped_overflow"],
            item["start_date"],
            item["end_date"],
        ]
    )

with (filter_dir / "county_stats.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["state_name", "county_name", "fips", "source_row_count", "value_count", "skipped_blank_count", "skipped_parse_count", "skipped_overflow_count", "start_date", "end_date"])
    writer.writerows(stats_rows)

summary = {
    "candidate_county_series": len(groups),
    "dataset_id": dataset_id,
    "date_columns": len(date_columns),
    "max_samples": max_samples,
    "min_values_per_sample": min_values,
    "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in index_rows),
    "primary_values": sum(int(row["value_count"]) for row in index_rows),
    "rejected_samples": rejected,
    "sample_count": len(index_rows),
    "series_id": series_id,
    "skipped_source_rows": dict(sorted(skipped_rows.items())),
    "source_rows": len(source_rows),
}
(filter_dir / "quality_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
    for row in index_rows:
        handle.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(index_rows)} primary_values={summary['primary_values']} "
    f"primary_bytes={summary['primary_sample_bytes']} candidates={len(groups)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
