#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="cifar10_pixels_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
MAX_IMAGES="${CIFAR_MAX_IMAGES:-60000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MAX_IMAGES
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import tarfile
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_images = int(os.environ["MAX_IMAGES"])

DATASET_ID = "cifar10_pixels_u8"
FAMILY = "cifar_pixel_u8"
REC = 3073          # 1 label byte + 3072 pixel bytes (32x32x3)
PLANE = 1024        # one 32x32 single-channel plane
CLASSES = ["airplane", "automobile", "bird", "cat", "deer", "dog",
           "frog", "horse", "ship", "truck"]

src = download_dir / "cifar-10-binary.tar.gz"
if not src.is_file():
    raise SystemExit(f"missing {src}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
fam_dir = samples_dir / FAMILY
fam_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
images = 0
skipped_constant = 0
per_class: dict[str, int] = {}  # class name -> running image index

with tarfile.open(src, "r:gz") as t:
    # iterate in archive order and extract each member in the same pass: a gzip tar
    # stream cannot seek backward, so getmembers()-then-extractfile() drops earlier members.
    for m in t:
        bn = m.name.rsplit("/", 1)[-1]
        # CIFAR-10 record files: data_batch_1.bin .. data_batch_5.bin and test_batch.bin
        if not (bn.endswith(".bin") and ("data_batch" in bn or "test_batch" in bn)):
            continue
        if images >= max_images:
            break
        f = t.extractfile(m)
        if f is None:
            continue
        blob = f.read()  # whole member; tar stream reads can be short, so don't read(REC)
        nrec = len(blob) // REC
        for ri in range(nrec):
            if images >= max_images:
                break
            rec = blob[ri * REC:(ri + 1) * REC]
            label = rec[0]
            cname = CLASSES[label] if 0 <= label < len(CLASSES) else f"class{label}"
            pixels = rec[1:]  # 1024 R, then 1024 G, then 1024 B
            ci = per_class.get(cname, 0)
            # one sample per single-channel 32x32 plane (R/G/B are the same quantity:
            # pixel intensity), matching the existing cifar10_rgb_32x32 layout.
            for k, ch in enumerate("rgb"):
                plane = pixels[k * PLANE:(k + 1) * PLANE]
                if len(set(plane)) <= 1:
                    skipped_constant += 1
                    continue
                out = fam_dir / f"{cname}_{ci:05d}_{ch}_32x32.bin"
                out.write_bytes(plane)  # uint8 (raw bytes)
                index_rows.append({
                    "dataset_id": DATASET_ID,
                    "series_id": FAMILY,
                    "role": "primary",
                    "sample_path": out.relative_to(data_root).as_posix(),
                    "numeric_kind": "uint",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "sample_size_bytes": len(plane),
                    "value_count": PLANE,
                    "sample_geometry": "grid_32x32",
                    "sample_rank": 2,
                    "image_class": cname,
                    "channel": ch,
                    "natural_record_kind": "cifar10_channel_plane",
                })
            per_class[cname] = ci + 1
            images += 1

if len(index_rows) < 5:
    raise SystemExit(f"only {len(index_rows)} samples produced")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "families": {FAMILY: len(index_rows)},
    "samples": len(index_rows),
    "images": images,
    "skipped_constant_planes": skipped_constant,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "value_count_per_sample": PLANE,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built family={FAMILY} images={images} samples={len(index_rows)} "
      f"skipped_constant={skipped_constant} primary_values={primary_values}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
