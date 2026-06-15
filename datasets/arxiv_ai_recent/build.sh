#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="arxiv_ai_recent"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations
import calendar, json, os, shutil, struct, xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

root = ET.parse(download_dir / "arxiv_ai_recent.xml").getroot()
entries = [e for e in root.iter() if e.tag.endswith("entry")]
vals = {
    "arxiv_ai_published_at": [],
    "arxiv_ai_updated_at": [],
    "arxiv_ai_author_count": [],
    "arxiv_ai_category_count": [],
    "arxiv_ai_title_length": [],
    "arxiv_ai_title_word_count": [],
    "arxiv_ai_summary_length": [],
    "arxiv_ai_comment_length": [],
    "arxiv_ai_primary_category_length": [],
}
skipped = 0

for sid in vals:
    d = samples_dir / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

def text(elem, name):
    for c in elem:
        if c.tag.endswith(name):
            return (c.text or "").strip()
    return ""

def primary_category_term(elem):
    for c in elem:
        if c.tag.endswith("primary_category"):
            return (c.attrib.get("term") or "").strip()
    return ""

def ts(s: str) -> int:
    return calendar.timegm(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").utctimetuple())

for e in entries:
    try:
        title = text(e, "title")
        summary = text(e, "summary")
        comment = text(e, "comment")
        primary = primary_category_term(e)
        entry_id = text(e, "id")
        vals["arxiv_ai_published_at"].append(ts(text(e, "published")))
        vals["arxiv_ai_updated_at"].append(ts(text(e, "updated")))
        vals["arxiv_ai_author_count"].append(sum(1 for c in e if c.tag.endswith("author")))
        vals["arxiv_ai_category_count"].append(sum(1 for c in e if c.tag.endswith("category")))
        vals["arxiv_ai_title_length"].append(len(title))
        vals["arxiv_ai_title_word_count"].append(len([w for w in title.split() if w]))
        vals["arxiv_ai_summary_length"].append(len(summary))
        vals["arxiv_ai_comment_length"].append(len(comment))
        vals["arxiv_ai_primary_category_length"].append(len(primary))
    except Exception:
        skipped += 1

meta = {
    "arxiv_ai_published_at": ("uint", 32, "I"),
    "arxiv_ai_updated_at": ("uint", 32, "I"),
    "arxiv_ai_author_count": ("uint", 16, "H"),
    "arxiv_ai_category_count": ("uint", 16, "H"),
    "arxiv_ai_title_length": ("uint", 16, "H"),
    "arxiv_ai_title_word_count": ("uint", 16, "H"),
    "arxiv_ai_summary_length": ("uint", 32, "I"),
    "arxiv_ai_comment_length": ("uint", 16, "H"),
    "arxiv_ai_primary_category_length": ("uint", 8, "B"),
}

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append({
        "dataset_id": "arxiv_ai_recent",
        "series_id": sid,
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": kind,
        "bit_width": bits,
        "endianness": "little",
        "element_size_bytes": bits // 8,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(values),
    })

(filter_dir / "ingest_stats.json").write_text(
    json.dumps({"dataset_id": "arxiv_ai_recent", "rows_total": len(entries), "rows_skipped": skipped}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
