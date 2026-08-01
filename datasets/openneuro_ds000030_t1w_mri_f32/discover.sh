#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="openneuro_ds000030_t1w_mri_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
FILE_LIMIT="${FILE_LIMIT:-20}"
MAX_PLANNED_BYTES="${MAX_PLANNED_BYTES:-900000000}"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] metadata discovery start dataset=$CANDIDATE_ID"

export OUT_DIR FILE_LIMIT MAX_PLANNED_BYTES
python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET


DATASET = "ds000030"
BUCKET_BASE = "https://s3.amazonaws.com/openneuro.org"
PREFIX = f"{DATASET}/"
OUT_DIR = Path(os.environ["OUT_DIR"])
FILE_LIMIT = int(os.environ["FILE_LIMIT"])
MAX_PLANNED_BYTES = int(os.environ["MAX_PLANNED_BYTES"])
USER_AGENT = "openzl-public-datasets-metadata-discovery/1.0"
T1_PATTERN = re.compile(r"(?:^|/)(sub-[^/]+)/anat/[^/]*_T1w\.nii\.gz$")


def request_bytes(url: str) -> bytes:
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
            "90",
            "--user-agent",
            USER_AGENT,
            url,
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def object_url(key: str) -> str:
    return f"{BUCKET_BASE}/{urllib.parse.quote(key, safe='/')}"


objects: list[dict[str, object]] = []
token: str | None = None
while True:
    query = {"list-type": "2", "prefix": PREFIX, "max-keys": "1000"}
    if token:
        query["continuation-token"] = token
    url = f"{BUCKET_BASE}?{urllib.parse.urlencode(query)}"
    root = ET.fromstring(request_bytes(url))
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"
    for content in root.findall(f"{namespace}Contents"):
        key = content.findtext(f"{namespace}Key") or ""
        size = int(content.findtext(f"{namespace}Size") or 0)
        etag = (content.findtext(f"{namespace}ETag") or "").strip('"')
        objects.append({"key": key, "size": size, "etag": etag})
    truncated = (root.findtext(f"{namespace}IsTruncated") or "false").lower() == "true"
    if not truncated:
        break
    token = root.findtext(f"{namespace}NextContinuationToken")
    if not token:
        raise SystemExit("S3 listing is truncated but has no continuation token")

groups: dict[str, list[dict[str, object]]] = defaultdict(list)
for item in objects:
    key = str(item["key"])
    if "/derivatives/" in key or "/sourcedata/" in key:
        continue
    match = T1_PATTERN.search(key)
    if not match:
        continue
    root = key[: match.start(1)].rstrip("/")
    groups[root].append(item)

if not groups:
    raise SystemExit(f"no BIDS T1w NIfTI objects found below {PREFIX}")

# Prefer the root containing the most T1w objects; use its path as a stable
# tie-breaker so discovery is deterministic if multiple releases are present.
release_root, candidates = sorted(
    groups.items(), key=lambda pair: (-len(pair[1]), pair[0])
)[0]
candidates.sort(key=lambda item: str(item["key"]))

description_key = f"{release_root}/dataset_description.json"
description_matches = [item for item in objects if item["key"] == description_key]
if not description_matches:
    fallback = f"{DATASET}/dataset_description.json"
    description_matches = [item for item in objects if item["key"] == fallback]
    if description_matches:
        description_key = fallback
if not description_matches:
    raise SystemExit(
        f"no dataset_description.json found for selected release root {release_root}"
    )

description_raw = request_bytes(object_url(description_key))
description = json.loads(description_raw)
license_value = str(description.get("License", "")).strip()
normalized_license = re.sub(r"[^a-z0-9]+", "", license_value.lower())
allowed = (
    normalized_license in {"pddl", "cc0", "cc01", "cc010", "ccby", "ccby40"}
    or normalized_license.startswith("creativecommonszero")
    or normalized_license.startswith("creativecommonsattribution")
)
if not allowed:
    raise SystemExit(
        f"dataset license is not explicitly approved: License={license_value!r}"
    )

selected: list[dict[str, object]] = []
planned_bytes = 0
for item in candidates:
    size = int(item["size"])
    if len(selected) >= FILE_LIMIT:
        break
    if size <= 0 or planned_bytes + size > MAX_PLANNED_BYTES:
        continue
    selected.append(item)
    planned_bytes += size

if len(selected) < 5:
    raise SystemExit(
        f"only {len(selected)} T1w objects fit the bounded plan; need at least 5"
    )

OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "dataset_description.json").write_bytes(description_raw)
with (OUT_DIR / "all_t1w_objects.tsv").open("w", encoding="utf-8") as handle:
    handle.write("key\tbytes\tetag\turl\n")
    for item in candidates:
        handle.write(
            f"{item['key']}\t{item['size']}\t{item['etag']}\t"
            f"{object_url(str(item['key']))}\n"
        )
with (OUT_DIR / "selected_t1w_plan.tsv").open("w", encoding="utf-8") as handle:
    handle.write("key\tbytes\tetag\turl\n")
    for item in selected:
        handle.write(
            f"{item['key']}\t{item['size']}\t{item['etag']}\t"
            f"{object_url(str(item['key']))}\n"
        )
summary = {
    "candidate_id": "openneuro_ds000030_t1w_mri_f32",
    "dataset_id": DATASET,
    "release_root": release_root,
    "dataset_name": description.get("Name"),
    "license": license_value,
    "description_key": description_key,
    "listed_objects": len(objects),
    "candidate_t1w_objects": len(candidates),
    "selected_objects": len(selected),
    "selected_compressed_bytes": planned_bytes,
    "file_limit": FILE_LIMIT,
    "max_planned_bytes": MAX_PLANNED_BYTES,
}
(OUT_DIR / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
print(f"plan={OUT_DIR / 'selected_t1w_plan.tsv'}")
PY

echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
