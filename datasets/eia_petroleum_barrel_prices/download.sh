#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_petroleum_barrel_prices"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ -z "${https_proxy:-}${HTTPS_PROXY:-}" && -z "${http_proxy:-}${HTTP_PROXY:-}" ]]; then
  if command -v getent >/dev/null 2>&1 && getent hosts fwdproxy >/dev/null 2>&1; then
    export https_proxy="http://fwdproxy:8080"
    export http_proxy="http://fwdproxy:8080"
    echo "proxy_auto_configured=https_proxy,http_proxy via fwdproxy"
  else
    echo "proxy_auto_configured=none fwdproxy_unresolved"
  fi
else
  echo "proxy_auto_configured=skipped existing_proxy_env=present"
fi

API_ROOT="${EIA_API_ROOT:-https://api.eia.gov/v2}"
API_KEY="${EIA_API_KEY:-DEMO_KEY}"
ROOTS="${EIA_BARREL_PRICE_ROOTS:-petroleum/pri}"
if [[ "${EIA_BARREL_PRICE_DISCOVER:-0}" == "1" ]]; then
  ENDPOINTS="${EIA_BARREL_PRICE_ENDPOINTS:-}"
else
  ENDPOINTS="${EIA_BARREL_PRICE_ENDPOINTS:-petroleum/pri/spt petroleum/pri/fut petroleum/pri/rac}"
fi
FREQUENCIES="${EIA_BARREL_PRICE_FREQUENCIES:-daily weekly monthly}"
PAGE_SIZE="${EIA_BARREL_PRICE_PAGE_SIZE:-5000}"
MAX_ENDPOINTS="${EIA_BARREL_PRICE_MAX_ENDPOINTS:-32}"
MAX_RECORDS_PER_ENDPOINT_FREQ="${EIA_BARREL_PRICE_MAX_RECORDS_PER_ENDPOINT_FREQ:-75000}"
CURL_CONNECT_TIMEOUT="${EIA_BARREL_PRICE_CONNECT_TIMEOUT:-10}"
CURL_MAX_TIME="${EIA_BARREL_PRICE_MAX_TIME:-120}"
CURL_HTTP_RETRIES="${EIA_BARREL_PRICE_HTTP_RETRIES:-2}"
CURL_RETRY_DELAY="${EIA_BARREL_PRICE_RETRY_DELAY:-2}"
UA="${USER_AGENT:-openzl-public-datasets/1.0 (numeric dataset collection)}"

rm -rf "$PAGE_DIR.tmp"
mkdir -p "$PAGE_DIR.tmp"

export API_ROOT API_KEY ROOTS ENDPOINTS FREQUENCIES PAGE_SIZE MAX_ENDPOINTS
export MAX_RECORDS_PER_ENDPOINT_FREQ CURL_CONNECT_TIMEOUT CURL_MAX_TIME
export CURL_HTTP_RETRIES CURL_RETRY_DELAY UA PAGE_DIR_TMP="$PAGE_DIR.tmp" DATASET_ID
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

api_root = os.environ["API_ROOT"].rstrip("/")
api_key = os.environ["API_KEY"]
roots = os.environ["ROOTS"].split()
explicit_endpoints = os.environ["ENDPOINTS"].split()
frequencies = os.environ["FREQUENCIES"].split()
page_size = int(os.environ["PAGE_SIZE"])
max_endpoints = int(os.environ["MAX_ENDPOINTS"])
max_records = int(os.environ["MAX_RECORDS_PER_ENDPOINT_FREQ"])
curl_connect_timeout = int(os.environ["CURL_CONNECT_TIMEOUT"])
curl_max_time = int(os.environ["CURL_MAX_TIME"])
curl_http_retries = int(os.environ["CURL_HTTP_RETRIES"])
curl_retry_delay = int(os.environ["CURL_RETRY_DELAY"])
ua = os.environ["UA"]
page_dir = Path(os.environ["PAGE_DIR_TMP"])
dataset_id = os.environ["DATASET_ID"]

if not 1 <= page_size <= 5000:
    raise SystemExit("EIA_BARREL_PRICE_PAGE_SIZE must be 1..5000")
if curl_connect_timeout <= 0 or curl_max_time <= 0:
    raise SystemExit("EIA_BARREL_PRICE_CONNECT_TIMEOUT and EIA_BARREL_PRICE_MAX_TIME must be positive")
if curl_http_retries < 0 or curl_retry_delay < 0:
    raise SystemExit("EIA_BARREL_PRICE_HTTP_RETRIES and EIA_BARREL_PRICE_RETRY_DELAY must be non-negative")


def slug(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip("/")).strip("_").lower()
    return out or "root"


def normalize_route(route: str) -> str:
    route = route.strip()
    route = route.removeprefix(api_root).strip("/")
    route = route.removeprefix("v2/").strip("/")
    route = route.removesuffix("/data").strip("/")
    return route


