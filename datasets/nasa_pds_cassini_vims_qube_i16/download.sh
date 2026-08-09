#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_pds_cassini_vims_qube_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$CANDIDATE_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

export SOURCES PLAN
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import re


BASE_URLS = {
    1: "https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/covims_0001/data/1999010T054026_1999010T060958/",
    2: "https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/covims_0014/data/2006280T203008_2006283T032145/",
    3: "https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/covims_0028/data/2008150T001534_2008151T101955/",
    4: "https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/covims_0041/data/2010001T144918_2010004T125922/",
    5: "https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/covims_0054/data/2012275T120155_2012287T000537/",
    6: "https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/covims_0067/data/2014091T144158_2014093T173828/",
}
source = Path(os.environ["SOURCES"])
expected_sha256 = "485cbe552ab98fbfe9d5fc99622d31cb126aeb1aacb9b2afd411f5651a4ab51f"
if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
    raise SystemExit("pinned VIMS source plan identity changed")
with source.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 120 or [int(row["ordinal"]) for row in rows] != list(range(1, 121)):
    raise SystemExit("pinned VIMS source count or order changed")
if sum(int(row["file_bytes"]) for row in rows) != 194_715_648:
    raise SystemExit("pinned VIMS source-byte aggregate changed")
if {int(row["group"]) for row in rows} != set(BASE_URLS):
    raise SystemExit("pinned VIMS source groups changed")
if any(sum(int(row["group"]) == group for row in rows) != 20 for group in BASE_URLS):
    raise SystemExit("pinned VIMS source group cardinality changed")
if len({(row["group"], row["filename"]) for row in rows}) != len(rows):
    raise SystemExit("duplicate pinned VIMS source")

columns = ("ordinal", "local_filename", "payload_url", "file_bytes", "sha256")
with Path(os.environ["PLAN"]).open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        filename = row["filename"]
        digest = row["sha256"]
        ordinal = int(row["ordinal"])
        if not re.fullmatch(r"v[0-9]+_[0-9]+\.qub", filename) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit("unsafe filename or invalid SHA256 in VIMS source plan")
        writer.writerow({
            "ordinal": ordinal,
            "local_filename": f"{ordinal:03d}_{filename}",
            "payload_url": BASE_URLS[int(row["group"])] + filename,
            "file_bytes": int(row["file_bytes"]),
            "sha256": digest,
        })
print("source_plan=ok products=120 source_bytes=194715648")
PY

while IFS=$'\t' read -r ordinal local_filename payload_url file_bytes expected_sha256; do
  [[ "$ordinal" == "ordinal" ]] && continue
  target="$DOWNLOAD_DIR/$local_filename"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "payload_cache_hit ordinal=$ordinal file=$local_filename"
  else
    echo "payload_fetch ordinal=$ordinal file=$local_filename expected_bytes=$file_bytes"
    curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
      --retry-all-errors --max-time 900 --max-filesize 250000000 \
      --output "$target.part" "$payload_url"
    mv "$target.part" "$target"
  fi
  [[ "$(stat -c %s "$target")" == "$file_bytes" ]] || {
    echo "payload size mismatch: $local_filename" >&2
    exit 1
  }
  [[ "$(sha256sum "$target" | awk '{print $1}')" == "$expected_sha256" ]] || {
    echo "payload SHA256 mismatch: $local_filename" >&2
    exit 1
  }
done < "$PLAN"

export DOWNLOAD_DIR RECIPE_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path


plan = Path(os.environ["PLAN"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
module_path = Path(os.environ["RECIPE_DIR"]) / "scripts" / "vims_qube.py"
spec = importlib.util.spec_from_file_location("vims_qube_download_validation", module_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
with plan.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))

records = []
targets = {}
product_ids = set()
for row in rows:
    payload = download_dir / row["local_filename"]
    if payload.stat().st_size != int(row["file_bytes"]):
        raise SystemExit(f"downloaded VIMS size changed: {payload.name}")
    digest = module.sha256_file(payload)
    if digest != row["sha256"]:
        raise SystemExit(f"downloaded VIMS identity changed: {payload.name}")
    schema = module.parse_schema(payload)
    if schema["product_id"] in product_ids:
        raise SystemExit("duplicate VIMS product identity")
    product_ids.add(schema["product_id"])
    target = str(schema["target_name"])
    targets[target] = targets.get(target, 0) + 1
    records.append({
        "local_filename": payload.name,
        "ordinal": int(row["ordinal"]),
        "payload_sha256": digest,
        "payload_url": row["payload_url"],
        **schema,
    })
expected_targets = {
    "ATLAS": 1, "BESTLA": 1, "SATURN": 39, "SKY": 32,
    "SUN": 8, "TITAN": 38, "UNK": 1,
}
if targets != expected_targets:
    raise SystemExit(f"VIMS target distribution changed: {targets}")
if sum(int(record["core_bytes"]) for record in records) != 179_397_504:
    raise SystemExit("VIMS core-byte aggregate changed")
if sum(int(record["value_count"]) for record in records) != 89_698_752:
    raise SystemExit("VIMS value-count aggregate changed")
inventory = {
    "candidate_id": "nasa_pds_cassini_vims_qube_i16",
    "core_bytes": 179_397_504,
    "products": len(records),
    "records": records,
    "source_bytes": 194_715_648,
    "source_plan_sha256": hashlib.sha256(
        (Path(os.environ["RECIPE_DIR"]) / "sources.tsv").read_bytes()
    ).hexdigest(),
    "target_counts": targets,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print("downloaded_products=120 source_bytes=194715648 core_bytes=179397504")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
