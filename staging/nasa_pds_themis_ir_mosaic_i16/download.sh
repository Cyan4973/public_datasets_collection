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
FILE_LIMIT="${FILE_LIMIT:-4}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-750000000}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
PAGES_DIR="$DOWNLOAD_DIR/pages"
LABELS_DIR="$DOWNLOAD_DIR/labels"
mkdir -p "$PAGES_DIR" "$LABELS_DIR"

cat > "$PLAN.pages" <<'EOF'
arabia_day_ir	https://astrogeology.usgs.gov/search/map/mars_themis_day_ir_controlled_mosaic_arabia_000n_000e_100_mpp
elysium_day_ir	https://astrogeology.usgs.gov/search/map/mars_themis_day_ir_controlled_mosaic_elysium_00n_135e_100_mpp
mare_acidalium_day_ir	https://astrogeology.usgs.gov/search/map/mars_themis_day_ir_controlled_mosaic_mare_acidalium_30n_300e_100_mpp
coprates_day_ir	https://astrogeology.usgs.gov/search/map/mars_themis_day_ir_controlled_mosaic_coprates_30s_270e_100_mpp
iapygia_night_ir	https://astrogeology.usgs.gov/search/map/mars_themis_night_ir_controlled_mosaic_iapygia_30s_45e_100_mpp
noachis_night_ir	https://astrogeology.usgs.gov/search/map/mars_themis_night_ir_controlled_mosaic_noachis_65s_000e_100_mpp
EOF

while IFS=$'\t' read -r name url; do
  [[ -n "$name" ]] || continue
  target="$PAGES_DIR/${name}.html"
  if [[ -f "$target" ]]; then
    echo "using existing product page: $target"
  else
    curl -fL --retry 3 --retry-delay 5 -o "$target" "$url"
  fi
done < "$PLAN.pages"

LABEL_PLAN="$DOWNLOAD_DIR/label_plan.tsv"

export PLAN PAGES_DIR LABEL_PLAN FILE_LIMIT
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
        if tag.lower() not in {"a", "link"}:
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def safe_name(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name or name in {"do", "download"}:
        name = fallback
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


plan = Path(os.environ["PLAN"])
pages_dir = Path(os.environ["PAGES_DIR"])
label_plan = Path(os.environ["LABEL_PLAN"])
limit = int(os.environ["FILE_LIMIT"])
page_rows = [
    line.split("\t", 1)
    for line in (plan.parent / "download_plan.tsv.pages").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
rows: list[tuple[str, str, str, str]] = []
for page_name, page_url in page_rows:
    html = (pages_dir / f"{page_name}.html").read_text(encoding="utf-8", errors="replace")
    parser = LinkParser()
    parser.feed(html)
    candidates = list(parser.hrefs)
    candidates.extend(re.findall(r"https?://[^\s\"'<>]+", html))
    urls: list[str] = []
    for href in candidates:
        url = urljoin(page_url, href).rstrip(").,;")
        path = urlparse(url).path.lower()
        if path.endswith((".tif", ".tiff", ".lbl")) and url not in urls:
            urls.append(url)
    image_url = next((url for url in urls if urlparse(url).path.lower().endswith((".tif", ".tiff"))), "")
    label_url = next((url for url in urls if urlparse(url).path.lower().endswith("_pds3.lbl")), "")
    if not label_url:
        label_url = next((url for url in urls if urlparse(url).path.lower().endswith(".lbl")), "")
    if image_url and label_url:
        rows.append((page_name, safe_name(label_url, f"{page_name}.lbl"), label_url, image_url))
if not rows:
    raise SystemExit(
        "no THEMIS image+label pairs found on product pages; "
        "the stale CKAN /do search-result URLs were intentionally removed"
    )
with label_plan.open("w", encoding="utf-8") as fh:
    for row in rows[:limit]:
        fh.write("\t".join(row) + "\n")
print(f"selected_label_prefight_pairs={min(len(rows), limit)}")
PY

while IFS=$'\t' read -r page_name label_name label_url image_url; do
  [[ -n "$page_name" ]] || continue
  target="$LABELS_DIR/$label_name"
  if [[ -f "$target" ]]; then
    echo "using existing label: $target"
  else
    curl -fL --retry 3 --retry-delay 5 --max-filesize 1000000 -o "$target" "$label_url"
  fi
done < "$LABEL_PLAN"

export PLAN LABEL_PLAN LABELS_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse


def value(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    return match.group(1).strip().strip('"') if match else ""


def clean_name(url: str, fallback: str) -> str:
    name = Path(urlparse(url).path).name or fallback
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


plan = Path(os.environ["PLAN"])
label_plan = Path(os.environ["LABEL_PLAN"])
labels_dir = Path(os.environ["LABELS_DIR"])
accepted: list[tuple[str, str]] = []
rejected: list[dict[str, str]] = []
for line in label_plan.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    page_name, label_name, label_url, image_url = line.split("\t")
    label = labels_dir / label_name
    text = label.read_text(encoding="utf-8", errors="replace")
    sample_bits = value(text, "SAMPLE_BITS")
    pixel_type = value(text, "Type")
    if sample_bits.split()[0:1] == ["16"] or pixel_type.lower() in {"signedword", "unsignedword"}:
        accepted.append((clean_name(image_url, f"{page_name}.tif"), image_url))
    else:
        rejected.append(
            {
                "page": page_name,
                "label": label_name,
                "label_url": label_url,
                "image_url": image_url,
                "sample_bits": sample_bits,
                "pixel_type": pixel_type,
                "reason": "not_native_16_bit",
            }
        )
(plan.parent / "download_rejections.json").write_text(
    json.dumps(rejected, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
if not accepted:
    raise SystemExit(
        "no native 16-bit THEMIS mosaic resources found; "
        f"rejected={len(rejected)} details={plan.parent / 'download_rejections.json'}"
    )
with plan.open("w", encoding="utf-8") as fh:
    for name, url in accepted:
        fh.write(f"{name}\t{url}\n")
print(f"selected_16bit_resource_urls={len(accepted)} rejected_non_16bit={len(rejected)}")
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
