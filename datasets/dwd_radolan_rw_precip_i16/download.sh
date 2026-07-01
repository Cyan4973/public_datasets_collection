#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dwd_radolan_rw_precip_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
BASE_URL="${BASE_URL:-https://opendata.dwd.de/weather/radar/radolan/rw/}"
FILE_LIMIT="${FILE_LIMIT:-192}"
DIRECTORY_HTML="$DOWNLOAD_DIR/directory.html"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

if [[ -n "${LOCAL_DIR:-}" ]]; then
  find "$LOCAL_DIR" -maxdepth 1 -type f -name 'raa01-rw_10000-*-dwd---bin.bz2' -printf '%f\t%p\n' | sort > "$PLAN"
else
  curl -fL --retry 3 --retry-delay 5 -o "$DIRECTORY_HTML" "$BASE_URL"
  export BASE_URL DIRECTORY_HTML PLAN FILE_LIMIT
  python3 - <<'PY'
from __future__ import annotations

import html.parser
import os
import re
from pathlib import Path
from urllib.parse import urljoin

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

base_url = os.environ["BASE_URL"]
directory_html = Path(os.environ["DIRECTORY_HTML"])
plan = Path(os.environ["PLAN"])
limit = int(os.environ["FILE_LIMIT"])
parser = LinkParser()
parser.feed(directory_html.read_text(encoding="utf-8", errors="replace"))
pattern = re.compile(r"^raa01-rw_10000-\d{10}-dwd---bin\.bz2$")
names = sorted({Path(href).name for href in parser.hrefs if pattern.match(Path(href).name)})
if not names:
    raise SystemExit("no timestamped RADOLAN RW files found in directory listing")
selected = names[-limit:]
with plan.open("w", encoding="utf-8") as fh:
    for name in selected:
        fh.write(f"{name}\t{urljoin(base_url, name)}\n")
print(f"selected_files={len(selected)} first={selected[0]} last={selected[-1]}")
PY
fi

downloaded=0
while IFS=$'\t' read -r name source; do
  [[ -n "$name" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]]; then
    echo "using existing file: $target"
  elif [[ -n "${LOCAL_DIR:-}" ]]; then
    cp "$source" "$target"
  else
    curl -fL --retry 3 --retry-delay 5 -o "$target" "$source"
  fi
  downloaded=$((downloaded + 1))
done < "$PLAN"

export DOWNLOAD_DIR PLAN
python3 - <<'PY'
from __future__ import annotations

import bz2
import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
expected_payload = 900 * 900 * 2
records = []
for line in plan.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    name = line.split("\t", 1)[0]
    path = download_dir / name
    raw = bz2.decompress(path.read_bytes())
    try:
        header_end = raw.index(b"\x03") + 1
    except ValueError as exc:
        raise SystemExit(f"{name}: missing RADOLAN header ETX") from exc
    payload_len = len(raw) - header_end
    if payload_len != expected_payload:
        raise SystemExit(f"{name}: unexpected payload length {payload_len}")
    records.append({"file": name, "source_bytes": path.stat().st_size, "header_bytes": header_end, "payload_bytes": payload_len})
if len(records) < 24:
    raise SystemExit(f"too few valid RADOLAN RW files: {len(records)}")
(download_dir / "download_inventory.json").write_text(json.dumps({"records": records, "record_count": len(records)}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} payload_bytes={sum(row['payload_bytes'] for row in records)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
