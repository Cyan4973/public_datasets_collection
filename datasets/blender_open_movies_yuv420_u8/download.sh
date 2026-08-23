#!/usr/bin/env bash
# Download and preflight three selected Wikimedia Commons video transcodes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="blender_open_movies_yuv420_u8"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"

mkdir -p "$DOWNLOAD_DIR" "$DISCOVERY_DIR/ffprobe" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

command -v ffprobe >/dev/null || { echo "ffprobe is required" >&2; exit 1; }

tail -n +2 "$SOURCES" | while IFS=$'\t' read -r project_id title url local_file expected_bytes expected_sha256 width height frame_rate duration_seconds license license_url attribution; do
  test -n "$project_id" || continue
  target="$DOWNLOAD_DIR/$local_file"
  if [[ -s "$target" \
      && "$(stat -c %s "$target")" == "$expected_bytes" \
      && "$(sha256sum "$target" | awk '{print $1}')" == "$expected_sha256" \
      && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse project=$project_id bytes=$(stat -c %s "$target")"
  else
    rm -f "$target.part"
    echo "fetch project=$project_id url=$url"
    curl --globoff --fail-with-body --silent --show-error --location \
      --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
      --max-time 3600 --max-filesize 350000000 \
      --user-agent "openzl-public-datasets/1.0" \
      --output "$target.part" "$url"
    test -s "$target.part" || { echo "empty video: $project_id" >&2; exit 1; }
    mv "$target.part" "$target"
  fi
  [[ "$(stat -c %s "$target")" == "$expected_bytes" ]] || { echo "size mismatch: $project_id" >&2; exit 1; }
  [[ "$(sha256sum "$target" | awk '{print $1}')" == "$expected_sha256" ]] || { echo "SHA-256 mismatch: $project_id" >&2; exit 1; }
  ffprobe -v error -show_streams -show_format -of json "$target" \
    > "$DISCOVERY_DIR/ffprobe/$project_id.json"
done

SOURCES="$SOURCES" DOWNLOAD_DIR="$DOWNLOAD_DIR" FFPROBE_DIR="$DISCOVERY_DIR/ffprobe" OUTPUT="$DISCOVERY_DIR/downloaded_sources.tsv" python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


sources_path = Path(os.environ["SOURCES"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
ffprobe_dir = Path(os.environ["FFPROBE_DIR"])
output = Path(os.environ["OUTPUT"])
reports = []

with sources_path.open(encoding="utf-8", newline="") as handle:
    sources = list(csv.DictReader(handle, delimiter="\t"))

for source in sources:
    project_id = source["project_id"]
    path = download_dir / source["local_file"]
    if not path.is_file() or path.stat().st_size <= 0:
        raise SystemExit(f"missing video: {path}")
    probe = json.loads((ffprobe_dir / f"{project_id}.json").read_text(encoding="utf-8"))
    videos = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
    if len(videos) != 1:
        raise SystemExit(f"expected one video stream for {project_id}, got {len(videos)}")
    video = videos[0]
    actual = (
        video.get("codec_name"), video.get("pix_fmt"),
        int(video.get("width", 0)), int(video.get("height", 0)),
    )
    expected = ("vp9", "yuv420p", int(source["width"]), int(source["height"]))
    if actual != expected:
        raise SystemExit(f"unexpected video format for {project_id}: {actual} != {expected}")
    duration = float(probe.get("format", {}).get("duration", 0))
    if video.get("avg_frame_rate") != source["frame_rate"]:
        raise SystemExit(f"frame-rate mismatch for {project_id}: {video.get('avg_frame_rate')}")
    if f"{duration:.6f}" != source["duration_seconds"]:
        raise SystemExit(f"duration mismatch for {project_id}: {duration}s")
    if path.stat().st_size != int(source["bytes"]) or sha256(path) != source["sha256"]:
        raise SystemExit(f"pinned identity mismatch for {project_id}")
    reports.append({
        **source,
        "codec": video["codec_name"],
        "pixel_format": video["pix_fmt"],
    })

with output.open("w", encoding="utf-8", newline="") as handle:
    fields = [
        "project_id", "title", "url", "local_file", "bytes", "sha256",
        "width", "height", "frame_rate", "duration_seconds", "license",
        "license_url", "attribution", "codec", "pixel_format",
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(reports)
for row in reports:
    print(
        f"verified project={row['project_id']} bytes={row['bytes']} "
        f"shape={row['width']}x{row['height']} pix_fmt={row['pixel_format']} "
        f"fps={row['frame_rate']} duration={row['duration_seconds']}"
    )
print(f"verified videos={len(reports)} bytes={sum(int(row['bytes']) for row in reports)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
