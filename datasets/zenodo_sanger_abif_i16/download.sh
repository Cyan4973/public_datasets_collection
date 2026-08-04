#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_sanger_abif_i16"
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
USER_AGENT = "openzl-public-datasets-acquisition/1.0"
# Pinned non-clinical records selected from the metadata-only discovery.
EXPECTED = {
    "10829882": (14, 4_624_860),  # HeLa PINK1 cell-line traces
    "14001236": (2, 726_791),  # mouse Prex2 verification
    "15945185": (38, 9_848_986),  # cane-toad CRISPR traces
    "17172684": (6, 1_841_863),  # environmental bacterial 16S traces
    "7840070": (3, 1_076_848),  # cultured-cell-line methylation traces
}
EXPECTED_FILES = 63
EXPECTED_BYTES = 18_119_348
ALLOWED_SUFFIXES = {".ab1", ".abi"}


def run_curl(url: str, target: Path, max_bytes: int) -> None:
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


def license_id(metadata: dict[str, object]) -> str:
    value = metadata.get("license")
    if isinstance(value, dict):
        return str(value.get("id", "")).lower()
    return str(value or "").lower()


inventory: list[dict[str, object]] = []
for record_id, (expected_count, expected_bytes) in EXPECTED.items():
    record_dir = DOWNLOAD_DIR / record_id
    record_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = record_dir / f"record_{record_id}.json"
    metadata_url = f"https://zenodo.org/api/records/{record_id}"
    if not metadata_path.exists():
        print(f"fetch_metadata record={record_id}")
        run_curl(metadata_url, metadata_path, 10_000_000)
    else:
        print(f"metadata_cache_hit record={record_id} bytes={metadata_path.stat().st_size}")
    try:
        record = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid cached metadata for record {record_id}") from exc
    if str(record.get("id", "")) != record_id:
        raise RuntimeError(f"record identity mismatch for {record_id}")
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict) or license_id(metadata) != "cc-by-4.0":
        raise RuntimeError(f"record {record_id} is not explicitly CC BY 4.0")
    files_obj = record.get("files", [])
    if not isinstance(files_obj, list):
        raise RuntimeError(f"record {record_id} has no file inventory")
    files = []
    for file_obj in files_obj:
        if not isinstance(file_obj, dict):
            continue
        key = str(file_obj.get("key", ""))
        if Path(key.lower()).suffix not in ALLOWED_SUFFIXES:
            continue
        if Path(key).name != key or key in {"", ".", ".."}:
            raise RuntimeError(f"unsafe ABIF key in record {record_id}: {key!r}")
        files.append(file_obj)
    actual_bytes = sum(int(file_obj.get("size", 0) or 0) for file_obj in files)
    if len(files) != expected_count or actual_bytes != expected_bytes:
        raise RuntimeError(
            f"record {record_id} inventory drift: files={len(files)}/{expected_count} "
            f"bytes={actual_bytes}/{expected_bytes}"
        )
    for file_obj in sorted(files, key=lambda value: str(value.get("key", ""))):
        key = str(file_obj["key"])
        size = int(file_obj["size"])
        checksum = str(file_obj.get("checksum", ""))
        if not checksum.startswith("md5:") or len(checksum) != 36:
            raise RuntimeError(f"missing MD5 for record={record_id} key={key}")
        expected_md5 = checksum[4:].lower()
        links = file_obj.get("links", {})
        if not isinstance(links, dict):
            links = {}
        url = str(links.get("content") or links.get("self") or "")
        if not url:
            raise RuntimeError(f"missing content URL for record={record_id} key={key}")
        target = record_dir / key
        valid_cache = (
            target.is_file()
            and target.stat().st_size == size
            and md5_file(target) == expected_md5
        )
        if valid_cache:
            print(f"cache_hit record={record_id} bytes={size} key={key}")
        else:
            print(f"fetch record={record_id} bytes={size} key={key}")
            run_curl(url, target, min(200_000_000, size + 1))
            actual_md5 = md5_file(target)
            if target.stat().st_size != size or actual_md5 != expected_md5:
                target.unlink(missing_ok=True)
                raise RuntimeError(f"payload mismatch record={record_id} key={key}")
        inventory.append(
            {
                "record_id": record_id,
                "key": key,
                "bytes": size,
                "md5": expected_md5,
                "relative_path": str(target.relative_to(DOWNLOAD_DIR)),
                "url": url,
            }
        )

if len(inventory) != EXPECTED_FILES or sum(int(row["bytes"]) for row in inventory) != EXPECTED_BYTES:
    raise SystemExit("aggregate pinned inventory mismatch")
(DOWNLOAD_DIR / "source_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"download_complete records={len(EXPECTED)} files={len(inventory)} "
    f"bytes={sum(int(row['bytes']) for row in inventory)}"
)
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
