#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wikimedia_pageviews_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

SERIES_ID = "wikimedia_daily_pageviews"
series_dir = samples_dir / SERIES_ID

PAGES = [
    ("en.wikipedia", "Main_Page", "en_wikipedia_main_page"),
    ("en.wikipedia", "Python_(programming_language)", "en_wikipedia_python_programming_language"),
    ("en.wikipedia", "New_York_City", "en_wikipedia_new_york_city"),
    ("de.wikipedia", "Berlin", "de_wikipedia_berlin"),
    ("fr.wikipedia", "Paris", "fr_wikipedia_paris"),
    ("es.wikipedia", "Madrid", "es_wikipedia_madrid"),
    ("it.wikipedia", "Roma", "it_wikipedia_roma"),
]

EXPECTED_DATES = []
current = dt.date(2024, 1, 1)
end = dt.date(2024, 12, 31)
while current <= end:
    EXPECTED_DATES.append(current.strftime("%Y%m%d"))
    current += dt.timedelta(days=1)


def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

stats = {"dataset_id": "wikimedia_pageviews_daily", "pages": [], "series": {SERIES_ID: {"files": 0, "values": 0, "bytes": 0}}}
sample_rows = []

for project, article, slug in PAGES:
    raw_path = download_dir / f"{slug}.json"
    if not raw_path.is_file():
        raise RuntimeError(f"missing raw payload: {raw_path}")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != len(EXPECTED_DATES):
        raise RuntimeError(f"{slug}: expected {len(EXPECTED_DATES)} items, got {0 if items is None else len(items)}")
    views = []
    for idx, (item, expected_date) in enumerate(zip(items, EXPECTED_DATES), start=1):
        timestamp = item.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.startswith(expected_date):
            raise RuntimeError(f"{slug}: bad timestamp at position {idx}: {timestamp!r} expected prefix {expected_date}")
        raw_views = item.get("views")
        if not isinstance(raw_views, int) or raw_views < 0:
            raise RuntimeError(f"{slug}: bad views at position {idx}: {raw_views!r}")
        views.append(raw_views)
    out_path = series_dir / f"{slug}_u32_n{len(views):06d}.bin"
    out_path.write_bytes(struct.pack("<" + "I" * len(views), *views))
    sample_rows.append({
        "dataset_id": "wikimedia_pageviews_daily",
        "series_id": SERIES_ID,
        "sample_path": rel_data(out_path),
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": out_path.stat().st_size,
        "value_count": len(views),
    })
    stats["series"][SERIES_ID]["files"] += 1
    stats["series"][SERIES_ID]["values"] += len(views)
    stats["series"][SERIES_ID]["bytes"] += out_path.stat().st_size
    stats["pages"].append({
        "project": project,
        "article": article,
        "slug": slug,
        "source_file": rel_data(raw_path),
        "source_sha256": sha256_file(raw_path),
        "sample_file": rel_data(out_path),
        "sample_sha256": sha256_file(out_path),
        "days": len(views),
        "min_views": min(views),
        "max_views": max(views),
    })

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