def fetch_json(url: str, out: Path) -> tuple[bool, str]:
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    retryable_http = {"408", "500", "502", "503", "504"}
    last_reason = "not_started"
    for attempt in range(curl_http_retries + 1):
        proc = subprocess.run(
            [
                "curl",
                "--globoff",
                "--location",
                "--silent",
                "--show-error",
                "--connect-timeout",
                str(curl_connect_timeout),
                "--max-time",
                str(curl_max_time),
                "-A",
                ua,
                "-o",
                str(tmp),
                "-w",
                "%{http_code}",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        http_code = proc.stdout.strip()[-3:] if proc.stdout.strip() else "000"
        if proc.returncode == 0 and http_code.startswith("2"):
            break
        tmp.unlink(missing_ok=True)
        if http_code == "429":
            return False, "http_429_rate_limited"
        if proc.returncode != 0:
            detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no_stderr"
            last_reason = f"curl_failed:{proc.returncode}:{detail}"
        else:
            last_reason = f"http_{http_code}"
        if attempt < curl_http_retries and (proc.returncode != 0 or http_code in retryable_http):
            print(
                f"curl_retry attempt={attempt + 1}/{curl_http_retries} "
                f"reason={last_reason} delay_seconds={curl_retry_delay}"
            )
            if curl_retry_delay:
                time.sleep(curl_retry_delay)
            continue
        return False, last_reason
    try:
        json.loads(tmp.read_text(encoding="utf-8"))
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return False, f"bad_json:{exc}"
    tmp.replace(out)
    return True, "ok"


def discover() -> list[str]:
    if explicit_endpoints:
        return [normalize_route(r) for r in explicit_endpoints]
    found: list[str] = []
    seen: set[str] = set()
    queue = [normalize_route(r) for r in roots]
    while queue and len(found) < max_endpoints:
        route = queue.pop(0)
        if route in seen:
            continue
        seen.add(route)
        meta_url = f"{api_root}/{route}/?{urlencode({'api_key': api_key})}"
        meta_path = page_dir / "_metadata" / f"{slug(route)}.json"
        ok, reason = fetch_json(meta_url, meta_path)
        if not ok:
            print(f"metadata_skip route={route} reason={reason}")
            found.append(route)
            continue
        obj = json.loads(meta_path.read_text(encoding="utf-8"))
        response = obj.get("response") or {}
        routes = response.get("routes") or []
        child_ids = []
        for child in routes:
            cid = child.get("id") or child.get("route")
            if cid:
                child_ids.append(str(cid).strip("/"))
        if child_ids:
            for cid in child_ids:
                queue.append(normalize_route(f"{route}/{cid}"))
        else:
            found.append(route)
    fallback = [
        "petroleum/pri/spt",
        "petroleum/pri/fut",
        "petroleum/pri/rac",
        "petroleum/pri/refmg",
    ]
    for route in fallback:
        if route not in found:
            found.append(route)
    return found[:max_endpoints]


endpoints = discover()
inventory = {
    "dataset_id": dataset_id,
    "api_root": api_root,
    "endpoints": [],
    "frequencies": frequencies,
    "page_size": page_size,
    "max_records_per_endpoint_frequency": max_records,
}

for route in endpoints:
    for frequency in frequencies:
        endpoint_slug = slug(route)
        freq_dir = page_dir / endpoint_slug / frequency
        rows_seen = 0
        offset = 0
        page_no = 0
        api_total = None
        pages = []
        while rows_seen < max_records:
            params = [
                ("api_key", api_key),
                ("frequency", frequency),
                ("data[0]", "value"),
                ("sort[0][column]", "period"),
                ("sort[0][direction]", "asc"),
                ("offset", str(offset)),
                ("length", str(page_size)),
            ]
            url = f"{api_root}/{route}/data/?{urlencode(params)}"
            page_no += 1
            out = freq_dir / f"page_{page_no:05d}.json"
            print(f"fetch route={route} frequency={frequency} page={page_no} offset={offset}")
            ok, reason = fetch_json(url, out)
            if not ok:
                print(f"frequency_skip route={route} frequency={frequency} reason={reason}")
                break
            obj = json.loads(out.read_text(encoding="utf-8"))
            response = obj.get("response") or {}
            data = response.get("data")
            if not isinstance(data, list):
                print(f"frequency_skip route={route} frequency={frequency} reason=missing_response_data")
                out.unlink(missing_ok=True)
                break
            if api_total is None and response.get("total") is not None:
                api_total = int(response["total"])
            pages.append(
                {
                    "path": out.relative_to(page_dir).as_posix(),
                    "record_count": len(data),
                    "bytes": out.stat().st_size,
                    "url": url,
                }
            )
            rows_seen += len(data)
            print(
                f"page_ok route={route} frequency={frequency} page={page_no} "
                f"records={len(data)} total_seen={rows_seen} api_total={api_total}"
            )
            if not data or len(data) < page_size:
                break
            offset += page_size
            if api_total is not None and offset >= api_total:
                break
        if pages:
            inventory["endpoints"].append(
                {
                    "route": route,
                    "frequency": frequency,
                    "api_total": api_total,
                    "records_downloaded": rows_seen,
                    "pages": pages,
                }
            )

(page_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok endpoint_frequency_count={len(inventory['endpoints'])} "
    f"page_count={sum(len(e['pages']) for e in inventory['endpoints'])}"
)
PY

rm -rf "$PAGE_DIR"
mv "$PAGE_DIR.tmp" "$PAGE_DIR"
cp "$PAGE_DIR/download_inventory.json" "$DOWNLOAD_DIR/download_inventory.json"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
