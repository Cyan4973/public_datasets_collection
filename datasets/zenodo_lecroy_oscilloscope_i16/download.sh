#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_lecroy_oscilloscope_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


DOWNLOAD_DIR = Path(os.environ["DOWNLOAD_DIR"])
# Immutable source selected by the bounded LeCroy header discovery.
RECORD_ID = "7939431"
EXPECTED_TITLE = "Hypervelocity impact RF/optical measurements"
EXPECTED_FILES = 21
EXPECTED_BYTES = 30_007_565
USER_AGENT = "openzl-public-datasets-acquisition/1.0"


def fetch(url: str, target: Path, max_bytes: int) -> None:
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--retry",
            "3",
            "--max-time",
            "600",
            "--max-filesize",
            str(max_bytes),
            "--user-agent",
            USER_AGENT,
            "--output",
            str(part),
            url,
        ],
        check=False,
    )
    if result.returncode != 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"curl failed rc={result.returncode}: {url}")
    if not part.is_file() or part.stat().st_size > max_bytes:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"invalid or oversized response: {url}")
    part.replace(target)


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


metadata_path = DOWNLOAD_DIR / f"record_{RECORD_ID}.json"
metadata_url = f"https://zenodo.org/api/records/{RECORD_ID}"
if not metadata_path.exists():
    print(f"fetch_metadata record={RECORD_ID}")
    fetch(metadata_url, metadata_path, 10_000_000)
else:
    print(f"metadata_cache_hit bytes={metadata_path.stat().st_size}")
try:
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise RuntimeError("cached record metadata is invalid") from exc
if str(record.get("id", "")) != RECORD_ID:
    raise RuntimeError("Zenodo record identity changed")
metadata = record.get("metadata", {})
if not isinstance(metadata, dict):
    raise RuntimeError("Zenodo metadata object is missing")
license_obj = metadata.get("license", {})
license_id = str(license_obj.get("id", "")) if isinstance(license_obj, dict) else str(license_obj)
if license_id.lower() != "cc-by-4.0":
    raise RuntimeError(f"record license changed: {license_id!r}")
if str(metadata.get("title", "")) != EXPECTED_TITLE:
    raise RuntimeError(f"record title changed: {metadata.get('title')!r}")

files_obj = record.get("files", [])
if not isinstance(files_obj, list):
    raise RuntimeError("Zenodo file inventory is missing")
files = []
for file_obj in files_obj:
    if not isinstance(file_obj, dict):
        continue
    key = str(file_obj.get("key", ""))
    if Path(key.lower()).suffix != ".trc":
        continue
    if Path(key).name != key or key in {"", ".", ".."}:
        raise RuntimeError(f"unsafe TRC key: {key!r}")
    files.append(file_obj)
actual_bytes = sum(int(file_obj.get("size", 0) or 0) for file_obj in files)
if len(files) != EXPECTED_FILES or actual_bytes != EXPECTED_BYTES:
    raise RuntimeError(
        f"TRC inventory drift files={len(files)}/{EXPECTED_FILES} "
        f"bytes={actual_bytes}/{EXPECTED_BYTES}"
    )

inventory: list[dict[str, object]] = []
for file_obj in sorted(files, key=lambda value: str(value.get("key", ""))):
    key = str(file_obj["key"])
    size = int(file_obj["size"])
    checksum = str(file_obj.get("checksum", ""))
    if not checksum.startswith("md5:") or len(checksum) != 36:
        raise RuntimeError(f"missing MD5 for {key}")
    expected_md5 = checksum[4:].lower()
    links = file_obj.get("links", {})
    if not isinstance(links, dict):
        links = {}
    url = str(links.get("content") or links.get("self") or "")
    if not url:
        raise RuntimeError(f"missing content URL for {key}")
    target = DOWNLOAD_DIR / key
    valid_cache = (
        target.is_file()
        and target.stat().st_size == size
        and md5_file(target) == expected_md5
    )
    if valid_cache:
        print(f"cache_hit bytes={size} key={key}")
    else:
        print(f"fetch bytes={size} key={key}")
        fetch(url, target, min(1_000_000_000, size + 1))
        if target.stat().st_size != size or md5_file(target) != expected_md5:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"payload mismatch for {key}")
    inventory.append(
        {
            "record_id": RECORD_ID,
            "key": key,
            "bytes": size,
            "md5": expected_md5,
            "relative_path": key,
            "url": url,
        }
    )

(DOWNLOAD_DIR / "source_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"download_complete files={len(inventory)} bytes={sum(int(row['bytes']) for row in inventory)}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
