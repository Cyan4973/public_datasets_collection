#!/usr/bin/env bash
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nsidc_snodas_masked_swe_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export RECIPE_DIR DATA_ROOT
python3 -I - <<'PY'
"""Independent re-derivation: re-read the gzip source members, swap bytes by
slicing (not array.byteswap), compare to the samples, recompute statistics and
check them against the index and the manifest."""
import array
import csv
import gzip
import hashlib
import json
import os
import statistics
import tomllib
from collections import Counter
from pathlib import Path

DATASET_ID = "nsidc_snodas_masked_swe_i16"
SERIES_ID = "snodas_swe_mm_i16"
ROWS, COLS = 3351, 6935
VALUES = ROWS * COLS
NODATA = -9999

recipe = Path(os.environ["RECIPE_DIR"])
root = Path(os.environ["DATA_ROOT"])
manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
plan = list(csv.DictReader((recipe / "plan.tsv").open(encoding="utf-8"), delimiter="\t"))
index = [json.loads(l) for l in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if l.strip()]


def fail(msg):
    raise SystemExit(f"VERIFY FAILED: {msg}")


if len(index) != len(plan) or len(index) != 20:
    fail(f"index rows {len(index)} plan rows {len(plan)} expected 20")
by_date = {r["analysis_date_utc"].replace("-", ""): r for r in index}
if set(by_date) != {p["date"] for p in plan}:
    fail("index dates differ from plan dates")

masks = set()
total = 0
sizes = []
for p in plan:
    row = by_date[p["date"]]
    for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("role", "primary"),
                      ("numeric_kind", "int"), ("bit_width", 16), ("endianness", "little"),
                      ("element_size_bytes", 2), ("value_count", VALUES),
                      ("sample_size_bytes", VALUES * 2), ("sample_shape", [ROWS, COLS])):
        if row.get(key) != want:
            fail(f"{p['date']}: index {key}={row.get(key)!r} expected {want!r}")
    sample = (root / row["sample_path"]).read_bytes()
    if len(sample) != VALUES * 2:
        fail(f"{p['date']}: sample bytes {len(sample)}")
    with gzip.open(root / "downloads" / DATASET_ID / "members" / p["dat_member"], "rb") as fh:
        src = fh.read()
    swapped = bytearray(len(src))
    swapped[0::2] = src[1::2]
    swapped[1::2] = src[0::2]
    if bytes(swapped) != sample:
        fail(f"{p['date']}: sample is not the byte-swapped source raster")
    if hashlib.sha256(sample).hexdigest() != row["sha256"]:
        fail(f"{p['date']}: sha256 mismatch")
    grid = array.array("h", sample)
    hist = Counter(grid)
    if any(v < 0 and v != NODATA for v in hist):
        fail(f"{p['date']}: negative non-nodata values present")
    nodata, zeros = hist.get(NODATA, 0), hist.get(0, 0)
    valid = [v for v in hist if v != NODATA]
    derived = {"nodata_count": nodata, "zero_count": zeros, "positive_count": VALUES - nodata - zeros,
               "saturated_32767_count": hist.get(32767, 0), "distinct_values": len(hist),
               "min_valid": min(valid), "max_valid": max(valid)}
    for key, value in derived.items():
        if row.get(key) != value:
            fail(f"{p['date']}: {key} index={row.get(key)} recomputed={value}")
    if derived["positive_count"] < VALUES // 100 or len(hist) < 500 or nodata * 2 >= VALUES:
        fail(f"{p['date']}: degenerate grid {derived}")
    mask = hashlib.sha256(bytes(v == NODATA for v in grid)).hexdigest()
    if mask != row["nodata_mask_sha256"]:
        fail(f"{p['date']}: nodata mask hash mismatch")
    masks.add(mask)
    total += len(sample)
    sizes.append(VALUES)
    print(f"ok date={p['date']} nodata={nodata / VALUES:.4f} zero={zeros / VALUES:.4f} "
          f"sat32767={derived['saturated_32767_count']} distinct={len(hist)} max={derived['max_valid']}", flush=True)

series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1:
    fail("manifest series missing")
s = series[0]
if s["sample_count"] != len(index) or s["total_size_bytes"] != total:
    fail(f"manifest sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} realized {len(index)}/{total}")
if total > 1_000_000_000 or statistics.median(sizes) < 1000:
    fail("size bounds")
print(f"verify ok dataset={DATASET_ID} samples={len(index)} bytes={total} distinct_nodata_masks={len(masks)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
