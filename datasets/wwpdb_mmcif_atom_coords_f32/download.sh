#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wwpdb_mmcif_atom_coords_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL_BASE="${WWPDB_URL_BASE:-https://files.wwpdb.org/download}"
IDS_CSV="${WWPDB_IDS:-6VXX,7K00,1CRN,4HHB,1AON,6LU7,1TUP,2PTC}"
MAX_FILE_BYTES="${WWPDB_MAX_FILE_BYTES:-50000000}"
MAX_TOTAL_BYTES="${WWPDB_MAX_TOTAL_BYTES:-200000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

export URL_BASE IDS_CSV PLAN DOWNLOAD_DIR WWPDB_URLS_FILE="${WWPDB_URLS_FILE:-}"
python3 - <<'PY'
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from urllib.parse import urlparse

url_base = os.environ["URL_BASE"].rstrip("/")
ids_csv = os.environ["IDS_CSV"]
plan = Path(os.environ["PLAN"])
urls_file = os.environ.get("WWPDB_URLS_FILE")

rows: list[tuple[str, str]] = []
if urls_file:
    for raw in Path(urls_file).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        name = Path(urlparse(raw).path).name
        pdb_id = name.split(".", 1)[0].upper() or re.sub(r"[^A-Za-z0-9]+", "_", raw)
        rows.append((pdb_id, raw))
else:
    for token in ids_csv.split(","):
        pdb_id = token.strip().upper()
        if not pdb_id:
            continue
        if not re.fullmatch(r"[A-Z0-9]{4,12}", pdb_id):
            raise SystemExit(f"invalid PDB id token: {pdb_id}")
        rows.append((pdb_id, f"{url_base}/{pdb_id}.cif.gz"))

deduped: list[tuple[str, str]] = []
seen: set[str] = set()
for pdb_id, url in rows:
    if url not in seen:
        deduped.append((pdb_id, url))
        seen.add(url)
if not deduped:
    raise SystemExit("no mmCIF URLs selected")

with plan.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
    writer.writerow(["pdb_id", "url", "local_path"])
    for pdb_id, url in deduped:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", pdb_id)
        writer.writerow([safe, url, f"cif/{safe}.cif.gz"])
print(f"selected_files={len(deduped)} first={deduped[0][0]} last={deduped[-1][0]}")
PY

total=0
while IFS=$'\t' read -r pdb_id url local_path; do
  [ "$pdb_id" != "pdb_id" ] || continue
  [ -n "$pdb_id" ] || continue
  target="$DOWNLOAD_DIR/$local_path"
  mkdir -p "$(dirname "$target")"
  if [ -s "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    bytes="$(wc -c < "$target" | tr -d ' ')"
    echo "cif cache_hit pdb_id=$pdb_id bytes=$bytes"
  else
    echo "fetch_cif pdb_id=$pdb_id url=$url"
    curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      --speed-limit 1024 --speed-time 180 \
      -A "$UA" -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
    bytes="$(wc -c < "$target" | tr -d ' ')"
  fi
  total=$((total + bytes))
  if [ "$total" -gt "$MAX_TOTAL_BYTES" ]; then
    echo "downloaded bytes exceed cap: $total > $MAX_TOTAL_BYTES" >&2
    exit 1
  fi
done < "$PLAN"

export DATASET_ID DOWNLOAD_DIR PLAN MAX_FILE_BYTES MAX_TOTAL_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
plan = Path(os.environ["PLAN"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
records = []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        path = download_dir / row["local_path"]
        if not path.is_file():
            raise SystemExit(f"missing mmCIF {path}")
        size = path.stat().st_size
        if size > max_file_bytes:
            raise SystemExit(f"{row['pdb_id']}: exceeds per-file cap: {size}")
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as src:
                prefix = src.read(8192)
        except Exception as exc:
            raise SystemExit(f"{row['pdb_id']}: invalid gzip text: {exc}") from exc
        if "_atom_site." not in prefix and "data_" not in prefix:
            raise SystemExit(f"{row['pdb_id']}: does not look like mmCIF")
        records.append({
            "pdb_id": row["pdb_id"],
            "url": row["url"],
            "local_path": row["local_path"],
            "source_bytes": size,
            "sha256": sha256_file(path),
        })
inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "record_count": len(records),
    "source_bytes": sum(r["source_bytes"] for r in records),
    "records": records,
}
if inventory["source_bytes"] > int(os.environ["MAX_TOTAL_BYTES"]):
    raise SystemExit(f"downloaded bytes exceed cap: {inventory['source_bytes']}")
(download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
