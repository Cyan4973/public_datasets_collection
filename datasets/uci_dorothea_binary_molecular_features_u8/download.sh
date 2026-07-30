#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_dorothea_binary_molecular_features_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${DOROTHEA_URL:-https://archive.ics.uci.edu/static/public/169/dorothea.zip}"
ARCHIVE="$DOWNLOAD_DIR/dorothea.zip"
MIN_ARCHIVE_BYTES="${DOROTHEA_MIN_ARCHIVE_BYTES:-100000}"
MAX_ARCHIVE_BYTES="${DOROTHEA_MAX_ARCHIVE_BYTES:-500000000}"
UA="${DOROTHEA_UA:-openzl-public-datasets/1.0}"

if [ -f "$ARCHIVE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "cache_hit path=$ARCHIVE bytes=$(wc -c < "$ARCHIVE" | tr -d ' ')"
else
  rm -f "$ARCHIVE.part"
  curl --globoff -fL --retry 5 --retry-all-errors --retry-delay 5 \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    -A "$UA" -o "$ARCHIVE.part" "$URL"
  mv "$ARCHIVE.part" "$ARCHIVE"
fi

archive_bytes="$(wc -c < "$ARCHIVE" | tr -d ' ')"
if [ "$archive_bytes" -lt "$MIN_ARCHIVE_BYTES" ] || [ "$archive_bytes" -gt "$MAX_ARCHIVE_BYTES" ]; then
  echo "FATAL: archive size outside bounds bytes=$archive_bytes min=$MIN_ARCHIVE_BYTES max=$MAX_ARCHIVE_BYTES" >&2
  exit 1
fi

export ARCHIVE EXTRACT_DIR DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

archive = Path(os.environ["ARCHIVE"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
member_pattern = re.compile(r"(?:^|/)dorothea_(train|valid|test)\.data$", re.IGNORECASE)
expected_rows = {"train": 800, "valid": 350, "test": 800}
feature_count = 100_000

if not zipfile.is_zipfile(archive):
    raise SystemExit(f"not a valid ZIP archive: {archive}")
if extract_dir.exists():
    shutil.rmtree(extract_dir)
extract_dir.mkdir(parents=True)

with zipfile.ZipFile(archive) as zf:
    members: dict[str, zipfile.ZipInfo] = {}
    total_uncompressed = 0
    for info in zf.infolist():
        member_path = PurePosixPath(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        total_uncompressed += info.file_size
        if total_uncompressed > 1_000_000_000:
            raise SystemExit("archive uncompressed content exceeds 1 GB safety cap")
        match = member_pattern.search(info.filename)
        if not match or info.is_dir():
            continue
        split = match.group(1).lower()
        if split in members:
            raise SystemExit(f"duplicate sparse matrix for split={split}")
        if info.file_size > 250_000_000:
            raise SystemExit(f"matrix member too large: {info.filename} bytes={info.file_size}")
        members[split] = info

    if set(members) != set(expected_rows):
        raise SystemExit(
            f"split set mismatch found={sorted(members)} expected={sorted(expected_rows)}"
        )

    inventory: list[dict[str, object]] = []
    for split in ("train", "valid", "test"):
        info = members[split]
        output = extract_dir / f"dorothea_{split}.data"
        rows = 0
        total_active = 0
        min_active: int | None = None
        max_active = 0
        with zf.open(info) as source, output.open("wb") as destination:
            for source_line, raw in enumerate(source, 1):
                destination.write(raw)
                if not raw.strip():
                    raise SystemExit(f"empty sparse row split={split} source_line={source_line}")
                try:
                    tokens = raw.decode("ascii").split()
                    indices = [int(token) for token in tokens]
                except (UnicodeDecodeError, ValueError) as exc:
                    raise SystemExit(f"malformed sparse row split={split} source_line={source_line}: {exc}")
                if not indices:
                    raise SystemExit(f"all-zero/empty sparse row split={split} source_line={source_line}")
                if indices[0] < 1 or indices[-1] > feature_count:
                    raise SystemExit(
                        f"index outside 1..{feature_count} split={split} source_line={source_line} "
                        f"range={indices[0]}..{indices[-1]}"
                    )
                if any(left >= right for left, right in zip(indices, indices[1:])):
                    raise SystemExit(f"indices not strictly increasing split={split} source_line={source_line}")
                active = len(indices)
                total_active += active
                min_active = active if min_active is None else min(min_active, active)
                max_active = max(max_active, active)
                rows += 1
        if rows != expected_rows[split]:
            raise SystemExit(f"row count mismatch split={split} rows={rows} expected={expected_rows[split]}")
        inventory.append({
            "split": split,
            "zip_member": info.filename,
            "source_size_bytes": info.file_size,
            "rows": rows,
            "feature_count": feature_count,
            "total_active_features": total_active,
            "min_active_features": min_active,
            "max_active_features": max_active,
            "extracted_filename": output.name,
        })
        print(
            f"validated split={split} rows={rows} active_min={min_active} "
            f"active_max={max_active} active_total={total_active} member={info.filename}"
        )

inventory_path = download_dir / "inventory.tsv"
with inventory_path.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=[
            "split", "zip_member", "source_size_bytes", "rows", "feature_count",
            "total_active_features", "min_active_features", "max_active_features",
            "extracted_filename",
        ],
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(inventory)
print(f"validated_archive splits=3 rows={sum(expected_rows.values())} total_uncompressed_bytes={total_uncompressed}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID archive_bytes=$archive_bytes"
