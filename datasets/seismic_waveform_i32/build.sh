#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="seismic_waveform_i32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

EXPECTED = {
    "anchorage_cola": 24000,
    "chile_hrv": 12000,
    "haiti_hrv": 12000,
    "kumamoto_majo": 12000,
    "mexico_anmo": 12000,
    "nepal_tuc": 12000,
    "nz_snzo": 12000,
    "okhotsk_cola": 12000,
    "quiet_anmo": 24000,
    "sumatra_cola": 12000,
    "tohoku_anmo": 12000,
    "turkey_kev": 12000,
}

HEADER_RE = re.compile(
    r"^TIMESERIES\s+(?P<series>[^,]+),\s+(?P<samples>\d+)\s+samples,\s+"
    r"(?P<sps>[0-9.]+)\s+sps,\s+(?P<start>[^,]+),\s+TSPAIR,\s+INTEGER,\s+COUNTS$"
)

def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_ascii(path: Path) -> tuple[dict[str, object], list[int]]:
    header = None
    values = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith("TIMESERIES"):
                match = HEADER_RE.match(line)
                if match is None:
                    raise RuntimeError(f"unexpected TIMESERIES header in {path}: {line}")
                header = {
                    "series": match.group("series"),
                    "samples": int(match.group("samples")),
                    "sample_rate_hz": float(match.group("sps")),
                    "start_time_utc": match.group("start"),
                    "format": "TSPAIR",
                    "sample_type": "INTEGER",
                    "unit": "COUNTS",
                }
                continue
            parts = line.split()
            try:
                value = int(parts[-1])
            except (IndexError, ValueError) as exc:
                raise RuntimeError(f"{path}:{line_number}: bad integer sample") from exc
            if not -(1 << 31) <= value < (1 << 31):
                raise RuntimeError(f"{path}:{line_number}: value out of int32 range: {value}")
            values.append(value)
    if header is None:
        raise RuntimeError(f"missing TIMESERIES header in {path}")
    if header["samples"] != len(values):
        raise RuntimeError(f"{path} header says {header['samples']} samples; parsed {len(values)}")
    return header, values

filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
sample_dir = samples_dir / "seismic_waveform_i32"
if sample_dir.exists():
    shutil.rmtree(sample_dir)
sample_dir.mkdir(parents=True, exist_ok=True)

sample_rows = []
stats_files = []
total_values = 0
total_bytes = 0
global_min = None
global_max = None
sample_rates = set()

for stem, expected_values in EXPECTED.items():
    source = download_dir / f"{stem}.ascii"
    if not source.is_file():
        raise RuntimeError(f"missing raw file: {source}")
    header, values = parse_ascii(source)
    if len(values) != expected_values:
        raise RuntimeError(f"{source} has {len(values)} values; expected {expected_values}")

    output = sample_dir / f"{stem}.bin"
    with output.open("wb") as f:
        f.write(struct.pack("<" + "i" * len(values), *values))

    output_sha = sha256_file(output)
    file_min = min(values)
    file_max = max(values)
    total_values += len(values)
    total_bytes += output.stat().st_size
    global_min = file_min if global_min is None else min(global_min, file_min)
    global_max = file_max if global_max is None else max(global_max, file_max)
    sample_rates.add(float(header["sample_rate_hz"]))

    sample_rows.append({
        "dataset_id": "seismic_waveform_i32",
        "series_id": "seismic_waveform_i32",
        "sample_path": rel_data(output),
        "numeric_kind": "int",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": output.stat().st_size,
        "value_count": len(values),
    })
    stats_files.append({
        "file": rel_data(output),
        "source_file": rel_data(source),
        "values": len(values),
        "bytes": output.stat().st_size,
        "sha256": output_sha,
        "min": file_min,
        "max": file_max,
        "sample_rate_hz": header["sample_rate_hz"],
        "start_time_utc": header["start_time_utc"],
        "series": header["series"],
    })

stats = {
    "dataset_id": "seismic_waveform_i32",
    "family": "seismic_waveform_i32",
    "total_files": len(stats_files),
    "total_values": total_values,
    "total_output_bytes": total_bytes,
    "encoding": "little-endian signed int32",
    "source_format": "IRIS ASCII TSPAIR integer COUNTS",
    "sample_rates_hz": sorted(sample_rates),
    "min_value": global_min,
    "max_value": global_max,
    "files": stats_files,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
