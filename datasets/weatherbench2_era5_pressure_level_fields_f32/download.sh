#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/weatherbench2_era5_pressure_level_fields_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="weatherbench2_era5_pressure_level_fields_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
CHUNK_DIR="$DOWNLOAD_DIR/chunks"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR" "$CHUNK_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets-weatherbench2-era5/1.0"
JOBS="${ERA5_DOWNLOAD_JOBS:-8}"
EXPECTED_PLAN_SHA256="efa91f21a5db11f18712977d3dc550ff4aeca08a70b24ee175443aaa9ca75f8f"
EXPECTED_ZMETADATA_SHA256="0edf7981e8d07885312c611e5f9d53f84545e2f586506c3e7fe31e64395ee67b"

if (( JOBS < 1 || JOBS > 32 )); then
  echo "FATAL: ERA5_DOWNLOAD_JOBS must be between 1 and 32" >&2
  exit 1
fi

LICENSE_PATH="$DOWNLOAD_DIR/LICENSE"
LICENSE_URL="https://storage.googleapis.com/weatherbench2/datasets/era5/LICENSE?generation=1692728948234337"
if [[ ! -f "$LICENSE_PATH" ]] || \
   [[ "$(stat -c %s "$LICENSE_PATH" 2>/dev/null || echo 0)" != "8435" ]] || \
   [[ "$(sha256sum "$LICENSE_PATH" 2>/dev/null | awk '{print $1}')" != "ffe05f9653f14ffd23322bf1ebecfd6dd519ba59726280b34593fcf69ccab60e" ]] || \
   [[ "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  rm -f "$LICENSE_PATH.part"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 180 \
    --max-filesize 8436 --user-agent "$UA" \
    --output "$LICENSE_PATH.part" "$LICENSE_URL"
  if [[ "$(stat -c %s "$LICENSE_PATH.part")" != "8435" ]] || \
     [[ "$(sha256sum "$LICENSE_PATH.part" | awk '{print $1}')" != "ffe05f9653f14ffd23322bf1ebecfd6dd519ba59726280b34593fcf69ccab60e" ]]; then
    echo "FATAL: ERA5 license identity mismatch" >&2
    exit 1
  fi
  mv "$LICENSE_PATH.part" "$LICENSE_PATH"
fi

PLAN_OUT_DIR="$DOWNLOAD_DIR" PLAN_LOG_DIR="$LOG_DIR" \
  bash "$RECIPE_DIR/plan.sh"

if [[ "$(sha256sum "$DOWNLOAD_DIR/zmetadata.json" | awk '{print $1}')" != "$EXPECTED_ZMETADATA_SHA256" ]]; then
  echo "FATAL: consolidated Zarr metadata identity changed" >&2
  exit 1
fi
if [[ "$(sha256sum "$DOWNLOAD_DIR/download_plan.tsv" | awk '{print $1}')" != "$EXPECTED_PLAN_SHA256" ]]; then
  echo "FATAL: generation-pinned chunk plan changed" >&2
  exit 1
fi

export CHUNK_DIR DOWNLOAD_DIR JOBS UA
python3 - <<'PY'
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
from pathlib import Path
import subprocess


download_dir = Path(os.environ["DOWNLOAD_DIR"])
chunk_dir = Path(os.environ["CHUNK_DIR"])
jobs = int(os.environ["JOBS"])
ua = os.environ["UA"]
plan = download_dir / "download_plan.tsv"
rows = list(csv.DictReader(plan.open("r", encoding="utf-8", newline=""), delimiter="\t"))
if len(rows) != 48:
    raise SystemExit(f"expected 48 source chunks, found {len(rows)}")


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(row: dict[str, str]) -> tuple[str, str, int, str]:
    variable = row["variable"]
    chunk_index = row["time_chunk_index"]
    expected_size = int(row["size_bytes"])
    expected_md5 = row["md5_hex"]
    output = chunk_dir / variable / f"{chunk_index}.0.0.0.blosc"
    output.parent.mkdir(parents=True, exist_ok=True)
    if (
        output.is_file()
        and output.stat().st_size == expected_size
        and md5(output) == expected_md5
        and os.environ.get("FORCE_DOWNLOAD", "0") != "1"
    ):
        return variable, chunk_index, expected_size, "cache_hit"
    part = output.with_suffix(output.suffix + ".part")
    part.unlink(missing_ok=True)
    url = f"{row['url']}?generation={row['generation']}"
    completed = subprocess.run(
        [
            "curl", "--globoff", "--fail", "--silent", "--show-error", "--location",
            "--retry", "5", "--retry-delay", "3", "--retry-all-errors",
            "--connect-timeout", "30", "--speed-limit", "1024", "--speed-time", "120",
            "--max-time", "1800", "--max-filesize", str(expected_size + 1),
            "--user-agent", ua, "--output", str(part), url,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            f"download failed variable={variable} chunk={chunk_index}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    if part.stat().st_size != expected_size or md5(part) != expected_md5:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"identity mismatch variable={variable} chunk={chunk_index}")
    part.replace(output)
    return variable, chunk_index, expected_size, "fetched"


total = 0
with ThreadPoolExecutor(max_workers=jobs) as pool:
    futures = [pool.submit(fetch, row) for row in rows]
    for completed_count, future in enumerate(as_completed(futures), 1):
        variable, chunk_index, size, status = future.result()
        total += size
        print(
            f"chunk {status} variable={variable} index={chunk_index} "
            f"bytes={size} progress={completed_count}/{len(rows)}"
        )
print(f"downloaded chunks={len(rows)} compressed_bytes={total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
