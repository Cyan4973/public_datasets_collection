#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="sentinel1_grd_measurement_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

SCENE_LIMIT="${SCENE_LIMIT:-2}"
POLARIZATIONS="${POLARIZATIONS:-HH}"
PRODUCT_TOKEN="${PRODUCT_TOKEN:-GRDM}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-600000000}"
MAX_DOWNLOAD_BYTES="${MAX_DOWNLOAD_BYTES:-1000000000}"
STAC_SEARCH_URL="${STAC_SEARCH_URL:-https://planetarycomputer.microsoft.com/api/stac/v1/search}"
STAC_COLLECTION="${STAC_COLLECTION:-sentinel-1-grd}"
STAC_LIMIT="${STAC_LIMIT:-500}"
SENTINEL1_URLS_FILE="${SENTINEL1_URLS_FILE:-}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
STAC_RESPONSE="$DOWNLOAD_DIR/stac_selection.json"

export SCENE_LIMIT POLARIZATIONS PRODUCT_TOKEN PLAN STAC_RESPONSE STAC_SEARCH_URL STAC_COLLECTION STAC_LIMIT SENTINEL1_URLS_FILE
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

SCENE_LIMIT = int(os.environ["SCENE_LIMIT"])
POLARIZATIONS = [p.strip().upper() for p in re.split(r"[,\s]+", os.environ["POLARIZATIONS"]) if p.strip()]
PRODUCT_TOKEN = os.environ["PRODUCT_TOKEN"].strip().upper()
PLAN = Path(os.environ["PLAN"])
STAC_RESPONSE = Path(os.environ["STAC_RESPONSE"])
STAC_SEARCH_URL = os.environ["STAC_SEARCH_URL"]
STAC_COLLECTION = os.environ["STAC_COLLECTION"]
STAC_LIMIT = int(os.environ["STAC_LIMIT"])
URLS_FILE = os.environ.get("SENTINEL1_URLS_FILE", "")

VALID_POLARIZATIONS = {"VV", "VH", "HH", "HV"}
if not POLARIZATIONS or any(p not in VALID_POLARIZATIONS for p in POLARIZATIONS):
    raise SystemExit(f"POLARIZATIONS must be drawn from {sorted(VALID_POLARIZATIONS)}")

