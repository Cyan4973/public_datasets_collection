#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="msd_hippocampus_segmentation_labels_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

ARCHIVE_URL="${MSD_HIPPOCAMPUS_URL:-https://msd-for-monai.s3-us-west-2.amazonaws.com/Task04_Hippocampus.tar}"
LICENSE_URL="${MSD_HIPPOCAMPUS_LICENSE_URL:-https://msd-for-monai.s3-us-west-2.amazonaws.com/license.txt}"
MAX_FILE_BYTES="${MSD_HIPPOCAMPUS_MAX_FILE_BYTES:-100000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
ARCHIVE="$DOWNLOAD_DIR/Task04_Hippocampus.tar"
LICENSE="$DOWNLOAD_DIR/license.txt"

if [ -s "$ARCHIVE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "archive cache_hit bytes=$(wc -c < "$ARCHIVE" | tr -d ' ')"
else
  echo "fetch_archive url=$ARCHIVE_URL"
  curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    --speed-limit 1024 --speed-time 180 \
    -A "$UA" -o "$ARCHIVE.tmp" "$ARCHIVE_URL"
  mv "$ARCHIVE.tmp" "$ARCHIVE"
fi

if [ -s "$LICENSE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "license cache_hit bytes=$(wc -c < "$LICENSE" | tr -d ' ')"
else
  echo "fetch_license url=$LICENSE_URL"
  curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize 1000000 \
    -A "$UA" -o "$LICENSE.tmp" "$LICENSE_URL"
  mv "$LICENSE.tmp" "$LICENSE"
fi

export DATASET_ID ARCHIVE LICENSE ARCHIVE_URL LICENSE_URL MAX_FILE_BYTES DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path

archive = Path(os.environ["ARCHIVE"])
license_path = Path(os.environ["LICENSE"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


if archive.stat().st_size > max_file_bytes:
    raise SystemExit(f"archive exceeds cap: {archive.stat().st_size}")
if license_path.stat().st_size <= 0:
    raise SystemExit("missing or empty license")

with tarfile.open(archive, "r") as tf:
    members = [m for m in tf.getmembers() if m.isfile()]
label_members = sorted(
    m.name
    for m in members
    if "/labelsTr/" in m.name and m.name.endswith(".nii.gz") and not Path(m.name).name.startswith("._")
)
image_members = sorted(
    m.name
    for m in members
    if "/imagesTr/" in m.name and m.name.endswith(".nii.gz") and not Path(m.name).name.startswith("._")
)
has_dataset_json = any(m.name.endswith("/dataset.json") or m.name == "dataset.json" for m in members)
if not label_members:
    raise SystemExit("archive has no labelsTr/*.nii.gz members")
if not has_dataset_json:
    raise SystemExit("archive has no dataset.json")
inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "archive_url": os.environ["ARCHIVE_URL"],
    "license_url": os.environ["LICENSE_URL"],
    "archive_path": archive.name,
    "archive_bytes": archive.stat().st_size,
    "archive_sha256": sha256_file(archive),
    "license_path": license_path.name,
    "license_bytes": license_path.stat().st_size,
    "license_sha256": sha256_file(license_path),
    "label_member_count": len(label_members),
    "image_member_count": len(image_members),
    "first_label_member": label_members[0],
    "last_label_member": label_members[-1],
}
(Path(os.environ["DOWNLOAD_DIR"]) / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok archive_bytes={inventory['archive_bytes']} "
    f"labels={inventory['label_member_count']} imagesTr={inventory['image_member_count']}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
