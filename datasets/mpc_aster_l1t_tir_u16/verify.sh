#!/usr/bin/env bash
# Independently re-derive every sample from its source COG with a separate
# decoder (scripts/tir_independent_decode.py), byte-compare, and re-check the
# DN range, the zero-fill policy, the degeneracy / decode-correctness bounds,
# the scene rule, index fields and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_aster_l1t_tir_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1

python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
import tir_independent_decode as independent  # noqa: E402  (shares no code with the build decoder)

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "aster_l1t_tir_radiance_dn_u16"
BANDS = 5
FILL = 0
MAX_DN = 4095
MIN_SCENES = 40
MIN_REGIONS = 20
FILL_FRACTION_RANGE = (0.05, 0.80)
MIN_VALID_PER_BAND = 50_000
MIN_DISTINCT_PER_BAND = 64
MIN_MASK_AGREEMENT = 0.98
MIN_CORR_B13_B14 = 0.5
MAX_COHERENCE_B13 = 0.75
WINDOWS = {"feb_apr": ("02-15", "04-30"), "jul_sep": ("07-01", "09-15")}

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
download_dir = data_root / "downloads" / DATASET_ID
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def recompute(payload: bytes, height: int, width: int) -> dict:
    """One pass over pixels: per-band counts/ranges, fill agreement, b13/b14 stats."""
    valid = [0] * BANDS
    lo = [MAX_DN + 1] * BANDS
    hi = [0] * BANDS
    seen = [set() for _ in range(BANDS)]
    s1 = [0] * BANDS
    s2 = [0] * BANDS
    mixed = 0
    n = sx = sy = sxx = syy = sxy = 0
    dsum = dpairs = 0
    over = 0
    prev13 = 0
    col = 0
    for px in struct.iter_unpack("<5H", payload):
        zeros = 0
        for b in range(BANDS):
            v = px[b]
            if v == 0:
                zeros += 1
                continue
            if v > MAX_DN:
                over += 1
            valid[b] += 1
            if v < lo[b]:
                lo[b] = v
            if v > hi[b]:
                hi[b] = v
            seen[b].add(v)
            s1[b] += v
            s2[b] += v * v
        if 0 < zeros < BANDS:
            mixed += 1
        x, y = px[3], px[4]
        if x and y:
            n += 1
            sx += x
            sy += y
            sxx += x * x
            syy += y * y
            sxy += x * y
        if col and x and prev13:
            dsum += abs(x - prev13)
            dpairs += 1
        prev13 = x
        col += 1
        if col == width:
            col = 0
            prev13 = 0
    pixels = height * width
    std = []
    for b in range(BANDS):
        mean = s1[b] / valid[b] if valid[b] else 0.0
        std.append(math.sqrt(max(0.0, s2[b] / valid[b] - mean * mean)) if valid[b] else 0.0)
    corr = 0.0
    if n > 1:
        corr = (sxy - sx * sy / n) / math.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n))
    coherence = (dsum / dpairs) / std[3] if dpairs and std[3] > 0 else float("inf")
    fill = BANDS * pixels - sum(valid)
    return {
        "over": over, "valid": valid, "lo": lo, "hi": hi, "distinct": [len(s) for s in seen],
        "fill": fill, "fill_fraction": fill / (BANDS * pixels), "mixed": mixed,
        "mask_agreement": 1.0 - mixed / pixels, "corr": corr, "coherence": coherence,
    }


manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1 or series[0].get("role") != "primary":
    fail("manifest primary series missing")
series = series[0]

# Rights evidence: re-run the phrase/JSON checks offline on the saved files and
# compare them with rights_receipts.tsv.
with (download_dir / "rights_receipts.tsv").open(encoding="utf-8", newline="") as fh:
    rights_rows = list(csv.DictReader(fh, delimiter="\t"))