SEARCH_SPECS = [
    {
        "label": "svalbard_aug2023",
        "bbox": [10.0, 77.0, 24.0, 80.5],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
    {
        "label": "greenland_east_aug2023",
        "bbox": [-35.0, 68.0, -18.0, 74.0],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
    {
        "label": "barents_sea_sep2023",
        "bbox": [28.0, 72.0, 48.0, 78.0],
        "datetime": "2023-09-01T00:00:00Z/2023-09-30T23:59:59Z",
    },
    {
        "label": "bering_sea_sep2023",
        "bbox": [-174.0, 58.0, -160.0, 64.0],
        "datetime": "2023-09-01T00:00:00Z/2023-09-30T23:59:59Z",
    },
    {
        "label": "california_coast_aug2023",
        "bbox": [-123.2, 36.4, -121.2, 38.3],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
    {
        "label": "japan_coast_aug2023",
        "bbox": [139.0, 34.5, 141.2, 36.2],
        "datetime": "2023-08-01T00:00:00Z/2023-08-31T23:59:59Z",
    },
]


def apply_curlrc_proxy_fallback() -> None:
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


def request_json(request: urllib.request.Request) -> dict:
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


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
    return request_json(request)


def sign_planetary_href(href: str) -> str:
    if "blob.core.windows.net" not in href or "?" in href:
        return href
    sign_url = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href=" + urllib.parse.quote(href, safe="")
    request = urllib.request.Request(sign_url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    try:
        signed = request_json(request)
    except Exception:
        return href
    return str(signed.get("href") or href)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")


def infer_polarization(text: str) -> str | None:
    lowered = text.lower()
    for pol in sorted(VALID_POLARIZATIONS):
        if re.search(rf"(^|[^a-z0-9]){pol.lower()}([^a-z0-9]|$)", lowered):
            return pol
    parts = re.split(r"[^a-z0-9]+", lowered)
    for pol in sorted(VALID_POLARIZATIONS):
        if pol.lower() in parts:
            return pol
    return None


def write_plan(rows: list[dict]) -> None:
    with PLAN.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "local_name",
                "url",
                "scene_id",
                "polarization",
                "asset_key",
                "search_label",
                "datetime",
                "platform",
                "source_mode",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def plan_from_exact_file(path: Path) -> list[dict]:
    raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not raw_lines:
        raise SystemExit(f"empty SENTINEL1_URLS_FILE: {path}")
    rows: list[dict] = []
    first = raw_lines[0].split("\t")
    if "url" in first:
        reader = csv.DictReader(raw_lines, delimiter="\t")
        for index, row in enumerate(reader, start=1):
            url = str(row.get("url", "")).strip()
            pol = str(row.get("polarization", "")).strip().upper() or infer_polarization(url)
            if not url or pol not in VALID_POLARIZATIONS:
                raise SystemExit(f"invalid exact URL row {index}: {row}")
            local_name = str(row.get("local_name") or f"{index:04d}_{safe_name(row.get('scene_id') or Path(url.split('?', 1)[0]).stem)}_{pol.lower()}.tif")
            rows.append(
                {
                    "local_name": local_name,
                    "url": url,
                    "scene_id": str(row.get("scene_id") or Path(url.split("?", 1)[0]).stem),
                    "polarization": pol,
                    "asset_key": str(row.get("asset_key") or pol.lower()),
                    "search_label": str(row.get("search_label") or "exact_urls"),
                    "datetime": str(row.get("datetime") or ""),
                    "platform": str(row.get("platform") or ""),
                    "source_mode": "exact_urls_file",
                }
            )
    else:
        for index, url in enumerate(raw_lines, start=1):
            url = url.strip()
            pol = infer_polarization(url)
            if pol not in VALID_POLARIZATIONS:
                raise SystemExit(f"could not infer polarization for URL: {url}")
            stem = safe_name(Path(url.split("?", 1)[0]).stem)
            rows.append(
                {
                    "local_name": f"{index:04d}_{stem}_{pol.lower()}.tif",
                    "url": url,
                    "scene_id": stem,
                    "polarization": pol,
                    "asset_key": pol.lower(),
                    "search_label": "exact_urls",
                    "datetime": "",
                    "platform": "",
                    "source_mode": "exact_urls_file",
                }
            )
    return rows


def asset_matches(asset_key: str, asset: dict, pol: str) -> bool:
    wanted = pol.lower()
    names = {asset_key.lower()}
    title = asset.get("title")
    if isinstance(title, str):
        names.add(title.lower())
    href = str(asset.get("href", ""))
    names.add(Path(href.split("?", 1)[0]).stem.lower())
    roles = asset.get("roles") or []
    if isinstance(roles, list):
        names.update(str(role).lower() for role in roles)
    return any(re.search(rf"(^|[^a-z0-9]){wanted}([^a-z0-9]|$)", name) for name in names)


def plan_from_stac() -> list[dict]:
    selected: list[dict] = []
    search_records: list[dict] = []
    seen_scene_ids: set[str] = set()
    apply_curlrc_proxy_fallback()
    for spec in SEARCH_SPECS:
        payload = {
            "collections": [STAC_COLLECTION],
            "bbox": spec["bbox"],
            "datetime": spec["datetime"],
            "limit": STAC_LIMIT,
        }
        try:
            response = post_json(STAC_SEARCH_URL, payload)
        except Exception as exc:
            raise SystemExit(f"STAC search failed for {spec['label']} at {STAC_SEARCH_URL}: {exc}") from exc
        features = response.get("features", []) or []
        token_matches = 0
        asset_matches_count = 0
        candidate_examples = []
        for feature in features:
            scene_id = str(feature.get("id") or "")
            if not scene_id or scene_id in seen_scene_ids:
                continue
            if len(candidate_examples) < 12:
                candidate_examples.append(scene_id)
            if PRODUCT_TOKEN and PRODUCT_TOKEN not in scene_id.upper():
                continue
            token_matches += 1
            assets = feature.get("assets", {}) or {}
            asset_rows = []
            for pol in POLARIZATIONS:
                found = None
                for key, asset in assets.items():
                    if not isinstance(asset, dict):
                        continue
                    href = str(asset.get("href") or "")
                    media_type = str(asset.get("type") or "").lower()
                    if not href or (".tif" not in href.lower() and "tiff" not in media_type):
                        continue
                    if asset_matches(str(key), asset, pol):
                        found = (str(key), sign_planetary_href(href))
                        break
                if found is None:
                    asset_rows = []
                    break
                asset_key, href = found
                asset_rows.append(
                    {
                        "local_name": f"{len(selected) + len(asset_rows) + 1:04d}_{safe_name(scene_id)}_{pol.lower()}.tif",
                        "url": href,
                        "scene_id": scene_id,
                        "polarization": pol,
                        "asset_key": asset_key,
                        "search_label": spec["label"],
                        "datetime": feature.get("properties", {}).get("datetime", ""),
                        "platform": feature.get("properties", {}).get("platform", ""),
                        "source_mode": "planetary_computer_stac",
                    }
                )
            if asset_rows:
                asset_matches_count += 1
                selected.extend(asset_rows)
                seen_scene_ids.add(scene_id)
                if len(seen_scene_ids) >= SCENE_LIMIT:
                    break
        search_records.append(
            {
                "spec": spec,
                "feature_count": len(features),
                "product_token_matches": token_matches,
                "asset_complete_matches": asset_matches_count,
                "candidate_examples": candidate_examples,
            }
        )
        if len(seen_scene_ids) >= SCENE_LIMIT:
            break

    STAC_RESPONSE.write_text(
        json.dumps(
            {
                "collection": STAC_COLLECTION,
                "stac_limit": STAC_LIMIT,
                "product_token": PRODUCT_TOKEN,
                "polarizations": POLARIZATIONS,
                "searches": search_records,
                "selected": selected,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if len({row["scene_id"] for row in selected}) < SCENE_LIMIT:
        raise SystemExit(f"selected only {len({row['scene_id'] for row in selected})} scenes; expected {SCENE_LIMIT}")
    return selected


if URLS_FILE:
    rows = plan_from_exact_file(Path(URLS_FILE))
else:
    rows = plan_from_stac()

if not rows:
    raise SystemExit("download plan is empty")
write_plan(rows)
print(f"selected_assets={len(rows)} selected_scenes={len({row['scene_id'] for row in rows})} polarizations={','.join(sorted({row['polarization'] for row in rows}))}")
PY

downloaded_total=0
tail -n +2 "$PLAN" | while IFS=$'\t' read -r local_name url scene_id polarization asset_key search_label datetime platform source_mode; do
  [[ -n "$local_name" ]] || continue
  target="$DOWNLOAD_DIR/$local_name"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -o "$target" "$url"
  fi
  size="$(wc -c < "$target")"
  if (( size > MAX_FILE_BYTES )); then
    echo "file exceeds cap: $target size=$size cap=$MAX_FILE_BYTES" >&2
    exit 1
  fi
  magic="$(LC_ALL=C head -c 4 "$target" | od -An -tx1 | tr -d ' \n')"
  if [[ "$magic" != "49492a00" && "$magic" != "4d4d002a" && "$magic" != "49492b00" && "$magic" != "4d4d002b" ]]; then
    echo "download is not a TIFF/BigTIFF file: $target magic=$magic" >&2
    exit 1
  fi
  downloaded_total=$((downloaded_total + size))
  if (( downloaded_total > MAX_DOWNLOAD_BYTES )); then
    echo "aggregate download exceeds cap: total=$downloaded_total cap=$MAX_DOWNLOAD_BYTES" >&2
    exit 1
  fi
  echo "downloaded local_name=$local_name polarization=$polarization bytes=$size scene_id=$scene_id"
done

echo "[$(date -Is)] download done dataset=$DATASET_ID"
