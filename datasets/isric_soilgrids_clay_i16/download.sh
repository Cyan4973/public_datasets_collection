#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="isric_soilgrids_clay_i16"
RECIPE_DIR="$REPO_ROOT/staging/$CANDIDATE_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
SOURCES="$RECIPE_DIR/sources.tsv"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

export SOURCES
python3 - <<'PY'
import csv
import hashlib
import os
from pathlib import Path
import re

path = Path(os.environ["SOURCES"])
with path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 256:
    raise SystemExit("pinned source count changed")
if [int(row["selection_ordinal"]) for row in rows] != list(range(1, 257)):
    raise SystemExit("pinned source ordinals changed")
if sum(int(row["decoded_bytes"]) for row in rows) != 103_680_000:
    raise SystemExit("pinned decoded-byte total changed")
if sum(int(row["source_bytes"]) for row in rows) != 104_067_284:
    raise SystemExit("pinned source-byte total changed")
if len({row["filename"] for row in rows}) != len(rows):
    raise SystemExit("duplicate pinned filename")
if len({(row["x_offset"], row["y_offset"]) for row in rows}) != len(rows):
    raise SystemExit("duplicate pinned mosaic offset")
for row in rows:
    match = re.fullmatch(r"(tileSG-\d{3}-\d{3})_[1-4]-[1-4]\.tif", row["filename"])
    if not match:
        raise SystemExit("unsafe SoilGrids source filename")
    expected_url = (
        "https://files.isric.org/soilgrids/latest/data/clay/clay_0-5cm_mean/"
        f"{match.group(1)}/{row['filename']}"
    )
    if row["url"] != expected_url:
        raise SystemExit("pinned source URL does not match official hierarchy")
    if row["source_x_size"] != "450" or row["source_y_size"] != "450":
        raise SystemExit("pinned source is not 450x450")
    if row["source_data_type"] != "Int16" or row["decoded_bytes"] != "405000":
        raise SystemExit("pinned source type or decoded size changed")
    if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
        raise SystemExit("invalid pinned source SHA256")
print(f"source_plan=ok files={len(rows)} decoded_bytes={sum(int(row['decoded_bytes']) for row in rows)}")
print(f"source_plan_sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
PY

while IFS=$'\t' read -r selection_ordinal filename url x_offset y_offset source_x_size source_y_size source_data_type decoded_bytes expected_source_bytes expected_sha256; do
  [[ "$selection_ordinal" == "selection_ordinal" ]] && continue
  target="$DOWNLOAD_DIR/$filename"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit ordinal=$selection_ordinal file=$filename"
  else
    echo "fetch ordinal=$selection_ordinal file=$filename"
    curl --fail --silent --show-error --location --retry 4 --retry-delay 3 --max-time 600 \
      --max-filesize 1000000 --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
  actual_bytes="$(wc -c < "$target" | tr -d ' ')"
  [[ "$actual_bytes" == "$expected_source_bytes" ]] || {
    echo "source size mismatch for $filename: $actual_bytes != $expected_source_bytes" >&2
    exit 1
  }
  actual_sha256="$(sha256sum "$target" | awk '{print $1}')"
  [[ "$actual_sha256" == "$expected_sha256" ]] || {
    echo "source SHA256 mismatch for $filename" >&2
    exit 1
  }
done < "$SOURCES"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path


sources = Path(os.environ["SOURCES"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
with sources.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


records = []
for row in rows:
    path = download_dir / row["filename"]
    actual_sha256 = sha256_file(path)
    if path.stat().st_size != int(row["source_bytes"]) or actual_sha256 != row["sha256"]:
        raise SystemExit(f"pinned source identity mismatch: {path.name}")
    records.append({
        "decoded_bytes": int(row["decoded_bytes"]),
        "filename": row["filename"],
        "selection_ordinal": int(row["selection_ordinal"]),
        "sha256": actual_sha256,
        "source_bytes": path.stat().st_size,
        "url": row["url"],
        "x_offset": int(row["x_offset"]),
        "y_offset": int(row["y_offset"]),
    })
source_bytes = sum(record["source_bytes"] for record in records)
if not 103_680_000 <= source_bytes <= 120_000_000:
    raise SystemExit(f"aggregate source size outside bounds: {source_bytes}")
payload = {
    "candidate_id": "isric_soilgrids_clay_i16",
    "decoded_bytes": sum(record["decoded_bytes"] for record in records),
    "files": len(records),
    "records": records,
    "source_bytes": source_bytes,
    "source_plan_sha256": hashlib.sha256(sources.read_bytes()).hexdigest(),
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"downloaded_files={payload['files']} source_bytes={source_bytes}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
