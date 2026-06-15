#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="smithsonian_openaccess_gltf_indices_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1

URL_LIST="${SMITHSONIAN_GLTF_URLS_FILE:-$SCRIPT_DIR/urls.txt}"
DISCOVERED_URLS="$FILTER_DIR/discovered_gltf_urls.txt"

if [ ! -s "$URL_LIST" ]; then
  URL_LIST="$DISCOVERED_URLS"
  python3 - <<'PY' "$URL_LIST"
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

out = Path(sys.argv[1])
if not any(os.environ.get(name) for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
    curlrc = Path.home() / ".curlrc"
    if curlrc.exists():
        for raw in curlrc.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line.startswith("proxy="):
                proxy = line.split("=", 1)[1].strip().strip('"')
                if proxy:
                    os.environ["http_proxy"] = proxy
                    os.environ["https_proxy"] = proxy
            elif line.startswith("noproxy="):
                no_proxy = line.split("=", 1)[1].strip().strip('"')
                if no_proxy:
                    os.environ.setdefault("no_proxy", no_proxy)
api_key = os.environ.get("SMITHSONIAN_API_KEY", "DEMO_KEY")
query = os.environ.get("SMITHSONIAN_QUERY", "3d")
rows = int(os.environ.get("SMITHSONIAN_API_ROWS", "100"))
max_pages = int(os.environ.get("SMITHSONIAN_API_MAX_PAGES", "20"))
min_urls = int(os.environ.get("SMITHSONIAN_MIN_URLS", "1"))
allow_zip = os.environ.get("SMITHSONIAN_ALLOW_ZIP", "0") == "1"
base = "https://api.si.edu/openaccess/api/v1.0/search"
suffix_pattern = r"(?:\.glb|\.zip)" if allow_zip else r"\.glb"
url_re = re.compile(r"https?://[^\"'\s<>]+" + suffix_pattern + r"(?:\?[^\"'\s<>]*)?", re.IGNORECASE)

def walk(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)
    elif isinstance(value, str):
        yield value

def is_cc0(row: dict) -> bool:
    dnr = row.get("content", {}).get("descriptiveNonRepeating", {})
    usage = dnr.get("metadata_usage") or {}
    return str(usage.get("access", "")).upper() == "CC0"

urls: list[str] = []
seen: set[str] = set()
for page in range(max_pages):
    params = {
        "api_key": api_key,
        "q": query,
        "rows": str(rows),
        "start": str(page * rows),
    }
    url = base + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        obj = json.loads(response.read().decode("utf-8"))
    rows_obj = obj.get("response", {}).get("rows", [])
    print(f"api_page={page} rows={len(rows_obj)}")
    if not rows_obj:
        break
    for row in rows_obj:
        if not is_cc0(row):
            continue
        for text in walk(row):
            for match in url_re.findall(text):
                cleaned = match.rstrip(".,;)")
                lower = cleaned.lower()
                if "draco" in lower:
                    continue
                if not allow_zip and not lower.split("?", 1)[0].endswith(".glb"):
                    continue
                if cleaned not in seen:
                    urls.append(cleaned)
                    seen.add(cleaned)
    if len(urls) >= min_urls:
        break
    time.sleep(float(os.environ.get("SMITHSONIAN_API_DELAY_SECONDS", "0.2")))

if not urls:
    raise SystemExit(
        "no direct .glb/.zip URLs discovered from the Smithsonian API; "
        "provide SMITHSONIAN_GLTF_URLS_FILE with exact CC0 model URLs"
    )
out.write_text("\n".join(urls) + "\n", encoding="utf-8")
print(f"discovered_urls={len(urls)} path={out}")
PY
fi

python3 "$REPO_ROOT/tools/bounded_url_download.py" \
  --dataset-id "$DATASET_ID" \
  --download-dir "$DOWNLOAD_DIR" \
  --url-list "$URL_LIST" \
  --suffix .glb \
  --max-files "${MAX_FILES:-24}" \
  --max-total-bytes "${MAX_DOWNLOAD_BYTES:-1000000000}"
