#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="imf_nominal_gdp_usd_annual"
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
import array, csv, json, os, re, shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

indicator_id = "NGDPD"
countries = ["USA", "CHN", "IND", "BRA", "DEU", "JPN", "MEX", "ZAF"]
series_defs = [
    {"series_id": "nominal_gdp_usd_f32", "array_type": "f", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
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

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "country_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["country_code", "row_count", "kept_count", "skipped_null_count", "skipped_parse_count", "start_year", "end_year"])
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
        kept = []
        skipped_null = 0
        skipped_parse = 0
        for year, value in sorted(selected.items()):
            if value is None:
                skipped_null += 1
                continue
            if year < 1900 or year > 2100:
                skipped_parse += 1
                continue
            kept.append((year, float(value)))
        years = [year for year, value in kept]
        values = [value for year, value in kept]
        start_year = str(years[0]) if years else ""
        end_year = str(years[-1]) if years else ""
        writer.writerow([country_code, row_count, len(kept), skipped_null, skipped_parse, start_year, end_year])
        payloads = {"nominal_gdp_usd_f32": values}
        for series in series_defs:
            payload_array = array.array(series["array_type"], payloads[series["series_id"]])
            if payload_array.itemsize > 1 and os.sys.byteorder != "little":
                payload_array.byteswap()
            out_path = samples_root / series["series_id"] / f"{country_code}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload_array.tobytes())
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
                "country_code": country_code,
                "indicator_id": indicator_id,
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
if not index_records:
    raise SystemExit("no country samples were produced")
PY

say "built samples under ${SAMPLES_ROOT}"
