#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_themis_ir_mosaic_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
FILE_LIMIT="${FILE_LIMIT:-3}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-750000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$PAGES_DIR"

cat > "$PLAN.pages" <<'EOF'
arabia_night_ir_page	https://astrogeology.usgs.gov/search/map/themis_night_ir_controlled_mosaic_arabia_000n_000e_100_mpp
diacria_night_ir_page	https://astrogeology.usgs.gov/search/map/themis_night_ir_controlled_mosaic_diacria_30n_180e_100_mpp
casius_day_ir_page	https://astrogeology.usgs.gov/search/map/themis_day_ir_controlled_mosaic_casius_30n_060e_100_mpp
EOF

while IFS=$'\t' read -r name url; do
  [[ -n "$name" ]] || continue
  target="$PAGES_DIR/${name}.html"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 -o "$target" "$url"
  fi
done < "$PLAN.pages"

export PLAN PAGES_DIR FILE_LIMIT
python3 - <<'PY'
from __future__ import annotations

import html.parser
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def safe_name(url: str, index: int) -> str:
    name = Path(urlparse(url).path).name or f"resource_{index:03d}.dat"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or f"resource_{index:03d}.dat"


pages_dir = Path(os.environ["PAGES_DIR"])
plan = Path(os.environ["PLAN"])
limit = int(os.environ["FILE_LIMIT"])
suffixes = (".cub", ".img", ".lbl", ".tar", ".tar.gz", ".tgz", ".tif", ".tiff", ".zip")
urls: list[str] = []
for line in (plan.parent / "download_plan.tsv.pages").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    name, page_url = line.split("\t")
    parser = LinkParser()
    parser.feed((pages_dir / f"{name}.html").read_text(encoding="utf-8", errors="replace"))
    for href in parser.hrefs:
        url = urljoin(page_url, href)
        path = urlparse(url).path.lower()
        if path.endswith(suffixes):
            urls.append(url)

urls = sorted(set(urls))[:limit]
if not urls:
    raise SystemExit("no direct THEMIS data-file links found on selected product pages")
with plan.open("w", encoding="utf-8") as fh:
    for index, url in enumerate(urls, start=1):
        fh.write(f"{safe_name(url, index)}\t{url}\n")
print(f"selected_direct_links={len(urls)}")
PY

while IFS=$'\t' read -r name url; do
  [[ -n "$name" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" -o "$target" "$url"
  fi
done < "$PLAN"

export DOWNLOAD_DIR PLAN MAX_FILE_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
records = []
for index, line in enumerate(plan.read_text(encoding="utf-8").splitlines(), start=1):
    if not line.strip():
        continue
    name, url = line.split("\t")
    path = download_dir / name
    size = path.stat().st_size
    if size < 10_240:
        raise SystemExit(f"{path.name}: too small to be useful: {size}")
    if size > max_file_bytes:
        raise SystemExit(f"{path.name}: exceeds per-file cap: {size}")
    records.append({"file": path.name, "logical_name": name, "url": url, "source_bytes": size})
inventory = {
    "dataset_id": "nasa_pds_themis_ir_mosaic_i16",
    "record_count": len(records),
    "source_bytes": sum(row["source_bytes"] for row in records),
    "records": records,
}
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
