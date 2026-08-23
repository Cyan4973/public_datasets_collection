#!/usr/bin/env bash
# Discover licensed Wikimedia copies of Blender Open Movies without downloading videos.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="blender_open_movies_yuv420_u8"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PROJECTS="$RECIPE_DIR/projects.tsv"
OUTPUT="$DISCOVERY_DIR/candidates.tsv"

mkdir -p "$DISCOVERY_DIR/metadata" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

fetch_metadata() {
  local target="$1" title="$2"
  rm -f "$target.part"
  curl --globoff --fail-with-body --silent --show-error --location --get \
    --retry 4 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 180 --max-filesize 5000000 \
    --user-agent "openzl-public-datasets/1.0" \
    --data-urlencode "action=query" \
    --data-urlencode "titles=$title" \
    --data-urlencode "prop=videoinfo" \
    --data-urlencode "viprop=url|size|mime|extmetadata|derivatives" \
    --data-urlencode "format=json" \
    --data-urlencode "formatversion=2" \
    --output "$target.part" "https://commons.wikimedia.org/w/api.php"
  test -s "$target.part" || { echo "empty Commons API response: $title" >&2; exit 1; }
  mv "$target.part" "$target"
}

tail -n +2 "$PROJECTS" | while IFS=$'\t' read -r project_id title; do
  test -n "$project_id" || continue
  echo "query project=$project_id title=$title"
  fetch_metadata "$DISCOVERY_DIR/metadata/${project_id}.json" "$title"
done

PROJECTS="$PROJECTS" METADATA="$DISCOVERY_DIR/metadata" OUTPUT="$OUTPUT" python3 - <<'PY'
from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path


projects_path = Path(os.environ["PROJECTS"])
metadata_dir = Path(os.environ["METADATA"])
output = Path(os.environ["OUTPUT"])
rows: list[tuple[object, ...]] = []

with projects_path.open(encoding="utf-8", newline="") as handle:
    projects = list(csv.DictReader(handle, delimiter="\t"))

for project in projects:
    project_id = project["project_id"]
    try:
        result = json.loads((metadata_dir / f"{project_id}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid Commons metadata for {project_id}: {exc}")
    found = 0
    pages = result.get("query", {}).get("pages", [])
    if len(pages) != 1 or pages[0].get("missing"):
        raise SystemExit(f"Commons title missing or ambiguous for {project_id}")
    page = pages[0]
    infos = page.get("videoinfo") or []
    if len(infos) != 1:
        raise SystemExit(f"missing video metadata for {project_id}")
    info = infos[0]
    meta = info.get("extmetadata") or {}
    license_name = html.unescape(str((meta.get("LicenseShortName") or {}).get("value", "")))
    license_url = str((meta.get("LicenseUrl") or {}).get("value", ""))
    if not license_name.startswith(("CC BY ", "CC BY-SA ")):
        raise SystemExit(f"unsupported license for {project_id}: {license_name}")
    for derivative in info.get("derivatives") or []:
        url = str(derivative.get("src", ""))
        mime = str(derivative.get("type", ""))
        width = int(derivative.get("width", 0))
        height = int(derivative.get("height", 0))
        if (not mime.startswith("video/") or not url
                or derivative.get("transcodekey") != "480p.vp9.webm"):
            continue
        rows.append((
            project_id,
            page.get("title", ""),
            derivative.get("transcodekey", ""),
            url,
            width,
            height,
            mime,
            license_name,
            license_url,
            str((meta.get("Artist") or {}).get("value", "")).replace("\t", " ").replace("\n", " "),
        ))
        found += 1
    if not found:
        raise SystemExit(f"no 480p VP9 CC BY/CC BY-SA transcode found for {project_id}")
    print(f"project={project_id} candidates={found}")

with output.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow((
        "project_id", "title", "transcode_key", "url", "width", "height", "mime",
        "license", "license_url", "artist",
    ))
    writer.writerows(sorted(rows))
print(f"wrote {output} candidates={len(rows)}")
PY

echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
