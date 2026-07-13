#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="gdelt_events_numsources_daily"
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
import array, csv, json, os, shutil, zipfile
from datetime import datetime
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

days = ["20240101", "20240102", "20240103", "20240104", "20240105", "20240106", "20240107"]
value_index = 32
series_defs = [
    {"series_id": "numsources_u32", "array_type": "I", "numeric_kind": "uint", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "day_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["day", "row_count", "kept_count", "skipped_blank_count", "skipped_parse_count"])
    for day in days:
        raw_path = download_root / f"{day}.zip"
        if not raw_path.is_file():
            raise SystemExit(f"missing raw zip: {raw_path}")
        row_count = 0
        kept_count = 0
        skipped_blank = 0
        skipped_parse = 0
        values = []
        years = []
        months = []
        day_values = []
        with zipfile.ZipFile(raw_path) as zf:
            member_name = zf.namelist()[0]
            with zf.open(member_name, "r") as member:
                for raw_line in member:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        continue
                    parts = line.split("\t")
                    row_count += 1
                    if len(parts) <= value_index:
                        skipped_parse += 1
                        continue
                    raw_date = parts[1].strip()
                    raw_value = parts[value_index].strip()
                    if raw_date == "" or raw_value == "":
                        skipped_blank += 1
                        continue
                    try:
                        dt = datetime.strptime(raw_date, "%Y%m%d")
                        value = int(raw_value)
                    except ValueError:
                        skipped_parse += 1
                        continue
                    if value < 0:
                        skipped_parse += 1
                        continue
                    kept_count += 1
                    values.append(value)
                    years.append(dt.year)
                    months.append(dt.month)
                    day_values.append(dt.day)
        writer.writerow([day, row_count, kept_count, skipped_blank, skipped_parse])
        payloads = {
            "numsources_u32": values,
        }
        for series in series_defs:
            arr = array.array(series["array_type"], payloads[series["series_id"]])
            if arr.itemsize > 1 and os.sys.byteorder != "little":
                arr.byteswap()
            out_path = samples_root / series["series_id"] / f"{day}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(arr.tobytes())
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
                "day": day,
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
