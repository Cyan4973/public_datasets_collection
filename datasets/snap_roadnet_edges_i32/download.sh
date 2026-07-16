#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="snap_roadnet_edges_i32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${SNAP_ROADNET_BASE_URL:-https://snap.stanford.edu/data}"
MAX_TOTAL_BYTES="${SNAP_ROADNET_MAX_TOTAL_BYTES:-200000000}"
HARD_MAX_TOTAL_BYTES=1000000000
MAX_FILE_BYTES="${SNAP_ROADNET_MAX_FILE_BYTES:-100000000}"
MIN_CA_EDGES="${SNAP_ROADNET_MIN_CA_EDGES:-2500000}"
MIN_PA_EDGES="${SNAP_ROADNET_MIN_PA_EDGES:-1400000}"
MIN_TX_EDGES="${SNAP_ROADNET_MIN_TX_EDGES:-1800000}"

if (( MAX_TOTAL_BYTES > HARD_MAX_TOTAL_BYTES )); then
  echo "requested max total bytes $MAX_TOTAL_BYTES exceeds hard cap $HARD_MAX_TOTAL_BYTES; clamping"
  MAX_TOTAL_BYTES="$HARD_MAX_TOTAL_BYTES"
fi

PLAN="$DOWNLOAD_DIR/download_plan.tsv"
{
  printf 'resource_id\turl\tfile\tmin_edges\n'
  printf 'roadnet_ca\t%s/roadNet-CA.txt.gz\troadNet-CA.txt.gz\t%s\n' "$BASE_URL" "$MIN_CA_EDGES"
  printf 'roadnet_pa\t%s/roadNet-PA.txt.gz\troadNet-PA.txt.gz\t%s\n' "$BASE_URL" "$MIN_PA_EDGES"
  printf 'roadnet_tx\t%s/roadNet-TX.txt.gz\troadNet-TX.txt.gz\t%s\n' "$BASE_URL" "$MIN_TX_EDGES"
} > "$PLAN"

fetch_one() {
  local url="$1"
  local target="$2"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit path=$target"
  else
    echo "fetch url=$url"
    curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
      -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
      -o "$target.tmp" "$url"
    mv "$target.tmp" "$target"
  fi
}

fetch_one "$BASE_URL/roadNet-CA.txt.gz" "$DOWNLOAD_DIR/roadNet-CA.txt.gz"
fetch_one "$BASE_URL/roadNet-PA.txt.gz" "$DOWNLOAD_DIR/roadNet-PA.txt.gz"
fetch_one "$BASE_URL/roadNet-TX.txt.gz" "$DOWNLOAD_DIR/roadNet-TX.txt.gz"

export DOWNLOAD_DIR BASE_URL MAX_TOTAL_BYTES
export MIN_CA_EDGES MIN_PA_EDGES MIN_TX_EDGES
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

SPECS = [
    ("CA", "roadNet-CA.txt.gz", int(os.environ["MIN_CA_EDGES"])),
    ("PA", "roadNet-PA.txt.gz", int(os.environ["MIN_PA_EDGES"])),
    ("TX", "roadNet-TX.txt.gz", int(os.environ["MIN_TX_EDGES"])),
]
MAX_I32 = 2_147_483_647

download_dir = Path(os.environ["DOWNLOAD_DIR"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
resources = []
total_bytes = 0
for state, filename, min_edges in SPECS:
    path = download_dir / filename
    if not path.is_file():
        raise SystemExit(f"missing download: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise SystemExit(f"empty download: {path}")
    total_bytes += size
    if total_bytes > max_total_bytes:
        raise SystemExit(f"download bytes exceed cap: {total_bytes} > {max_total_bytes}")
    edges = 0
    comments = 0
    max_node = -1
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                comments += 1
                continue
            parts = line.split()
            if len(parts) != 2:
                raise SystemExit(f"bad edge width in {filename}: {line[:80]}")
            try:
                src = int(parts[0])
                dst = int(parts[1])
            except ValueError:
                raise SystemExit(f"bad edge integer in {filename}: {line[:80]}") from None
            if src < 0 or dst < 0 or src > MAX_I32 or dst > MAX_I32:
                raise SystemExit(f"edge endpoint out of int32 range in {filename}: {line[:80]}")
            if src == dst:
                raise SystemExit(f"self-loop rejected in {filename}: {line[:80]}")
            max_node = max(max_node, src, dst)
            edges += 1
    if edges < min_edges:
        raise SystemExit(f"too few edges for {state}: {edges} < {min_edges}")
    resources.append({
        "state": state,
        "file": filename,
        "url": f"{os.environ['BASE_URL']}/{filename}",
        "bytes": size,
        "edges": edges,
        "comments": comments,
        "max_node_id": max_node,
    })

inventory = {
    "dataset_id": "snap_roadnet_edges_i32",
    "total_download_bytes": total_bytes,
    "max_total_bytes": max_total_bytes,
    "resources": resources,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    "semantic_validation=ok "
    + " ".join(f"{item['state'].lower()}_edges={item['edges']}" for item in resources)
    + f" total_download_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
