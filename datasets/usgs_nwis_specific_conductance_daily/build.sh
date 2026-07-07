#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_nwis_specific_conductance_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

PARAMETER_CD="00095"
STAT_CD="00003"
MIN_VALUES_PER_SAMPLE="${USGS_NWIS_SPECIFIC_CONDUCTANCE_MIN_VALUES_PER_SAMPLE:-7000}"
MAX_SAMPLES="${USGS_NWIS_SPECIFIC_CONDUCTANCE_MAX_SAMPLES:-120}"
MAX_PRIMARY_BYTES="${USGS_NWIS_SPECIFIC_CONDUCTANCE_MAX_PRIMARY_BYTES:-1000000000}"

echo "download_dir=$DOWNLOAD_DIR"
echo "page_dir=$PAGE_DIR"
echo "filter_dir=$FILTER_DIR"
echo "index_dir=$INDEX_DIR"
echo "samples_dir=$SAMPLES_DIR"
echo "min_values_per_sample=$MIN_VALUES_PER_SAMPLE"
echo "max_samples=$MAX_SAMPLES"

export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR PARAMETER_CD STAT_CD MIN_VALUES_PER_SAMPLE MAX_SAMPLES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
parameter_cd = os.environ["PARAMETER_CD"]
stat_cd = os.environ["STAT_CD"]
min_values = int(os.environ["MIN_VALUES_PER_SAMPLE"])
max_samples = int(os.environ["MAX_SAMPLES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

dataset_id = "usgs_nwis_specific_conductance_daily"
series_id = "usgs_specific_conductance_f64"
series_dir = samples_dir / series_id
if samples_dir.exists():
    shutil.rmtree(samples_dir)
series_dir.mkdir(parents=True, exist_ok=True)

def parse_row(row: object) -> tuple[float, str] | None:
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
    if not math.isfinite(value) or value < 0:
        return None
    date_part = raw_date[:10]
    pieces = date_part.split("-")
    if len(pieces) != 3:
        return None
    try:
        year, month, day = (int(piece) for piece in pieces)
    except ValueError:
        return None
    if year < 0 or year > 65535 or month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return value, date_part

def best_values(ts: dict[str, object]) -> tuple[list[float], str, str]:
    best: list[float] = []
    best_first = ""
    best_last = ""
    for wrapper in ts.get("values", []):
        if not isinstance(wrapper, dict):
            continue
        rows = wrapper.get("value", [])
        if not isinstance(rows, list):
            continue
        values: list[float] = []
        first_date = ""
        last_date = ""
        for row in rows:
            parsed = parse_row(row)
            if parsed is None:
                continue
            value, date_part = parsed
            values.append(value)
            if first_date == "":
                first_date = date_part
            last_date = date_part
        if len(values) > len(best):
            best = values
            best_first = first_date
            best_last = last_date
    return best, best_first, best_last

site_series: dict[tuple[str, str], dict[str, object]] = {}
for path in sorted(page_dir.glob(f"usgs_{parameter_cd}_*.json")):
    state = path.stem.rsplit("_", 1)[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    for ts in payload.get("value", {}).get("timeSeries", []):
        if not isinstance(ts, dict):
            continue
        name = str(ts.get("name", ""))
        if f":{parameter_cd}:" not in name or not name.endswith(f":{stat_cd}"):
            continue
        source_info = ts.get("sourceInfo", {})
        site_codes = source_info.get("siteCode", []) if isinstance(source_info, dict) else []
        if not site_codes or not isinstance(site_codes[0], dict):
            continue
        site_no = str(site_codes[0].get("value", "")).strip()
        if not site_no:
            continue
        values, first_date, last_date = best_values(ts)
        key = (state, site_no)
        if len(values) > int(site_series.get(key, {}).get("value_count", -1)):
            site_series[key] = {
                "first_date": first_date,
                "last_date": last_date,
                "series_name": name,
                "site_no": site_no,
                "state": state,
                "value_count": len(values),
                "values": values,
            }

accepted = []
rejected = []
for key, item in sorted(site_series.items()):
    values = item["values"]
    assert isinstance(values, list)
    if len(values) < min_values:
        rejected.append({"state": item["state"], "site_no": item["site_no"], "reason": "below_min_values", "value_count": len(values)})
        continue
    if len(set(values)) <= 1:
        rejected.append({"state": item["state"], "site_no": item["site_no"], "reason": "constant", "value_count": len(values)})
        continue
    accepted.append(item)

accepted = accepted[:max_samples]
index_rows: list[dict[str, object]] = []
primary_bytes = 0
stats_rows = []
for item in accepted:
    values = item["values"]
    assert isinstance(values, list)
    out = series_dir / f"{item['state']}_{item['site_no']}_n{len(values):05d}.bin"
    payload = struct.pack("<" + "d" * len(values), *values)
    primary_bytes += len(payload)
    if primary_bytes > max_primary_bytes:
        raise SystemExit(f"primary output exceeds cap: {primary_bytes} > {max_primary_bytes}")
    out.write_bytes(payload)
    index_rows.append(
        {
            "dataset_id": dataset_id,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(payload),
            "value_count": len(values),
            "sample_geometry": "usgs_site_daily_time_series",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "state_code": item["state"],
            "site_no": item["site_no"],
            "natural_record_kind": "usgs_site_daily_time_series",
            "natural_record_count": 1,
            "natural_record_values": len(values),
        }
    )
    stats_rows.append(
        [
            item["state"],
            item["site_no"],
            len(values),
            item["first_date"],
            item["last_date"],
            item["series_name"],
        ]
    )

if not index_rows:
    raise SystemExit("no site samples met the quality threshold")

with (filter_dir / "site_stats.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["state_code", "site_no", "value_count", "start_date", "end_date", "series_name"])
    writer.writerows(stats_rows)

summary = {
    "candidate_site_series": len(site_series),
    "dataset_id": dataset_id,
    "max_samples": max_samples,
    "min_values_per_sample": min_values,
    "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in index_rows),
    "primary_values": sum(int(row["value_count"]) for row in index_rows),
    "rejected_samples": rejected,
    "sample_count": len(index_rows),
    "series_id": series_id,
}
(filter_dir / "quality_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
    for row in index_rows:
        handle.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(index_rows)} primary_values={summary['primary_values']} "
    f"primary_bytes={summary['primary_sample_bytes']} candidates={len(site_series)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
