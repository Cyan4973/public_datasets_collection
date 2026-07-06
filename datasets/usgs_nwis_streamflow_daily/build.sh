#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/usgs_nwis_streamflow_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/usgs_nwis_streamflow_daily"
INDEX_ROOT="${DATA_DIR}/index/usgs_nwis_streamflow_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/usgs_nwis_streamflow_daily"
LOG_ROOT="${DATA_DIR}/logs/usgs_nwis_streamflow_daily"
MIN_VALUES_PER_SAMPLE=${USGS_NWIS_STREAMFLOW_MIN_VALUES_PER_SAMPLE:-7000}
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
say "min_values_per_sample=${MIN_VALUES_PER_SAMPLE}"
say "log_file=${LOG_FILE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" \
FILTERED_ROOT="${FILTERED_ROOT}" \
INDEX_ROOT="${INDEX_ROOT}" \
SAMPLES_ROOT="${SAMPLES_ROOT}" \
MIN_VALUES_PER_SAMPLE="${MIN_VALUES_PER_SAMPLE}" \
python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import array
import csv
import json
import math
import os
import shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])
data_root = samples_root.parent.parent

dataset_id = "usgs_nwis_streamflow_daily"
parameter_cd = "00060"
series_defs = [
    {
        "series_id": "usgs_discharge_cfs_f64",
        "array_type": "d",
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
    },
]

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

plan_path = download_root / "download_plan.tsv"
if not plan_path.is_file():
    raise SystemExit(f"missing download plan: {plan_path}")

planned_files: list[tuple[str, Path]] = []
with plan_path.open("r", encoding="utf-8", newline="") as plan_file:
    reader = csv.DictReader(plan_file, delimiter="\t")
    if reader.fieldnames is None:
        raise SystemExit(f"empty download plan: {plan_path}")
    required = {"site_no", "rel_out"}
    missing = required.difference(reader.fieldnames)
    if missing:
        raise SystemExit(f"download plan missing columns {sorted(missing)}: {plan_path}")
    for row in reader:
        site_id = row["site_no"].strip()
        rel_out = row["rel_out"].strip()
        if not site_id or not rel_out:
            continue
        json_path = download_root / rel_out
        if json_path.is_file():
            planned_files.append((site_id, json_path))
        else:
            print(f"planned file missing, skipping: {json_path}", flush=True)

def selected_time_series(payload: dict[str, object]) -> dict[str, object] | None:
    time_series = payload.get("value", {}).get("timeSeries", [])  # type: ignore[union-attr]
    if not isinstance(time_series, list):
        return None
    for candidate in time_series:
        if not isinstance(candidate, dict):
            continue
        name = str(candidate.get("name", ""))
        if f":{parameter_cd}:" in name and name.endswith(":00003"):
            return candidate
    return None

def parse_value_row(row: object) -> tuple[float, str] | None:
    if not isinstance(row, dict):
        return None
    raw_value = str(row.get("value", "")).strip()
    raw_date = str(row.get("dateTime", "")).strip()
    if raw_value == "" or raw_date == "":
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    date_part = raw_date[:10]
    pieces = date_part.split("-")
    if len(pieces) != 3:
        return None
    try:
        obs_year = int(pieces[0])
        obs_month = int(pieces[1])
        obs_day = int(pieces[2])
    except ValueError:
        return None
    if obs_year < 0 or obs_year > 65535 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
        return None
    return value, date_part

stats_path = filtered_root / "site_stats.tsv"
index_path = index_root / "samples.jsonl"
summary_path = filtered_root / "quality_summary.json"
index_records: list[dict[str, object]] = []
rejected_samples: list[dict[str, object]] = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["site_id", "row_count", "value_count", "skipped_count", "start_date", "end_date", "series_name"])

    for site_id, json_path in planned_files:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        selected_series = selected_time_series(payload)
        if selected_series is None:
            rejected_samples.append({"site_id": site_id, "reason": "no_time_series"})
            writer.writerow([site_id, 0, 0, 0, "", "", ""])
            continue

        rows: list[object] = []
        best_wrapper_count = -1
        for wrapper in selected_series.get("values", []):
            if not isinstance(wrapper, dict):
                continue
            candidate = wrapper.get("value", [])
            if not isinstance(candidate, list):
                continue
            candidate_count = sum(1 for row in candidate if parse_value_row(row) is not None)
            if candidate_count > best_wrapper_count:
                best_wrapper_count = candidate_count
                rows = candidate

        values: list[float] = []
        row_count = len(rows)
        skipped_count = 0
        first_date = ""
        last_date = ""
        for row in rows:
            parsed = parse_value_row(row)
            if parsed is None:
                skipped_count += 1
                continue
            value, date_part = parsed
            values.append(value)
            if first_date == "":
                first_date = date_part
            last_date = date_part

        series_name = str(selected_series.get("name", ""))
        writer.writerow([site_id, row_count, len(values), skipped_count, first_date, last_date, series_name])

        if len(values) < min_values_per_sample:
            rejected_samples.append(
                {
                    "site_id": site_id,
                    "reason": "below_min_values_per_sample",
                    "value_count": len(values),
                    "min_values_per_sample": min_values_per_sample,
                }
            )
            continue

        site_slug = f"site_{site_id}"
        values_by_series = {"usgs_discharge_cfs_f64": values}
        for series in series_defs:
            arr = array.array(series["array_type"], values_by_series[series["series_id"]])
            if arr.itemsize > 1 and os.sys.byteorder != "little":
                arr.byteswap()
            out_path = samples_root / series["series_id"] / f"{site_slug}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(arr.tobytes())
            sample_size_bytes = out_path.stat().st_size
            index_records.append(
                {
                    "dataset_id": dataset_id,
                    "series_id": series["series_id"],
                    "sample_path": out_path.relative_to(data_root).as_posix(),
                    "numeric_kind": series["numeric_kind"],
                    "bit_width": series["bit_width"],
                    "endianness": series["endianness"],
                    "element_size_bytes": series["element_size_bytes"],
                    "sample_size_bytes": sample_size_bytes,
                    "value_count": len(values_by_series[series["series_id"]]),
                }
            )

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")

total_values = sum(int(record["value_count"]) for record in index_records)
summary = {
    "dataset_id": dataset_id,
    "series_id": "usgs_discharge_cfs_f64",
    "planned_files": len(planned_files),
    "sample_count": len(index_records),
    "total_values": total_values,
    "total_size_bytes": total_values * 8,
    "min_values_per_sample": min_values_per_sample,
    "rejected_samples": rejected_samples,
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {len(index_records)} samples with {total_values} values", flush=True)
print(f"quality summary: {summary_path}", flush=True)
PY

say "built samples under ${SAMPLES_ROOT}"
