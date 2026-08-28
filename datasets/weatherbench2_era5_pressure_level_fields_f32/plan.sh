#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="weatherbench2_era5_pressure_level_fields_f32"
OUT_DIR="${PLAN_OUT_DIR:-$REPO_ROOT/$DATA_DIR/probes/$CANDIDATE_ID/plan}"
LOG_DIR="${PLAN_LOG_DIR:-$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID}"
BUCKET="weatherbench2"
ZARR_PREFIX="datasets/era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr"
BASE_URL="https://storage.googleapis.com/$BUCKET/$ZARR_PREFIX"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/plan.$RUN_TS.log" "$LOG_DIR/plan.latest.log") 2>&1
echo "[$(date -Is)] acquisition planning start candidate=$CANDIDATE_ID"

curl --globoff --fail --silent --show-error --location \
  --retry 5 --retry-delay 2 --retry-all-errors --max-time 180 \
  --max-filesize 20000000 \
  --user-agent "openzl-public-datasets-weatherbench2-era5-plan/1.0" \
  --output "$OUT_DIR/zmetadata.json.part" "$BASE_URL/.zmetadata"
mv "$OUT_DIR/zmetadata.json.part" "$OUT_DIR/zmetadata.json"

export BUCKET OUT_DIR ZARR_PREFIX
python3 - <<'PY'
from __future__ import annotations

import base64
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlencode


bucket = os.environ["BUCKET"]
out_dir = Path(os.environ["OUT_DIR"])
prefix = os.environ["ZARR_PREFIX"]
zmetadata = json.loads((out_dir / "zmetadata.json").read_text(encoding="utf-8"))
metadata = zmetadata.get("metadata") if isinstance(zmetadata, dict) else None
if not isinstance(metadata, dict):
    raise SystemExit("invalid consolidated Zarr metadata")

variables = (
    "geopotential",
    "specific_humidity",
    "temperature",
    "u_component_of_wind",
    "v_component_of_wind",
    "vertical_velocity",
)
target_dates = (
    "1960-01-15T00:00:00Z",
    "1970-04-15T00:00:00Z",
    "1980-07-15T00:00:00Z",
    "1990-10-15T00:00:00Z",
    "2000-01-15T00:00:00Z",
    "2010-04-15T00:00:00Z",
    "2020-07-15T00:00:00Z",
    "2022-10-15T00:00:00Z",
)
origin = datetime(1959, 1, 1, tzinfo=timezone.utc)

array_layouts = {}
for variable in variables:
    array_meta = metadata.get(f"{variable}/.zarray")
    attrs = metadata.get(f"{variable}/.zattrs")
    if not isinstance(array_meta, dict) or not isinstance(attrs, dict):
        raise SystemExit(f"missing Zarr metadata for {variable}")
    dimensions = attrs.get("_ARRAY_DIMENSIONS")
    if dimensions != ["time", "level", "longitude", "latitude"]:
        raise SystemExit(f"unexpected dimensions for {variable}: {dimensions}")
    if array_meta.get("dtype") != "<f4":
        raise SystemExit(f"unexpected dtype for {variable}: {array_meta.get('dtype')}")
    if array_meta.get("chunks") != [8, 13, 240, 121]:
        raise SystemExit(f"unexpected chunks for {variable}: {array_meta.get('chunks')}")
    expected_compressor = {"id": "blosc", "cname": "lz4", "clevel": 5, "shuffle": 1, "blocksize": 0}
    if array_meta.get("compressor") != expected_compressor:
        raise SystemExit(f"unexpected compressor for {variable}: {array_meta.get('compressor')}")
    array_layouts[variable] = array_meta

requests = []
for date_text in target_dates:
    target = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
    total_hours = int((target - origin).total_seconds() // 3600)
    if total_hours % 6:
        raise SystemExit(f"target is not aligned to six-hour cadence: {date_text}")
    time_index = total_hours // 6
    chunk_index = time_index // 8
    chunk_start_index = chunk_index * 8
    chunk_start = origin + timedelta(hours=chunk_start_index * 6)
    for variable in variables:
        object_name = f"{prefix}/{variable}/{chunk_index}.0.0.0"
        requests.append(
            {
                "variable": variable,
                "target_date": date_text,
                "time_chunk_index": chunk_index,
                "chunk_start_time": chunk_start.isoformat().replace("+00:00", "Z"),
                "chunk_start_time_index": chunk_start_index,
                "object_name": object_name,
            }
        )


def fetch_metadata(request: dict[str, object]) -> dict[str, object]:
    query = urlencode(
        {
            "maxResults": "10",
            "prefix": request["object_name"],
            "fields": "items(name,size,generation,md5Hash)",
        }
    )
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?{query}"
    completed = subprocess.run(
        [
            "curl", "--globoff", "--fail", "--silent", "--show-error", "--location",
            "--retry", "5", "--retry-delay", "2", "--retry-all-errors",
            "--max-time", "180", "--max-filesize", "2000000",
            "--user-agent", "openzl-public-datasets-weatherbench2-era5-plan/1.0", url,
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    value = json.loads(completed.stdout.decode("utf-8"))
    matches = [
        item
        for item in value.get("items", [])
        if isinstance(item, dict) and item.get("name") == request["object_name"]
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one exact object for {request['object_name']}, found {len(matches)}")
    item = matches[0]
    result = dict(request)
    result.update(
        {
            "size_bytes": int(str(item.get("size") or "0")),
            "generation": str(item.get("generation") or ""),
            "md5_base64": str(item.get("md5Hash") or ""),
        }
    )
    if result["size_bytes"] <= 16 or not result["generation"] or not result["md5_base64"]:
        raise RuntimeError(f"incomplete metadata: {result}")
    result["md5_hex"] = base64.b64decode(str(result["md5_base64"]), validate=True).hex()
    result["url"] = f"https://storage.googleapis.com/{bucket}/{result['object_name']}"
    result["decoded_chunk_shape"] = "8,13,240,121"
    result["decoded_chunk_bytes"] = 8 * 13 * 240 * 121 * 4
    result["output_samples"] = 8
    result["output_values_per_sample"] = 13 * 240 * 121
    return result


planned = []
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(fetch_metadata, request): request for request in requests}
    for completed_count, future in enumerate(as_completed(futures), 1):
        row = future.result()
        planned.append(row)
        print(
            f"metadata variable={row['variable']} chunk={row['time_chunk_index']} "
            f"bytes={row['size_bytes']} progress={completed_count}/{len(requests)}"
        )
planned.sort(key=lambda row: (str(row["target_date"]), str(row["variable"])))

columns = (
    "variable", "target_date", "time_chunk_index", "chunk_start_time",
    "chunk_start_time_index", "object_name", "size_bytes", "generation",
    "md5_base64", "md5_hex", "url", "decoded_chunk_shape",
    "decoded_chunk_bytes", "output_samples", "output_values_per_sample",
)
with (out_dir / "download_plan.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(planned)

summary = {
    "candidate_id": "weatherbench2_era5_pressure_level_fields_f32",
    "zarr_prefix": prefix,
    "variables": list(variables),
    "target_dates": list(target_dates),
    "source_chunk_count": len(planned),
    "output_sample_count": sum(int(row["output_samples"]) for row in planned),
    "output_value_count": sum(
        int(row["output_samples"]) * int(row["output_values_per_sample"]) for row in planned
    ),
    "output_bytes": sum(int(row["decoded_chunk_bytes"]) for row in planned),
    "compressed_download_bytes": sum(int(row["size_bytes"]) for row in planned),
    "dataset_payload_bytes_downloaded": 0,
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] acquisition planning done candidate=$CANDIDATE_ID"
