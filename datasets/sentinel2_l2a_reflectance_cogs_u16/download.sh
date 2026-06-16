#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sentinel2_l2a_reflectance_cogs_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
SCENE_LIMIT="${SCENE_LIMIT:-2}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-350000000}"
MAX_DOWNLOAD_BYTES="${MAX_DOWNLOAD_BYTES:-1000000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
STAC_RESPONSE="$DOWNLOAD_DIR/stac_selection.json"

export SCENE_LIMIT PLAN STAC_RESPONSE
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SCENE_LIMIT = int(os.environ["SCENE_LIMIT"])
PLAN = Path(os.environ["PLAN"])
STAC_RESPONSE = Path(os.environ["STAC_RESPONSE"])
SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"

SEARCH_SPECS = [
    {
        "label": "california_sierra_aug2023",
        "bbox": [-120.2, 37.0, -119.1, 38.0],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
    {
        "label": "atacama_aug2023",
        "bbox": [-70.6, -24.2, -69.4, -23.2],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
    {
        "label": "namibia_aug2023",
        "bbox": [14.2, -23.8, 15.2, -22.8],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
]

BANDS = [
    ("blue_10m", {"blue", "B02"}),
    ("rededge1_20m", {"rededge1", "B05"}),
    ("coastal_60m", {"coastal", "B01"}),
]


def apply_curlrc_proxy_fallback() -> None:
    """urllib does not read ~/.curlrc; mirror proxy settings used by curl."""
    if any(os.environ.get(name) for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        return
    curlrc = Path.home() / ".curlrc"
    if not curlrc.exists():
        return
    for raw in curlrc.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("proxy="):
            proxy = line.split("=", 1)[1].strip().strip('"')
            if proxy:
                os.environ["http_proxy"] = proxy
                os.environ["https_proxy"] = proxy
        elif line.startswith("noproxy="):
            no_proxy = line.split("=", 1)[1].strip().strip('"')
            if no_proxy:
                os.environ.setdefault("no_proxy", no_proxy)


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "openzl-public-datasets/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_href(href: str) -> str:
    if href.startswith("s3://sentinel-cogs/"):
        return "https://sentinel-cogs.s3.us-west-2.amazonaws.com/" + href[len("s3://sentinel-cogs/") :]
    if href.startswith("https://sentinel-cogs.s3.us-west-2.amazonaws.com/"):
        return href
    return href


def asset_band_names(asset: dict, key: str) -> set[str]:
    names = {key}
    for band in asset.get("eo:bands", []) or []:
        if isinstance(band, dict):
            for name_key in ("name", "common_name"):
                value = band.get(name_key)
                if isinstance(value, str):
                    names.add(value)
    href = str(asset.get("href", ""))
    stem = Path(href.split("?", 1)[0]).stem
    if stem:
        names.add(stem)
    return names


def find_asset(feature: dict, wanted: set[str]) -> tuple[str, str] | None:
    assets = feature.get("assets", {}) or {}
    for key, asset in assets.items():
        if not isinstance(asset, dict):
            continue
        names = asset_band_names(asset, str(key))
        if names & wanted:
            href = normalize_href(str(asset.get("href", "")))
            if href.startswith("https://sentinel-cogs.s3.us-west-2.amazonaws.com/") and href.lower().endswith(".tif"):
                return str(key), href
    return None


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")


selected: list[dict] = []
search_records: list[dict] = []
seen_scene_ids: set[str] = set()
apply_curlrc_proxy_fallback()
for spec in SEARCH_SPECS:
    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": spec["bbox"],
        "datetime": spec["datetime"],
        "query": {"eo:cloud_cover": {"lt": 10}},
        "sortby": [
            {"field": "properties.eo:cloud_cover", "direction": "asc"},
            {"field": "properties.datetime", "direction": "asc"},
        ],
        "limit": 20,
    }
    try:
        response = post_json(SEARCH_URL, payload)
    except Exception as exc:
        raise SystemExit(f"STAC search failed for {spec['label']} at {SEARCH_URL}: {exc}") from exc
    features = response.get("features", []) or []
    search_records.append({"spec": spec, "feature_count": len(features)})
    for feature in features:
        scene_id = str(feature.get("id", ""))
        if not scene_id or scene_id in seen_scene_ids:
            continue
        band_rows = []
        for band_label, wanted in BANDS:
            found = find_asset(feature, wanted)
            if not found:
                band_rows = []
                break
            asset_key, href = found
            name = f"{len(selected) + 1:02d}_{safe_name(scene_id)}_{band_label}.tif"
            band_rows.append(
                {
                    "local_name": name,
                    "url": href,
                    "scene_id": scene_id,
                    "band_label": band_label,
                    "asset_key": asset_key,
                    "search_label": spec["label"],
                    "datetime": feature.get("properties", {}).get("datetime", ""),
                    "cloud_cover": feature.get("properties", {}).get("eo:cloud_cover", None),
                }
            )
        if band_rows:
            selected.extend(band_rows)
            seen_scene_ids.add(scene_id)
            break
    if len(seen_scene_ids) >= SCENE_LIMIT:
        break

if len(seen_scene_ids) < SCENE_LIMIT:
    raise SystemExit(f"selected only {len(seen_scene_ids)} scenes; expected {SCENE_LIMIT}")

STAC_RESPONSE.write_text(
    json.dumps({"searches": search_records, "selected": selected}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with PLAN.open("w", encoding="utf-8") as fh:
    fh.write("local_name\turl\tscene_id\tband_label\tasset_key\tsearch_label\tdatetime\tcloud_cover\n")
    for row in selected:
        fh.write(
            f"{row['local_name']}\t{row['url']}\t{row['scene_id']}\t{row['band_label']}\t"
            f"{row['asset_key']}\t{row['search_label']}\t{row['datetime']}\t{row['cloud_cover']}\n"
        )
print(f"selected_scenes={len(seen_scene_ids)} selected_assets={len(selected)}")
PY

downloaded_total=0
tail -n +2 "$PLAN" | while IFS=$'\t' read -r local_name url scene_id band_label asset_key search_label datetime cloud_cover; do
  [[ -n "$local_name" ]] || continue
  target="$DOWNLOAD_DIR/$local_name"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -o "$target" "$url"
  fi
  size="$(wc -c < "$target")"
  if (( size > MAX_FILE_BYTES )); then
    echo "$target exceeds per-file cap: $size" >&2
    exit 1
  fi
  downloaded_total=$((downloaded_total + size))
  if (( downloaded_total > MAX_DOWNLOAD_BYTES )); then
    echo "downloaded bytes exceed cap: $downloaded_total" >&2
    exit 1
  fi
done

export DOWNLOAD_DIR PLAN
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
records = []
for line in plan.read_text(encoding="utf-8").splitlines()[1:]:
    if not line.strip():
        continue
    local_name, url, scene_id, band_label, asset_key, search_label, datetime, cloud_cover = line.split("\t")
    path = download_dir / local_name
    if not path.exists() or path.stat().st_size < 1024:
        raise SystemExit(f"missing or tiny download: {path}")
    records.append(
        {
            "file": local_name,
            "url": url,
            "source_bytes": path.stat().st_size,
            "scene_id": scene_id,
            "band_label": band_label,
            "asset_key": asset_key,
            "search_label": search_label,
            "datetime": datetime,
            "cloud_cover": cloud_cover,
        }
    )
inventory = {
    "dataset_id": "sentinel2_l2a_reflectance_cogs_u16",
    "record_count": len(records),
    "source_bytes": sum(row["source_bytes"] for row in records),
    "records": records,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=downloaded files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