rights_by_file = {r["file"]: r for r in rights_rows}
for name, kind in (("usgs_data_policy.html", "usgs"), ("mpc_collection_aster-l1t.json", "mpc")):
    receipt = rights_by_file.get(name)
    saved = download_dir / "rights" / name
    if receipt is None or receipt.get("check") != "ok" or not saved.is_file():
        fail(f"rights evidence {name} missing or not ok")
    blob = saved.read_bytes()
    if len(blob) != int(receipt["size_bytes"]) or hashlib.sha256(blob).hexdigest() != receipt["sha256"]:
        fail(f"rights evidence {name} differs from its receipt")
    check = subprocess.run([sys.executable, str(recipe_dir / "scripts" / "rights_check.py"), kind, str(saved)],
                           capture_output=True, text=True)
    if check.returncode != 0:
        fail(f"rights evidence {name} fails the {kind} check: {check.stderr.strip()[:500]}")
    for line in check.stdout.splitlines():
        if line.startswith(("usgs_grant_sentence", "usgs_redistribution_sentence", "mpc_license", "mpc_licensors")):
            print(f"rights {line}")
    print(f"rights verified file={name} effective_url={receipt['effective_url']} sha256={receipt['sha256'][:16]}")

plan_path = download_dir / "download_plan.tsv"
if plan_path.read_bytes() != (recipe_dir / "sources.tsv").read_bytes():
    fail("download_plan.tsv differs from the pinned sources.tsv")
with plan_path.open(encoding="utf-8", newline="") as fh:
    plan = {r["item_id"]: r for r in csv.DictReader(fh, delimiter="\t")}
if not index_path.is_file():
    fail(f"missing index {index_path}")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != len(plan) or len(rows) < MIN_SCENES:
    fail(f"index rows={len(rows)} plan rows={len(plan)} minimum={MIN_SCENES}")

