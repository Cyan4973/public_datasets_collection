#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_lora24_indoor_rssi_i8"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
SUPPORT_DIR="$OUT_DIR/support"
RANGE_DIR="$OUT_DIR/ranges"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
mkdir -p "$SUPPORT_DIR" "$RANGE_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/preflight.$RUN_TS.log" "$LOG_DIR/preflight.latest.log") 2>&1
echo "[$(date -Is)] preflight start candidate=$CANDIDATE_ID"

BASE="https://zenodo.org/api/records/7106074/files"
UA="openzl-public-datasets-lora24-indoor-preflight/1.0"
RANGE_BYTES=1048576

fetch_small() {
  local url="$1" output="$2" expected_size="$3" expected_md5="$4"
  if [[ -f "$output" ]] && \
     [[ "$(stat -c %s "$output")" == "$expected_size" ]] && \
     [[ "$(md5sum "$output" | awk '{print $1}')" == "$expected_md5" ]]; then
    echo "reuse support file=$(basename "$output") bytes=$expected_size"
    return
  fi
  rm -f "$output.part"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 4 --retry-delay 3 --connect-timeout 30 --max-time 180 \
    --max-filesize 1000000 --user-agent "$UA" --output "$output.part" "$url"
  if [[ "$(stat -c %s "$output.part")" != "$expected_size" ]] || \
     [[ "$(md5sum "$output.part" | awk '{print $1}')" != "$expected_md5" ]]; then
    echo "FATAL: support-file identity mismatch: $(basename "$output")" >&2
    exit 1
  fi
  mv "$output.part" "$output"
}

fetch_range() {
  local url="$1" output="$2" start="$3" end="$4"
  local expected=$((end - start + 1))
  rm -f "$output.part"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 4 --retry-delay 3 --connect-timeout 30 --max-time 180 \
    --range "$start-$end" --max-filesize $((expected * 2)) \
    --user-agent "$UA" --output "$output.part" "$url"
  if [[ "$(stat -c %s "$output.part")" != "$expected" ]]; then
    echo "FATAL: range size mismatch file=$(basename "$output") expected=$expected" >&2
    exit 1
  fi
  mv "$output.part" "$output"
}

curl --globoff --fail-with-body --silent --show-error --location \
  --retry 4 --retry-delay 3 --connect-timeout 30 --max-time 180 \
  --max-filesize 1000000 --user-agent "$UA" \
  --output "$SUPPORT_DIR/record.json" "https://zenodo.org/api/records/7106074"

fetch_small "$BASE/Readme/content" \
  "$SUPPORT_DIR/Readme" 228 "f5f7ea0cbac65993d95c9f96ce9dfa56"
fetch_small "$BASE/plot_Exhaustive_experiment.py/content" \
  "$SUPPORT_DIR/plot_Exhaustive_experiment.py" 20045 "7f108ff4259a80b64509a8a458a350bc"
fetch_small "$BASE/plot_long_run_test.py/content" \
  "$SUPPORT_DIR/plot_long_run_test.py" 15157 "7f70427a105bd83a5b96c70bb366e394"

EXHAUSTIVE_SIZE=7316621
LONG_SIZE=18107378
fetch_range "$BASE/Test_Exhaustive_experiment.csv/content" \
  "$RANGE_DIR/exhaustive.head.csv" 0 $((RANGE_BYTES - 1))
fetch_range "$BASE/Test_Exhaustive_experiment.csv/content" \
  "$RANGE_DIR/exhaustive.tail.csv" $((EXHAUSTIVE_SIZE - RANGE_BYTES)) $((EXHAUSTIVE_SIZE - 1))
fetch_range "$BASE/Test_long_run.csv/content" \
  "$RANGE_DIR/long.head.csv" 0 $((RANGE_BYTES - 1))
fetch_range "$BASE/Test_long_run.csv/content" \
  "$RANGE_DIR/long.tail.csv" $((LONG_SIZE - RANGE_BYTES)) $((LONG_SIZE - 1))

export OUT_DIR SUPPORT_DIR RANGE_DIR
python3 - <<'PY'
from __future__ import annotations

from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path


OUT_DIR = Path(os.environ["OUT_DIR"])
SUPPORT_DIR = Path(os.environ["SUPPORT_DIR"])
RANGE_DIR = Path(os.environ["RANGE_DIR"])
EXPECTED_FILES = {
    "Test_Exhaustive_experiment.csv": (7_316_621, "md5:a9fb46df3d57f6edb345d7c1dd0da5ab"),
    "Test_long_run.csv": (18_107_378, "md5:f027322df443cff626b675ce3397587d"),
}
CONFIG_COLUMNS = ("chan", "freq", "modu", "datr", "bw", "codr", "power", "real_cr")


record = json.loads((SUPPORT_DIR / "record.json").read_text(encoding="utf-8"))
if str(record.get("id")) != "7106074":
    raise SystemExit("wrong Zenodo record ID")
metadata = record.get("metadata", {})
if not isinstance(metadata, dict) or metadata.get("doi") != "10.5281/zenodo.7106074":
    raise SystemExit("wrong Zenodo DOI")
