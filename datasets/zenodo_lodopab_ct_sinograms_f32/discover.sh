#!/usr/bin/env bash
# Metadata-only discovery for the LoDoPaB-CT Zenodo record.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_lodopab_ct_sinograms_f32"
RECORD_ID="${LODOPAB_ZENODO_RECORD_ID:-3384092}"
API_URL="https://zenodo.org/api/records/$RECORD_ID"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
UA="openzl-public-datasets-lodopab-discovery/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] metadata discovery start candidate=$CANDIDATE_ID record=$RECORD_ID"

curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 180 --max-filesize 20000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$OUT_DIR/record.json.part" "$API_URL"
mv "$OUT_DIR/record.json.part" "$OUT_DIR/record.json"

python3 - "$OUT_DIR/record.json" "$OUT_DIR/files.tsv" "$OUT_DIR/candidates.tsv" "$OUT_DIR/summary.json" <<'PY'
from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import re
import sys


record_path, files_path, candidates_path, summary_path = map(Path, sys.argv[1:])
try:
    record = json.loads(record_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"invalid Zenodo record JSON: {exc}") from exc
if not isinstance(record, dict):
    raise SystemExit("Zenodo response is not an object")

metadata = record.get("metadata")
if not isinstance(metadata, dict):
    raise SystemExit("Zenodo response has no metadata object")
title = str(metadata.get("title") or "")
description = html.unescape(re.sub(r"<[^>]+>", " ", str(metadata.get("description") or "")))
normalized_identity = re.sub(r"[^a-z0-9]+", "", f"{title} {description}".lower())
if "lodopabct" not in normalized_identity:
    raise SystemExit(f"unexpected Zenodo record title/description: {title!r}")

license_value = metadata.get("license")
if isinstance(license_value, dict):
    license_id = str(license_value.get("id") or license_value.get("title") or "")
else:
    license_id = str(license_value or "")
normalized_license = license_id.lower().replace("_", "-").replace(" ", "-")
if normalized_license not in {"cc-by-4.0", "creative-commons-attribution-4.0-international"}:
    raise SystemExit(
        f"record does not expose the expected permissive CC BY 4.0 license: {license_id!r}"
    )

files = record.get("files")
if not isinstance(files, list) or not files:
    raise SystemExit("Zenodo record has no files")

rows: list[dict[str, object]] = []
for item in files:
    if not isinstance(item, dict):
        continue
    key = str(item.get("key") or "")
    size = int(item.get("size") or 0)
    checksum = str(item.get("checksum") or "")
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    url = str(links.get("self") or links.get("download") or "")
    rows.append(
        {
            "key": key,
            "size_bytes": size,
            "checksum": checksum,
            "url": url,
        }
    )
rows.sort(key=lambda row: str(row["key"]))
with files_path.open("w", encoding="utf-8", newline="") as destination:
    writer = csv.DictWriter(
        destination,
        fieldnames=("key", "size_bytes", "checksum", "url"),
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)

observation_pattern = re.compile(
    r"(?:^|/)(?:observation|observations)[_-](train|validation|test)[_-]?(\d+)?\.(h5|hdf5|zip)$",
    flags=re.IGNORECASE,
)
candidates: list[dict[str, object]] = []
for row in rows:
    match = observation_pattern.search(str(row["key"]))
    if not match:
        continue
    split = match.group(1).lower()
    shard_text = match.group(2) or ""
    shard = int(shard_text) if shard_text else -1
    size = int(row["size_bytes"])
    # Prefer complete, reasonably bounded train/validation shards. Test data
    # remain candidates, but are ranked after data explicitly intended for
    # model development.
    split_rank = {"validation": 0, "train": 1, "test": 2}[split]
    bounded = 10_000_000 <= size <= 750_000_000
    candidates.append(
        {
            **row,
            "split": split,
            "shard": shard,
            "bounded": int(bounded),
            "preference_rank": split_rank,
        }
    )
candidates.sort(
    key=lambda row: (
        -int(row["bounded"]),
        int(row["preference_rank"]),
        int(row["shard"]),
        str(row["key"]),
    )
)
with candidates_path.open("w", encoding="utf-8", newline="") as destination:
    writer = csv.DictWriter(
        destination,
        fieldnames=(
            "preference_rank",
            "bounded",
            "split",
            "shard",
            "key",
            "size_bytes",
            "checksum",
            "url",
        ),
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(candidates)

bounded_candidates = [row for row in candidates if int(row["bounded"]) == 1]
creators = []
for creator in metadata.get("creators", []):
    if isinstance(creator, dict) and creator.get("name"):
        creators.append(str(creator["name"]))
summary = {
    "candidate_id": "zenodo_lodopab_ct_sinograms_f32",
    "metadata_only": True,
    "record_id": int(record.get("id") or 0),
    "conceptrecid": str(record.get("conceptrecid") or ""),
    "doi": str(metadata.get("doi") or ""),
    "title": title,
    "publication_date": str(metadata.get("publication_date") or ""),
    "version": str(metadata.get("version") or ""),
    "license": license_id,
    "creators": creators,
    "file_count": len(rows),
    "total_record_bytes": sum(int(row["size_bytes"]) for row in rows),
    "observation_shards": len(candidates),
    "bounded_observation_shards": len(bounded_candidates),
    "preferred_probe_candidates": bounded_candidates[:8],
    "payloads_downloaded": 0,
    "next_step": (
        "download one exact bounded observation shard and inspect HDF5 dtype/shape"
        if bounded_candidates
        else "inspect file naming/layout; no bounded observation shard matched the expected pattern"
    ),
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
if not candidates:
    raise SystemExit("record contains no observation HDF5/ZIP shard matching the expected naming scheme")
if not bounded_candidates:
    print(
        "outer observation archives are oversized; run discover_zip.sh to inspect "
        "validation-archive members by HTTP range"
    )
PY

echo "[$(date -Is)] metadata discovery done candidate=$CANDIDATE_ID"
