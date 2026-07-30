#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_mhealth_activity_state_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${MHEALTH_URL:-https://archive.ics.uci.edu/static/public/319/mhealth+dataset.zip}"
ARCHIVE="$DOWNLOAD_DIR/mhealth_dataset.zip"
MIN_ARCHIVE_BYTES="${MHEALTH_MIN_ARCHIVE_BYTES:-1000000}"
MAX_ARCHIVE_BYTES="${MHEALTH_MAX_ARCHIVE_BYTES:-500000000}"
UA="${MHEALTH_UA:-openzl-public-datasets/1.0}"

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
pattern = re.compile(r"(?:^|/)mhealth_subject(\d+)\.log$", re.IGNORECASE)

if not zipfile.is_zipfile(archive):
    raise SystemExit(f"not a valid ZIP archive: {archive}")
if extract_dir.exists():
    shutil.rmtree(extract_dir)
extract_dir.mkdir(parents=True)

with zipfile.ZipFile(archive) as zf:
    subject_members: dict[int, zipfile.ZipInfo] = {}
    total_uncompressed = 0
    for info in zf.infolist():
        member_path = PurePosixPath(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        total_uncompressed += info.file_size
        if total_uncompressed > 1_000_000_000:
            raise SystemExit("archive uncompressed content exceeds 1 GB safety cap")
        match = pattern.search(info.filename)
        if not match or info.is_dir():
            continue
        subject = int(match.group(1))
        if subject in subject_members:
            raise SystemExit(f"duplicate subject recording: {subject}")
        if info.file_size > 200_000_000:
            raise SystemExit(f"subject member too large: {info.filename} bytes={info.file_size}")
        subject_members[subject] = info

    expected = set(range(1, 11))
    if set(subject_members) != expected:
        raise SystemExit(
            f"subject set mismatch found={sorted(subject_members)} expected={sorted(expected)}"
        )

    inventory: list[dict[str, object]] = []
    for subject in sorted(subject_members):
        info = subject_members[subject]
        output = extract_dir / f"subject{subject:02d}.log"
        rows = 0
        labels: set[int] = set()
        with zf.open(info) as source, output.open("wb") as destination:
            for raw in source:
                destination.write(raw)
                if not raw.strip():
                    continue
                try:
                    fields = raw.decode("ascii").split()
                except UnicodeDecodeError as exc:
                    raise SystemExit(f"non-ASCII row subject={subject} row={rows + 1}: {exc}")
                if len(fields) != 24:
                    raise SystemExit(
                        f"wrong field count subject={subject} row={rows + 1} fields={len(fields)} expected=24"
                    )
                try:
                    label_float = float(fields[-1])
                except ValueError as exc:
                    raise SystemExit(f"invalid label subject={subject} row={rows + 1}: {exc}")
                label = int(label_float)
                if label_float != label or not 0 <= label <= 12:
                    raise SystemExit(
                        f"out-of-range/non-integral label subject={subject} row={rows + 1} value={fields[-1]}"
                    )
                labels.add(label)
                rows += 1
        if rows < 1_000:
            raise SystemExit(f"subject recording too short subject={subject} rows={rows}")
        if len(labels) <= 1:
            raise SystemExit(f"constant subject label stream subject={subject} labels={sorted(labels)}")
        inventory.append({
            "subject": subject,
            "zip_member": info.filename,
            "source_size_bytes": info.file_size,
            "rows": rows,
            "labels": ",".join(str(value) for value in sorted(labels)),
            "extracted_path": output.as_posix(),
        })
        print(
            f"validated subject={subject} rows={rows} labels={sorted(labels)} "
            f"member={info.filename}"
        )

inventory_path = download_dir / "inventory.tsv"
with inventory_path.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=["subject", "zip_member", "source_size_bytes", "rows", "labels", "extracted_path"],
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(inventory)
print(f"validated_archive subjects={len(inventory)} total_uncompressed_bytes={total_uncompressed}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID archive_bytes=$archive_bytes"
