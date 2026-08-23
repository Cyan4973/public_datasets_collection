#!/usr/bin/env bash
# Resolve, acquire, and preflight eight official Poly Haven roughness maps.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_material_roughness_u8"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
METADATA_DIR="$DOWNLOAD_DIR/metadata"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PLAN="$DISCOVERY_DIR/selection.tsv"
LICENSE_PAGE="$METADATA_DIR/polyhaven_license.html"
PINNED="$RECIPE_DIR/sources.tsv"

mkdir -p "$DOWNLOAD_DIR" "$METADATA_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch() {
  local target="$1" url="$2" max_bytes="$3"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse $(basename "$target") bytes=$(stat -c %s "$target")"
    return
  fi
  rm -f "$target.part"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 900 --max-filesize "$max_bytes" --user-agent "openzl-public-datasets/1.0" \
    --output "$target.part" "$url"
  [[ -s "$target.part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$target.part" "$target"
}

fetch "$LICENSE_PAGE" "https://polyhaven.com/license" 5000000
while IFS= read -r asset; do
  [[ -n "$asset" ]] || continue
  fetch "$METADATA_DIR/${asset}_files.json" "https://api.polyhaven.com/files/$asset" 5000000
done < "$RECIPE_DIR/assets.txt"

ASSETS="$RECIPE_DIR/assets.txt" METADATA_DIR="$METADATA_DIR" LICENSE_PAGE="$LICENSE_PAGE" PINNED="$PINNED" PLAN="$PLAN" python3 - <<'PY'
import csv
import json
import os
from pathlib import Path
from urllib.parse import urlparse

license_text = Path(os.environ["LICENSE_PAGE"]).read_text(encoding="utf-8", errors="replace").lower()
required = ("our assets are all licensed as", "cc0", "commercial work")
if not all(term in license_text for term in required):
    raise SystemExit("official Poly Haven license page lacks expected CC0/commercial-use statements")

def candidates(node, trail=()):
    found = []
    if isinstance(node, dict):
        if {"url", "size", "md5"} <= set(node):
            found.append((trail, node))
        for key, value in node.items():
            found.extend(candidates(value, trail + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(candidates(value, trail + (str(index),)))
    return found

assets = [line.strip() for line in Path(os.environ["ASSETS"]).read_text().splitlines() if line.strip()]
rows = []
for asset in assets:
    path = Path(os.environ["METADATA_DIR"]) / f"{asset}_files.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid Poly Haven metadata for {asset}: {exc}")
    matches = []
    for trail, item in candidates(metadata):
        url = str(item.get("url", ""))
        filename = Path(urlparse(url).path).name
        lowered = "/".join(trail).lower() + "/" + filename.lower()
        if "rough" in lowered and "1k" in lowered and filename.lower().endswith(('.jpg', '.jpeg')):
            matches.append((trail, item, filename))
    unique = {(str(item["url"]), int(item["size"]), str(item["md5"]), filename) for _, item, filename in matches}
    if len(unique) != 1:
        raise SystemExit(f"expected one 1K roughness JPEG for {asset}, found {sorted(unique)}")
    url, size, md5, filename = unique.pop()
    if not url.startswith("https://dl.polyhaven.org/") or size <= 0 or len(md5) != 32:
        raise SystemExit(f"invalid official roughness object metadata for {asset}")
    rows.append((asset, filename, size, md5, url))
with Path(os.environ["PINNED"]).open(encoding="utf-8", newline="") as handle:
    pinned = [
        (row["asset_id"], row["filename"], int(row["bytes"]), row["md5"], row["url"])
        for row in csv.DictReader(handle, delimiter="\t")
    ]
if rows != pinned:
    raise SystemExit("live Poly Haven metadata differs from the tracked sources.tsv inventory")
with Path(os.environ["PLAN"]).open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(("asset_id", "filename", "bytes", "md5", "url"))
    writer.writerows(rows)
print(f"selection=ok assets={len(rows)}")
for row in rows:
    print(f"select asset={row[0]} file={row[1]} bytes={row[2]}")
PY

while IFS=$'\t' read -r asset filename expected_bytes expected_md5 url; do
  [[ "$asset" == "asset_id" ]] && continue
  target="$DOWNLOAD_DIR/$filename"
  if [[ -f "$target" ]] \
      && [[ "$(stat -c %s "$target")" == "$expected_bytes" ]] \
      && [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]] \
      && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "verified cached $filename"
  else
    fetch "$target" "$url" 20000000
  fi
  [[ "$(stat -c %s "$target")" == "$expected_bytes" ]] || { echo "size mismatch: $filename" >&2; exit 1; }
  [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]] || { echo "MD5 mismatch: $filename" >&2; exit 1; }
done < "$PLAN"

python3 "$RECIPE_DIR/scripts/roughness_jpeg.py" inspect \
  --plan "$PLAN" --download-dir "$DOWNLOAD_DIR" \
  --report "$DISCOVERY_DIR/source_profile.json"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
