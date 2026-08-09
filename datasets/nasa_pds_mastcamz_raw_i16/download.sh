#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_pds_mastcamz_raw_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$CANDIDATE_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
PAYLOAD_HASHES="$RECIPE_DIR/payloads.sha256"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

export SOURCES PAYLOAD_HASHES
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


path = Path(os.environ["SOURCES"])
hash_path = Path(os.environ["PAYLOAD_HASHES"])
with path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 52 or [int(row["ordinal"]) for row in rows] != list(range(1, 53)):
    raise SystemExit("pinned Mastcam-Z source count or order changed")
if sum(int(row["label_bytes"]) for row in rows) != 2_851_659:
    raise SystemExit("pinned label-byte total changed")
if sum(int(row["file_bytes"]) for row in rows) != 207_384_320:
    raise SystemExit("pinned IMG-byte total changed")
if sum(int(row["array_bytes"]) for row in rows) != 205_670_400:
    raise SystemExit("pinned array-byte total changed")
if len({row["product_id"] for row in rows}) != len(rows):
    raise SystemExit("duplicate pinned product identity")
hashes = {}
for line in hash_path.read_text(encoding="utf-8").splitlines():
    digest, filename = line.split()
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or filename in hashes:
        raise SystemExit("invalid pinned payload SHA256 plan")
    hashes[filename] = digest
if set(hashes) != {row["payload_filename"] for row in rows}:
    raise SystemExit("pinned payload SHA256 inventory differs from source plan")
for row in rows:
    if not re.fullmatch(r"z[lr][0-7]_[a-z0-9_]+", row["product_id"]):
        raise SystemExit("unsafe Mastcam-Z product identity")
    if Path(urlsplit(row["label_url"]).path).name != row["label_filename"]:
        raise SystemExit("label URL/filename mismatch")
    if Path(urlsplit(row["payload_url"]).path).name != row["payload_filename"]:
        raise SystemExit("payload URL/filename mismatch")
    if not row["label_url"].startswith("https://pds-imaging.jpl.nasa.gov/data/mars2020/mars2020_mastcamz_ops_raw/"):
        raise SystemExit("non-official label URL")
    if not row["payload_url"].startswith("https://pds-imaging.jpl.nasa.gov/data/mars2020/mars2020_mastcamz_ops_raw/"):
        raise SystemExit("non-official payload URL")
    if row["data_type"] != "SignedMSB2" or (row["lines"], row["samples"]) != ("1200", "1648"):
        raise SystemExit("pinned source type or geometry changed")
    if row["array_offset"] != "32960" or row["array_bytes"] != "3955200":
        raise SystemExit("pinned array extent changed")
    if not re.fullmatch(r"[0-9a-f]{64}", row["label_sha256"]):
        raise SystemExit("invalid pinned label SHA256")
print(f"source_plan=ok products={len(rows)} img_bytes={sum(int(row['file_bytes']) for row in rows)}")
print(f"source_plan_sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
PY

while IFS=$'\t' read -r ordinal product_id label_filename payload_filename label_url payload_url label_bytes label_sha256 file_bytes array_offset array_bytes lines samples data_type; do
  [[ "$ordinal" == "ordinal" ]] && continue
  label_target="$DOWNLOAD_DIR/$label_filename"
  payload_target="$DOWNLOAD_DIR/$payload_filename"
  if [[ -s "$label_target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "label_cache_hit ordinal=$ordinal file=$label_filename"
  else
    echo "label_fetch ordinal=$ordinal file=$label_filename"
    curl --fail --silent --show-error --location --retry 4 --retry-delay 3 --max-time 300 \
      --max-filesize 2000000 --output "$label_target.part" "$label_url"
    mv "$label_target.part" "$label_target"
  fi
  [[ "$(stat -c %s "$label_target")" == "$label_bytes" ]] || {
    echo "label size mismatch: $label_filename" >&2
    exit 1
  }
  [[ "$(sha256sum "$label_target" | awk '{print $1}')" == "$label_sha256" ]] || {
    echo "label SHA256 mismatch: $label_filename" >&2
    exit 1
  }
  if [[ -s "$payload_target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "payload_cache_hit ordinal=$ordinal file=$payload_filename"
  else
    echo "payload_fetch ordinal=$ordinal file=$payload_filename"
    curl --fail --silent --show-error --location --retry 4 --retry-delay 3 --max-time 900 \
      --max-filesize 5000000 --output "$payload_target.part" "$payload_url"
    mv "$payload_target.part" "$payload_target"
  fi
  [[ "$(stat -c %s "$payload_target")" == "$file_bytes" ]] || {
    echo "payload size mismatch: $payload_filename" >&2
    exit 1
  }
  expected_payload_sha256="$(awk -v filename="$payload_filename" '$2 == filename {print $1}' "$PAYLOAD_HASHES")"
  [[ "$(sha256sum "$payload_target" | awk '{print $1}')" == "$expected_payload_sha256" ]] || {
    echo "payload SHA256 mismatch: $payload_filename" >&2
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
payload_hashes = Path(os.environ["PAYLOAD_HASHES"])
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
    label = download_dir / row["label_filename"]
    payload = download_dir / row["payload_filename"]
    records.append({
        "array_bytes": int(row["array_bytes"]),
        "array_offset": int(row["array_offset"]),
        "label_bytes": label.stat().st_size,
        "label_filename": label.name,
        "label_sha256": sha256_file(label),
        "ordinal": int(row["ordinal"]),
        "payload_bytes": payload.stat().st_size,
        "payload_filename": payload.name,
        "payload_sha256": sha256_file(payload),
        "product_id": row["product_id"],
    })
result = {
    "candidate_id": "nasa_pds_mastcamz_raw_i16",
    "label_bytes": sum(record["label_bytes"] for record in records),
    "payload_bytes": sum(record["payload_bytes"] for record in records),
    "products": len(records),
    "payload_hash_plan_sha256": hashlib.sha256(payload_hashes.read_bytes()).hexdigest(),
    "records": records,
    "source_plan_sha256": hashlib.sha256(sources.read_bytes()).hexdigest(),
}
if result["label_bytes"] != 2_851_659 or result["payload_bytes"] != 207_384_320:
    raise SystemExit("downloaded aggregate size changed")
(download_dir / "download_inventory.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"downloaded_products={result['products']} payload_bytes={result['payload_bytes']}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