digests = set()
items = set()
regions = set()
fill_fracs = []
for row in rows:
    item = row.get("stac_item_id")
    p = plan.get(item)
    if p is None or item in items:
        fail(f"index item {item} not in plan or duplicated")
    items.add(item)
    for key, value in {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary", "numeric_kind": "uint",
        "bit_width": 16, "endianness": "little", "element_size_bytes": 2, "fill_value": FILL,
        "natural_record_kind": series["natural_record_kind"], "source_format": series["source_format"],
        "source_field": series["source_field"], "region_id": p["region_id"], "window": p["window"],
        "source_url": p["url"], "datetime": p["datetime"],
        "band_order": ["ImageData10", "ImageData11", "ImageData12", "ImageData13", "ImageData14"],
    }.items():
        if row.get(key) != value:
            fail(f"{item}: index {key}={row.get(key)!r} expected {value!r}")
    # Scene rule: daytime, low cloud, inside the region's seasonal window, 2000..2006.
    if not (0.0 <= float(p["cloud_cover"]) < 10.0) or float(p["sun_elevation"]) <= 20.0:
        fail(f"{item}: violates the cloud/daytime rule")
    lo_w, hi_w = WINDOWS[p["window"]]
    if not (2000 <= int(p["year"]) <= 2006 and p["datetime"].startswith(p["year"]) and lo_w <= p["datetime"][5:10] <= hi_w):
        fail(f"{item}: datetime {p['datetime']} outside {p['year']} {p['window']}")
    regions.add(p["region_id"])

    height, width, bands = row["sample_shape"]
    if bands != BANDS:
        fail(f"{item}: {bands} bands")
    nbytes = height * width * BANDS * 2
    sample = data_root / row["sample_path"]
    if not sample.is_file() or sample.stat().st_size != nbytes or row["sample_size_bytes"] != nbytes \
            or row["value_count"] != nbytes // 2:
        fail(f"{item}: sample missing or size disagrees with shape {row['sample_shape']}")
    payload = sample.read_bytes()
    source = data_root / row["source_file"]
    if not source.is_file() or source.stat().st_size != int(p["size_bytes"]):
        fail(f"{item}: source COG missing or wrong size")
    if hashlib.sha256(source.read_bytes()).hexdigest() != row["source_sha256"]:
        fail(f"{item}: source sha256 changed since build")
    shape, rederived = independent.decode_file(str(source))
    if shape != (height, width, BANDS) or rederived != payload:
        fail(f"{item}: bytes differ from independent re-derivation of {source.name}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != row["sha256"] or digest in digests:
        fail(f"{item}: sha256 mismatch or duplicate content")
    digests.add(digest)

    s = recompute(payload, height, width)
    if s["over"]:
        fail(f"{item}: {s['over']} values above the 12-bit DN range")
    if not FILL_FRACTION_RANGE[0] <= s["fill_fraction"] <= FILL_FRACTION_RANGE[1]:
        fail(f"{item}: fill fraction {s['fill_fraction']:.4f}")
    for b in range(BANDS):
        if s["valid"][b] < MIN_VALID_PER_BAND or s["distinct"][b] < MIN_DISTINCT_PER_BAND or s["hi"][b] <= s["lo"][b]:
            fail(f"{item}: band {10 + b} degenerate valid={s['valid'][b]} distinct={s['distinct'][b]}")
        ib = row["per_band"][b]
        if (ib["valid_count"], ib["min"], ib["max"], ib["distinct"]) != (s["valid"][b], s["lo"][b], s["hi"][b], s["distinct"][b]):
            fail(f"{item}: index per_band[{b}] disagrees with recomputation")
    if s["mask_agreement"] < MIN_MASK_AGREEMENT:
        fail(f"{item}: band fill masks disagree ({s['mask_agreement']:.4f})")
    if s["corr"] < MIN_CORR_B13_B14 or s["coherence"] > MAX_COHERENCE_B13:
        fail(f"{item}: decode sanity corr13/14={s['corr']:.3f} coherence13={s['coherence']:.3f}")
    for key, value in {"fill_count": s["fill"], "mixed_fill_pixels": s["mixed"],
                       "valid_min": min(s["lo"]), "valid_max": max(s["hi"]),
                       "min_value_stored": FILL if s["fill"] else min(s["lo"]), "max_value_stored": max(s["hi"])}.items():
        if row.get(key) != value:
            fail(f"{item}: index {key}={row.get(key)} recomputed {value}")
    for key, value in {"corr_b13_b14": s["corr"], "coherence_b13": s["coherence"], "fill_fraction": s["fill_fraction"]}.items():
        if abs(float(row[key]) - value) > 1e-5:
            fail(f"{item}: index {key}={row[key]} recomputed {value:.6f}")
    fill_fracs.append(s["fill_fraction"])
    print(f"verified {item} region={p['region_id']} window={p['window']} shape={height}x{width}x5 "
          f"fill={s['fill_fraction']:.3f} dn={min(s['lo'])}..{max(s['hi'])} corr={s['corr']:.3f} "
          f"coh={s['coherence']:.3f} re-derived=identical")

if len(regions) < MIN_REGIONS:
    fail(f"only {len(regions)} regions")
total = sum(int(r["sample_size_bytes"]) for r in rows)
if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
    fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != {len(rows)}/{total}")
if total > 1_000_000_000:
    fail(f"primary bytes {total} exceed 1e9")
if statistics.median(int(r["value_count"]) for r in rows) < 1000:
    fail("median sample below floor")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats["samples"] != len(rows) or stats["primary_sample_bytes"] != total:
    fail("ingest_stats totals mismatch")
if stats.get("rights_receipts") != rights_rows:
    fail("ingest_stats rights_receipts differ from rights_receipts.tsv")
windows = {w: sum(1 for r in rows if r["window"] == w) for w in WINDOWS}
print(f"verified dataset={DATASET_ID} samples={len(rows)} regions={len(regions)} windows={windows} "
      f"values={total // 2} bytes={total} fill_fraction_range={min(fill_fracs):.3f}..{max(fill_fracs):.3f}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
