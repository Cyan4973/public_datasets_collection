#!/usr/bin/env bash
# Acquire exact complete frame ranges without downloading the oversized MRC object.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_tem_tilt_series_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


download_dir = Path(os.environ["DOWNLOAD_DIR"])
record_id = "3985424"
title = "Electron microscopy of SARS-CoV-2 particles - Dataset 05"
name = "Dataset_05_SARS-CoV-2_009.mrc"
source_bytes = 1_048_708_096
source_md5 = "5cb0286e5a75ce2d330efa8c7e1440ae"
header_bytes = 132_096
header_sha256 = "50371751ebc9c6f011614b17ba577b1cce3db3480db13a0441fa36a6b4fb20c6"
frame_bytes = 8_388_608
selected = tuple(range(0, 125, 2))
selection_sha256 = "931d9bd9099d92bc9a50e574023eab8f52bba0d4ac006494e151c4b38ee876cb"
user_agent = "openzl-public-datasets-acquisition/1.0"


def fetch(url: str, target: Path, max_bytes: int, byte_range: tuple[int, int] | None = None) -> None:
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "5", "--retry-delay", "2", "--max-time", "1800",
        "--max-filesize", str(max_bytes), "--user-agent", user_agent,
    ]
    if byte_range is not None:
        command.extend(["--range", f"{byte_range[0]}-{byte_range[1]}"])
    command.extend(["--output", str(part), url])
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"curl failed rc={result.returncode}: {url}")
    if not part.is_file() or part.stat().st_size > max_bytes:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"invalid or oversized response: {url}")
    part.replace(target)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def selection_digest() -> str:
    digest = hashlib.sha256()
    for index in selected:
        with (download_dir / f"frame_{index:04d}.i16le").open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest()


metadata_path = download_dir / f"record_{record_id}.json"
fetch(f"https://zenodo.org/api/records/{record_id}", metadata_path, 10_000_000)
record = json.loads(metadata_path.read_text(encoding="utf-8"))
metadata = record.get("metadata", {})
if str(record.get("id", "")) != record_id or metadata.get("title") != title:
    raise RuntimeError("unexpected Zenodo record identity")
if metadata.get("license", {}).get("id") != "cc-by-4.0":
    raise RuntimeError("record no longer declares CC BY 4.0")
description = str(metadata.get("description", "")).lower()
if "raw image tilt series" not in description or "mrc format" not in description:
    raise RuntimeError("record no longer documents the MRC as a raw image tilt series")
matching = [item for item in record.get("files", []) if item.get("key") == name]
if len(matching) != 1:
    raise RuntimeError("pinned MRC source is absent or ambiguous")
item = matching[0]
if int(item.get("size", 0)) != source_bytes or item.get("checksum") != f"md5:{source_md5}":
    raise RuntimeError("pinned MRC source identity changed")
links = item.get("links", {})
url = str(links.get("content") or links.get("self") or "") if isinstance(links, dict) else ""
if not url:
    raise RuntimeError("MRC content URL is missing")

header = download_dir / "header_and_extended.bin"
if not header.is_file() or header.stat().st_size != header_bytes or sha256(header) != header_sha256:
    print("fetch header_and_extended range=0-132095")
    fetch(url, header, header_bytes + 1, (0, header_bytes - 1))
if header.stat().st_size != header_bytes or sha256(header) != header_sha256:
    raise RuntimeError("MRC header-range identity mismatch")

def acquire_all(force: bool) -> None:
    for position, index in enumerate(selected, start=1):
        target = download_dir / f"frame_{index:04d}.i16le"
        start = header_bytes + index * frame_bytes
        end = start + frame_bytes - 1
        if not force and target.is_file() and target.stat().st_size == frame_bytes:
            print(f"cache_hit frame={index} progress={position}/{len(selected)}")
            continue
        print(f"fetch frame={index} range={start}-{end} progress={position}/{len(selected)}")
        fetch(url, target, frame_bytes + 1, (start, end))
        if target.stat().st_size != frame_bytes:
            raise RuntimeError(f"frame range size mismatch: {index}")


acquire_all(False)
digest = selection_digest()
if digest != selection_sha256:
    print("selected digest mismatch; refreshing all ranges")
    acquire_all(True)
    digest = selection_digest()
if digest != selection_sha256:
    raise RuntimeError(f"selected projection digest mismatch: {digest}")

inventory = {
    "record_id": record_id,
    "record_title": title,
    "license": "cc-by-4.0",
    "source_name": name,
    "source_bytes": source_bytes,
    "source_md5": source_md5,
    "header_sha256": header_sha256,
    "selected_frame_indices": list(selected),
    "selected_frame_count": len(selected),
    "selected_sample_bytes": len(selected) * frame_bytes,
    "selection_sha256": digest,
}
(download_dir / "source_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"download_complete frames={len(selected)} bytes={len(selected) * frame_bytes} sha256={digest}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