license_obj = metadata.get("license", {})
if not isinstance(license_obj, dict) or license_obj.get("id") != "cc-by-4.0":
    raise SystemExit(f"expected CC BY 4.0, got {license_obj}")
files = record.get("files", [])
actual_files = {
    str(item.get("key")): (int(item.get("size", 0)), str(item.get("checksum", "")))
    for item in files if isinstance(item, dict)
}
for key, identity in EXPECTED_FILES.items():
    if actual_files.get(key) != identity:
        raise SystemExit(f"Zenodo file identity changed for {key}: {actual_files.get(key)}")


def complete_head(path: Path) -> tuple[list[str], list[list[str]]]:
    text = path.read_text(encoding="utf-8-sig", errors="strict")
    lines = text.splitlines()
    if len(lines) < 3:
        raise SystemExit(f"too few head rows: {path}")
    reader = csv.reader(lines[:-1])
    header = next(reader)
    return header, [row for row in reader if row]


def complete_tail(path: Path, header: list[str]) -> list[list[str]]:
    raw = path.read_bytes()
    first_newline = raw.find(b"\n")
    if first_newline < 0:
        raise SystemExit(f"tail range contains no complete rows: {path}")
    text = raw[first_newline + 1:].decode("utf-8", errors="strict")
    lines = text.splitlines()
    # The range reaches the file end. Keep the last record whether or not the
    # upstream file has a terminal newline.
    rows = [row for row in csv.reader(lines) if row]
    if any(len(row) != len(header) for row in rows):
        raise SystemExit(f"wrong-width tail row: {path}")
    return rows


def profile(name: str, head_path: Path, tail_path: Path) -> dict[str, object]:
    header, head_rows = complete_head(head_path)
    tail_rows = complete_tail(tail_path, header)
    rows = head_rows + tail_rows
    if not rows or any(len(row) != len(header) for row in rows):
        raise SystemExit(f"invalid sampled rows: {name}")
    if "rssi" not in header or "data" not in header:
        raise SystemExit(f"required columns absent from {name}: {header}")
    rssi_index = header.index("rssi")
    rssis: list[int] = []
    for row in rows:
        try:
            value = Decimal(row[rssi_index].strip())
        except InvalidOperation:
            raise SystemExit(f"nonnumeric sampled RSSI in {name}: {row[rssi_index]!r}")
        if not value.is_finite() or value != value.to_integral_value() or not -128 <= value <= 127:
            raise SystemExit(f"non-int8 sampled RSSI in {name}: {value}")
        rssis.append(int(value))
    columns: dict[str, object] = {}
    for index, column in enumerate(header):
        values = [row[index] for row in rows]
        distinct = sorted(set(values))
        columns[column] = {
            "nonempty": sum(bool(value.strip()) for value in values),
            "distinct_count": len(distinct),
            "distinct_values": distinct if len(distinct) <= 100 else None,
            "examples": distinct[:20],
        }
    config_columns = [column for column in CONFIG_COLUMNS if column in header]
    config_indices = [header.index(column) for column in config_columns]
    configurations = Counter(tuple(row[index] for index in config_indices) for row in rows)
    data_index = header.index("data")
    data_examples = list(dict.fromkeys(row[data_index] for row in rows))[:50]
    return {
        "name": name, "header": header,
        "head_complete_rows": len(head_rows), "tail_complete_rows": len(tail_rows),
        "sampled_rows": len(rows), "rssi_minimum": min(rssis),
        "rssi_maximum": max(rssis), "rssi_distinct": len(set(rssis)),
        "rssi_histogram": {str(key): value for key, value in sorted(Counter(rssis).items())},
        "configuration_columns": config_columns,
        "sampled_configuration_count": len(configurations),
        "sampled_configurations": [
            {"values": dict(zip(config_columns, key)), "rows": count}
            for key, count in configurations.most_common(100)
        ],
        "data_examples": data_examples, "columns": columns,
    }


profiles = [
    profile("exhaustive", RANGE_DIR / "exhaustive.head.csv", RANGE_DIR / "exhaustive.tail.csv"),
    profile("long_run", RANGE_DIR / "long.head.csv", RANGE_DIR / "long.tail.csv"),
]
summary = {
    "candidate_id": "zenodo_lora24_indoor_rssi_i8",
    "record_id": 7106074, "doi": "10.5281/zenodo.7106074",
    "license": "cc-by-4.0", "experiment_csv_bytes": 25_423_999,
    "profiles": profiles,
}
(OUT_DIR / "profile.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps({
    "candidate_id": summary["candidate_id"], "record_id": 7106074,
    "license": summary["license"],
    "experiments": [
        {
            "name": item["name"], "sampled_rows": item["sampled_rows"],
            "rssi_range": [item["rssi_minimum"], item["rssi_maximum"]],
            "rssi_distinct": item["rssi_distinct"],
            "configuration_columns": item["configuration_columns"],
            "sampled_configurations": item["sampled_configuration_count"],
            "data_examples": item["data_examples"][:10],
        }
        for item in profiles
    ],
}, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] preflight done candidate=$CANDIDATE_ID"
