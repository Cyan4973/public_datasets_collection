#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_ghcn_daily_snwd_by_station"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_ghcn_daily_snwd_by_station"
INDEX_ROOT="${DATA_DIR}/index/noaa_ghcn_daily_snwd_by_station"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_ghcn_daily_snwd_by_station"
LOG_ROOT="${DATA_DIR}/logs/noaa_ghcn_daily_snwd_by_station"
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
import array, csv, gzip, json, os, shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "noaa_ghcn_daily_snwd_by_station"
element_id = "SNWD"
station_ids = [
    "USC00011084",
    "USC00024849",
    "USC00034756",
    "USC00043761",
    "USC00047916",
    "USC00053038",
    "USC00079605",
    "USC00091500",
    "USC00101408",
    "USC00110072",
    "USC00115943",
    "USC00122149",
    "USC00129113",
    "USC00137147",
    "USC00144972",
    "USC00158709",
    "USC00173046",
    "USC00190736",
    "USC00204090",
    "USC00213303",
    "USC00221389",
    "USC00229079",
    "USC00235834",
    "USC00243139",
    "USC00248597",
    "USC00253630",
    "USC00258480",
    "USC00284229",
    "USC00295960",
    "USC00301974",
    "USC00306164",
    "USC00314938",
    "USC00322365",
    "USC00331890",
    "USC00340017",
    "USC00345063",
    "USC00351765",
    "USC00356634",
    "USC00368449",
    "USC00384690",
    "USC00393217",
    "USC00406371",
    "USC00412679",
    "USC00417336",
    "USC00425402",
    "USC00431580",
    "USC00449263",
    "USC00455946",
    "USC00465224",
    "USC00476208",
    "USC00486440",
    "USW00013724",
    "USW00014739",
    "USW00014922",
    "USW00023062",
    "USW00024149",
    "USW00025339",
    "USW00094728",
    "USW00094846",
]
YEAR_MIN = 1763
YEAR_MAX = 2026
series_defs = [
    {"series_id": "ghcn_value_i16", "array_type": "h", "numeric_kind": "int", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]

station_names = {}
stations_path = download_root / "ghcnd-stations.txt"
if stations_path.is_file():
    with stations_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            station_id = line[:11].strip()
            if station_id in station_ids:
                station_names[station_id] = line[41:71].strip()

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "station_year_stats.tsv"
skipped_constants_path = filtered_root / "skipped_constant_samples.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

def is_constant(values):
    return bool(values) and all(value == values[0] for value in values)

with stats_path.open("w", encoding="utf-8", newline="") as stats_file, skipped_constants_path.open("w", encoding="utf-8", newline="") as skipped_file:
    writer = csv.writer(stats_file, delimiter="\t")
    skipped_writer = csv.writer(skipped_file, delimiter="\t")
    writer.writerow(["station_id", "year", "row_count", "kept_count", "skipped_quality_count", "skipped_parse_count", "start_date", "end_date"])
    skipped_writer.writerow(["station_id", "series_id", "value_count", "constant_value"])
    for station_id in station_ids:
        value_series = []
        csv_path = download_root / f"{station_id}.csv.gz"
        if not csv_path.is_file():
            raise SystemExit(f"missing raw station file: {csv_path}")
        per_year = {}
        with gzip.open(csv_path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if len(row) < 8:
                    continue
                row_station, raw_date, row_element, raw_value, _mflag, qflag, _sflag, _obs_time = row[:8]
                if row_station != station_id or row_element != element_id:
                    continue
                if len(raw_date) != 8 or not raw_date.isdigit():
                    continue
                year = int(raw_date[:4])
                if year < YEAR_MIN or year > YEAR_MAX:
                    continue
                bucket = per_year.setdefault(year, {"row_count": 0, "kept_count": 0, "skipped_quality_count": 0, "skipped_parse_count": 0, "start_date": "", "end_date": ""})
                bucket["row_count"] += 1
                if qflag.strip() != "":
                    bucket["skipped_quality_count"] += 1
                    continue
                try:
                    value = int(raw_value)
                    obs_year = year
                    obs_month = int(raw_date[4:6])
                    obs_day = int(raw_date[6:8])
                except ValueError:
                    bucket["skipped_parse_count"] += 1
                    continue
                if value < -32768 or value > 32767 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                    bucket["skipped_parse_count"] += 1
                    continue
                value_series.append(value)
                bucket["kept_count"] += 1
                if bucket["start_date"] == "":
                    bucket["start_date"] = raw_date
                bucket["end_date"] = raw_date
        for year in sorted(per_year):
            bucket = per_year[year]
            writer.writerow([station_id, year, bucket["row_count"], bucket["kept_count"], bucket["skipped_quality_count"], bucket["skipped_parse_count"], bucket["start_date"], bucket["end_date"]])
        if not value_series:
            continue
        if is_constant(value_series):
            skipped_writer.writerow([station_id, "ghcn_value_i16", len(value_series), value_series[0]])
            continue
        payloads = {"ghcn_value_i16": value_series}
        for series in series_defs:
            payload = array.array(series["array_type"], payloads[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            out_path = samples_root / series["series_id"] / f"{station_id}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload.tobytes())
            sample_size_bytes = out_path.stat().st_size
            index_records.append({
                "dataset_id": dataset_id,
                "series_id": series["series_id"],
                "sample_path": out_path.relative_to(data_root).as_posix(),
                "numeric_kind": series["numeric_kind"],
                "bit_width": series["bit_width"],
                "endianness": series["endianness"],
                "element_size_bytes": series["element_size_bytes"],
                "sample_size_bytes": sample_size_bytes,
                "value_count": len(payloads[series["series_id"]]),
                "station_id": station_id,
                "element_id": element_id,
                "station_name": station_names.get(station_id, ""),
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
