#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="anilist_media"
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
MIN_YEAR_RECORDS="${ANILIST_MIN_YEAR_RECORDS:-1000}"
BIN_YEARS="${ANILIST_BIN_YEARS:-3}"   # AniList has ~400-999 anime/year, so bin years to clear the floor
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_YEAR_RECORDS BIN_YEARS
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
pages_dir = download_dir / "pages"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_year = int(os.environ["MIN_YEAR_RECORDS"])
bin_years = int(os.environ["BIN_YEARS"])

DATASET_ID = "anilist_media"
# family -> (json field, numeric_kind, bit_width, struct code, lo, hi)
FAMILIES = {
    "anilist_average_score_u8": ("averageScore", "uint", 8,  "B", 0, 100),
    "anilist_popularity_u32":   ("popularity",   "uint", 32, "I", 0, 0xFFFFFFFF),
    "anilist_favourites_u32":   ("favourites",   "uint", 32, "I", 0, 0xFFFFFFFF),
    "anilist_episodes_u16":     ("episodes",     "uint", 16, "H", 0, 0xFFFF),
    "anilist_duration_u16":     ("duration",     "uint", 16, "H", 0, 0xFFFF),
}

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

by_fam_year = {f: defaultdict(list) for f in FAMILIES}
media_total = 0
no_year = 0

for path in sorted(pages_dir.glob("year_*_p*.json")):
    mo = re.match(r"year_(\d{4})_p", path.name)  # shard year from the filename
    if not mo:
        continue
    y = (int(mo.group(1)) // bin_years) * bin_years  # bin into multi-year groups
    try:
        media = json.loads(path.read_text(encoding="utf-8"))["data"]["Page"]["media"]
    except Exception:
        continue
    for m in media:
        media_total += 1
        for fam, (field, _k, _b, _c, lo, hi) in FAMILIES.items():
            v = m.get(field)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            iv = int(round(v))
            if lo <= iv <= hi:
                by_fam_year[fam][y].append(iv)

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
fam_summary = {}
for fam, (field, kind, bits, code, _lo, _hi) in FAMILIES.items():
    years = by_fam_year[fam]
    qualifying = sorted(y for y, vals in years.items()
                        if len(vals) >= min_year and len(set(vals)) > 1)
    if len(qualifying) < 5:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for y in qualifying:
        vals = years[y]
        out = samples_dir / fam / f"{fam}_y{y}_n{len(vals):06d}.bin"
        out.write_bytes(struct.pack("<" + code * len(vals), *vals))
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "year_bin": y,
            "natural_record_kind": "anilist_media",
        })
    fam_summary[fam] = len(qualifying)

if len(fam_summary) < 2:
    raise SystemExit(f"only {len(fam_summary)} families qualified: {fam_summary}")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_summary,
    "samples": len(index_rows),
    "media_total": media_total,
    "media_without_year": no_year,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_summary} samples={len(index_rows)} media={media_total} "
    f"no_year={no_year} primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
