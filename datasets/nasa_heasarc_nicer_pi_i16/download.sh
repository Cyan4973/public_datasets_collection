#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_heasarc_nicer_pi_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$CANDIDATE_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
EXPECTED_FILES=36
EXPECTED_TOTAL_BYTES=205174726

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

SOURCES="$SOURCES" EXPECTED_FILES="$EXPECTED_FILES" EXPECTED_TOTAL_BYTES="$EXPECTED_TOTAL_BYTES" python3 - <<'PY'
import csv
import os
from pathlib import Path
import re

path = Path(os.environ["SOURCES"])
with path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != int(os.environ["EXPECTED_FILES"]):
    raise SystemExit("pinned source count changed")
if sum(int(row["bytes"]) for row in rows) != int(os.environ["EXPECTED_TOTAL_BYTES"]):
    raise SystemExit("pinned aggregate source size changed")
if len({row["obs_id"] for row in rows}) != len(rows):
    raise SystemExit("duplicate pinned observation ID")
for row in rows:
    name = Path(row["filename"])
    if name.name != row["filename"] or not row["obs_id"].isdigit():
        raise SystemExit("unsafe pinned source identity")
    if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
        raise SystemExit("invalid pinned source SHA256")
    if row["url"] != (
        f"https://heasarc.gsfc.nasa.gov/FTP/nicer/data/obs/{row['month']}/"
        f"{row['obs_id']}/xti/event_cl/{row['filename']}"
    ):
        raise SystemExit("pinned source URL does not match archive identity")
print(f"source_inventory=ok files={len(rows)} bytes={sum(int(row['bytes']) for row in rows)}")
PY

while IFS=$'\t' read -r month obs_id filename expected_bytes expected_sha256 url; do
  [[ "$month" == "month" ]] && continue
  target="$DOWNLOAD_DIR/$filename"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit obs_id=$obs_id file=$filename"
  else
    echo "fetch obs_id=$obs_id bytes=$expected_bytes file=$filename"
    curl --fail --location --retry 4 --retry-delay 4 --max-time 3600 \
      --max-filesize 100000000 --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
  actual_bytes="$(wc -c < "$target" | tr -d ' ')"
  [[ "$actual_bytes" == "$expected_bytes" ]] || {
    echo "source size mismatch for $filename: $actual_bytes != $expected_bytes" >&2
    exit 1
  }
  gzip -t "$target"
  actual_sha256="$(sha256sum "$target" | awk '{print $1}')"
  [[ "$actual_sha256" == "$expected_sha256" ]] || {
    echo "source SHA256 mismatch for $filename" >&2
    exit 1
  }
done < "$SOURCES"

export SOURCES DOWNLOAD_DIR
python3 - <<'PY'
import csv
import hashlib
import json
import os
from pathlib import Path

sources = Path(os.environ["SOURCES"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
with sources.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
records = []
for row in rows:
    path = download_dir / row["filename"]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != row["sha256"]:
        raise SystemExit(f"pinned source SHA256 mismatch: {row['filename']}")
    records.append({
        "month": row["month"],
        "obs_id": row["obs_id"],
        "filename": row["filename"],
        "bytes": path.stat().st_size,
        "sha256": row["sha256"],
        "url": row["url"],
    })
payload = {
    "candidate_id": "nasa_heasarc_nicer_pi_i16",
    "files": len(records),
    "source_bytes": sum(record["bytes"] for record in records),
    "records": records,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"downloaded_files={payload['files']} source_bytes={payload['source_bytes']}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
