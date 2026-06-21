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
MIN_DAYS="${WIKI_MIN_DAYS:-365}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_DAYS
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
series_dir = download_dir / "series"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_days = int(os.environ["MIN_DAYS"])

DATASET_ID = "wikimedia_pageviews_daily"
FAMILY = "wikimedia_pageviews_daily_u32"
UINT32_MAX = 0xFFFFFFFF

# Landing/main pages are not content articles: their traffic is driven by default
# homepages, app opens and redirects rather than topical interest, so they belong to a
# different regime of the same quantity. Colon-namespaced main pages (de/fr/es) are
# already excluded during download; these localized titles carry no colon.
MAIN_PAGES = {
    "Main_Page",            # en
    "Заглавная_страница",   # ru
    "メインページ",          # ja
    "Wikipedia:Portada",    # es (defensive; normally colon-filtered)
}

if not series_dir.is_dir():
    raise SystemExit(f"missing series dir: {series_dir}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
fam_dir = samples_dir / FAMILY
fam_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
skipped_short = 0
skipped_const = 0
skipped_bad = 0
skipped_mainpage = 0

for path in sorted(series_dir.glob("*.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        skipped_bad += 1
        continue
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        skipped_bad += 1
        continue

    project = items[0].get("project") or "unknown"
    article = items[0].get("article") or path.stem
    if article in MAIN_PAGES:
        skipped_mainpage += 1
        continue

    views = []
    prev_ts = ""
    ok = True
    for item in items:
        ts = item.get("timestamp")
        v = item.get("views")
        if not isinstance(ts, str) or not isinstance(v, int) or v < 0 or v > UINT32_MAX:
            ok = False
            break
        if ts <= prev_ts:  # strictly increasing daily timestamps
            ok = False
            break
        prev_ts = ts
        views.append(v)
    if not ok:
        skipped_bad += 1
        continue
    if len(views) < min_days:
        skipped_short += 1
        continue
    if len(set(views)) <= 1:
        skipped_const += 1
        continue

    out = fam_dir / f"{path.stem}_n{len(views):06d}.bin"
    out.write_bytes(struct.pack("<" + "I" * len(views), *views))
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": FAMILY,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(views),
        "sample_geometry": "sequence",
        "sample_rank": 1,
        "project": project,
        "article": article,
        "natural_record_kind": "wikipedia_article_daily_views",
    })

if len(index_rows) < 5:
    raise SystemExit(
        f"only {len(index_rows)} usable article series "
        f"(short={skipped_short} const={skipped_const} bad={skipped_bad})"
    )

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": {FAMILY: len(index_rows)},
    "samples": len(index_rows),
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "skipped_short": skipped_short,
    "skipped_const": skipped_const,
    "skipped_bad": skipped_bad,
    "skipped_mainpage": skipped_mainpage,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built family={FAMILY} samples={len(index_rows)} primary_values={primary_values} "
    f"median_days={median} range=[{counts[0]},{counts[-1]}] "
    f"skipped(short={skipped_short},const={skipped_const},bad={skipped_bad},mainpage={skipped_mainpage})"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
