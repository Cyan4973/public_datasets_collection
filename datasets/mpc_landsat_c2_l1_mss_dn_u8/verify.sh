#!/usr/bin/env bash
# Independently re-derive every sample from its source COG with a separate
# decoder (scripts/mss_independent_decode.py), byte-compare, and re-check the
# zero-fill policy, degeneracy / decode-correctness bounds (recomputed with
# different code paths than build.sh), the scene rule, MTL metadata, rights
# evidence, index fields and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_landsat_c2_l1_mss_dn_u8"
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
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
import mss_independent_decode as independent  # noqa: E402  (shares no code with the build decoder)
import mtl_check  # noqa: E402

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "landsat5_mss_l1tp_dn_u8"
BANDS = [("B1", "green"), ("B2", "red"), ("B3", "nir08"), ("B4", "nir09")]
FILL = 0
EXPECTED_SCENES = 13
FILL_FRACTION_RANGE = (0.05, 0.70)
MIN_VALID_PER_BAND = 1_000_000
MIN_DISTINCT_PER_BAND = 16
MIN_MASK_AGREEMENT = 0.99
MIN_BAND_PAIR_CORR = 0.5
MAX_COHERENCE = 0.6
MAX_SATURATED_FRACTION = 0.6
TOL = 1e-5

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
download_dir = data_root / "downloads" / DATASET_ID
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def histogram(payload: bytes) -> list[int]:
    one = [bytes([v]) for v in range(256)]
    counts = [payload.count(one[v]) for v in range(256)]
    if sum(counts) != len(payload):
        fail("histogram does not cover the payload")
    return counts


def band_recompute(payload: bytes, height: int, width: int) -> dict:
    counts = histogram(payload)
    fill = counts[0]
    valid = len(payload) - fill
    present = [v for v in range(1, 256) if counts[v]]
    mean = sum(v * counts[v] for v in present) / valid if valid else 0.0
    std = math.sqrt(sum(counts[v] * (v - mean) ** 2 for v in present) / valid) if valid else 0.0
    entropy = -sum((c / len(payload)) * math.log2(c / len(payload)) for c in counts if c)
    dsum = dpairs = 0
    for r in range(height):
        line = payload[r * width:(r + 1) * width]
        for (a, b), c in Counter(zip(line, line[1:])).items():
            if a and b:
                dsum += abs(a - b) * c
                dpairs += c
    coherence = (dsum / dpairs) / std if dpairs and std > 0 else float("inf")
    return {
        "fill": fill, "valid": valid, "lo": present[0] if present else None, "hi": present[-1] if present else None,
        "distinct": len(present), "mean": mean, "std": std, "sat": counts[255], "entropy": entropy,
        "coherence": coherence,
    }


def corr_recompute(a: bytes, b: bytes) -> float:
    n = sx = sy = sxx = syy = sxy = 0
    for (x, y), c in Counter(zip(a, b)).items():
        if x and y:
            n += c
            sx += c * x
            sy += c * y
            sxx += c * x * x
            syy += c * y * y
            sxy += c * x * y
    mx, my = sx / n, sy / n
    cov = sxy / n - mx * my
    vx, vy = sxx / n - mx * mx, syy / n - my * my
    return cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0


def mixed_fill(payloads: list[bytes]) -> int:
    """Sum of per-band 0/1 validity masks as big integers (no carries: each byte <= 4)."""
    to_mask = bytes([0] + [1] * 255)
    total = sum(int.from_bytes(p.translate(to_mask), "big") for p in payloads)
    summed = total.to_bytes(len(payloads[0]), "big")
    return len(summed) - summed.count(0) - summed.count(len(payloads))


manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1 or series[0].get("role") != "primary":
    fail("manifest primary series missing")
series = series[0]

# Rights evidence: offline re-check of every saved document and its receipt.
with (download_dir / "rights_receipts.tsv").open(encoding="utf-8", newline="") as fh:
    rights_rows = list(csv.DictReader(fh, delimiter="\t"))
kinds = set()
for receipt in rights_rows:
    saved = download_dir / "rights" / receipt["file"]
    if receipt.get("check") != "ok" or not saved.is_file():
        fail(f"rights evidence {receipt['file']} missing or not ok")
    blob = saved.read_bytes()
    if len(blob) != int(receipt["size_bytes"]) or hashlib.sha256(blob).hexdigest() != receipt["sha256"]:
        fail(f"rights evidence {receipt['file']} differs from its receipt")
    check = subprocess.run([sys.executable, str(recipe_dir / "scripts" / "rights_check.py"), receipt["kind"], str(saved)],
                           capture_output=True, text=True)
    if check.returncode != 0:
        fail(f"rights evidence {receipt['file']} fails the {receipt['kind']} check: {check.stderr.strip()[:500]}")
    for line in check.stdout.splitlines():
        if line.startswith(("usgs_grant_sentence", "usgs_redistribution_sentence", "aws_license_sentence",
                            "mpc_license", "mpc_licensors")):
            print(f"rights {line[:400]}")
    kinds.add(receipt["kind"])
    print(f"rights verified file={receipt['file']} kind={receipt['kind']} effective_url={receipt['effective_url']}")
if "mpc" not in kinds or not kinds & {"usgs", "aws"}:
    fail(f"rights evidence needs mpc plus usgs or aws; have {sorted(kinds)}")

plan_path = download_dir / "download_plan.tsv"
if plan_path.read_bytes() != (recipe_dir / "sources.tsv").read_bytes():
    fail("download_plan.tsv differs from the pinned sources.tsv")
with plan_path.open(encoding="utf-8", newline="") as fh:
    plan = {(r["item_id"], r["band"]): r for r in csv.DictReader(fh, delimiter="\t")}
items = sorted({k[0] for k in plan})
if len(items) != EXPECTED_SCENES:
    fail(f"plan has {len(items)} scenes, expected {EXPECTED_SCENES}")

if not index_path.is_file():
    fail(f"missing index {index_path}")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
by_key = {}
for row in rows:
    key = (row.get("stac_item_id"), row.get("band"))
    if key not in plan or key in by_key or key[1] == "MTL":
        fail(f"index row {key} not in plan, duplicated, or not a band")
    by_key[key] = row
if len(rows) != 4 * EXPECTED_SCENES:
    fail(f"index has {len(rows)} rows, expected {4 * EXPECTED_SCENES}")

digests = set()
fill_fracs = []
paths_rows = set()
for item in items:
    meta = plan[(item, "MTL")]
    p_rows, p_cols = int(meta["proj_rows"]), int(meta["proj_cols"])
    # Scene rule (pinned plan): Landsat-5 MSS L1TP T1 C2, 1984-03..1993, cloud < 5, sun > 30.
    product = meta["product_id"]
    if not (product.startswith(f"LM05_L1TP_{meta['wrs_path']}{meta['wrs_row']}_") and product.endswith("_02_T1")):
        fail(f"{item}: product {product} is not Landsat-5 MSS L1TP T1 C2 of the pinned path/row")
    if not ("1984-03-01" <= meta["datetime"][:10] <= "1993-12-31") or not (0.0 <= float(meta["cloud_cover"]) < 5.0) \
            or float(meta["sun_elevation"]) <= 30.0:
        fail(f"{item}: violates the date/cloud/sun rule")
    paths_rows.add((meta["wrs_path"], meta["wrs_row"]))
    mtl_file = data_root / "downloads" / DATASET_ID / "scenes" / meta["url"].rsplit("/", 1)[1]
    try:
        mtl = mtl_check.summarize(str(mtl_file), product, meta["wrs_path"], meta["wrs_row"], p_rows, p_cols)
    except (ValueError, OSError) as exc:
        fail(f"{item}: MTL check failed: {exc}")
    payloads = []
    for band, common in BANDS:
        row = by_key.get((item, band))
        p = plan[(item, band)]
        if row is None:
            fail(f"{item}: no index row for {band}")
        for key, value in {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary", "numeric_kind": "uint",
            "bit_width": 8, "endianness": "little", "element_size_bytes": 1, "fill_value": FILL,
            "natural_record_kind": series["natural_record_kind"], "source_format": series["source_format"],
            "source_field": series["source_field"], "band_common_name": common, "region_id": p["region_id"],
            "source_url": p["url"], "datetime": p["datetime"], "landsat_product_id": product,
            "sample_shape": [p_rows, p_cols], "radiance_mult": mtl["bands"][band]["radiance_mult"],
            "radiance_add": mtl["bands"][band]["radiance_add"],
        }.items():
            if row.get(key) != value:
                fail(f"{item} {band}: index {key}={row.get(key)!r} expected {value!r}")
        nbytes = p_rows * p_cols
        sample = data_root / row["sample_path"]
        if not sample.is_file() or sample.stat().st_size != nbytes or row["sample_size_bytes"] != nbytes \
                or row["value_count"] != nbytes:
            fail(f"{item} {band}: sample missing or size disagrees with shape {p_rows}x{p_cols}")
        payload = sample.read_bytes()
        source = data_root / row["source_file"]
        if not source.is_file() or source.stat().st_size != int(p["size_bytes"]):
            fail(f"{item} {band}: source COG missing or wrong size")
        if hashlib.sha256(source.read_bytes()).hexdigest() != row["source_sha256"]:
            fail(f"{item} {band}: source sha256 changed since build")
        shape, rederived = independent.decode_file(str(source))
        if shape != (p_rows, p_cols) or rederived != payload:
            fail(f"{item} {band}: bytes differ from independent re-derivation of {source.name}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["sha256"] or digest in digests:
            fail(f"{item} {band}: sha256 mismatch or duplicate content")
        digests.add(digest)

        s = band_recompute(payload, p_rows, p_cols)
        frac = s["fill"] / nbytes
        if s["valid"] < MIN_VALID_PER_BAND or not FILL_FRACTION_RANGE[0] <= frac <= FILL_FRACTION_RANGE[1]:
            fail(f"{item} {band}: valid={s['valid']} fill fraction {frac:.4f}")
        if s["distinct"] < MIN_DISTINCT_PER_BAND or s["hi"] <= s["lo"]:
            fail(f"{item} {band}: degenerate ({s['distinct']} distinct valid DN)")
        if s["coherence"] > MAX_COHERENCE:
            fail(f"{item} {band}: spatial coherence {s['coherence']:.3f}")
        if s["sat"] > MAX_SATURATED_FRACTION * s["valid"]:
            fail(f"{item} {band}: {s['sat']} of {s['valid']} valid pixels saturated")
        if s["lo"] < mtl["bands"][band]["quantize_cal_min"] or s["hi"] > mtl["bands"][band]["quantize_cal_max"]:
            fail(f"{item} {band}: valid DN outside the MTL quantize range")
        for key, value in {"fill_count": s["fill"], "valid_count": s["valid"], "valid_min": s["lo"],
                           "valid_max": s["hi"], "distinct_valid": s["distinct"], "saturated_255_count": s["sat"],
                           "min_value_stored": FILL if s["fill"] else s["lo"], "max_value_stored": s["hi"]}.items():
            if row.get(key) != value:
                fail(f"{item} {band}: index {key}={row.get(key)} recomputed {value}")
        for key, value, tol in (("fill_fraction", frac, 1e-6), ("valid_mean", s["mean"], 1e-4),
                                ("valid_std", s["std"], 1e-4), ("entropy_bits", s["entropy"], 1e-4),
                                ("coherence", s["coherence"], TOL)):
            if abs(float(row[key]) - value) > tol:
                fail(f"{item} {band}: index {key}={row[key]} recomputed {value:.6f}")
        fill_fracs.append(frac)
        payloads.append(payload)
        print(f"verified {item} {band} region={p['region_id']} shape={p_rows}x{p_cols} fill={frac:.3f} "
              f"dn={s['lo']}..{s['hi']} distinct={s['distinct']} coh={s['coherence']:.3f} re-derived=identical")
    mixed = mixed_fill(payloads)
    agreement = 1.0 - mixed / len(payloads[0])
    corr12 = corr_recompute(payloads[0], payloads[1])
    corr34 = corr_recompute(payloads[2], payloads[3])
    if agreement < MIN_MASK_AGREEMENT or corr12 < MIN_BAND_PAIR_CORR or corr34 < MIN_BAND_PAIR_CORR:
        fail(f"{item}: mask agreement {agreement:.4f} corr12={corr12:.3f} corr34={corr34:.3f}")
    for band, _ in BANDS:
        row = by_key[(item, band)]
        if row["scene_mixed_fill_pixels"] != mixed or abs(row["scene_mask_agreement"] - agreement) > 1e-6 \
                or abs(row["scene_corr_b1_b2"] - corr12) > TOL or abs(row["scene_corr_b3_b4"] - corr34) > TOL:
            fail(f"{item} {band}: scene-level index fields disagree with recomputation")
    print(f"verified scene {item} mask_agreement={agreement:.5f} corr12={corr12:.3f} corr34={corr34:.3f}")

if len(paths_rows) != EXPECTED_SCENES:
    fail("scenes do not cover distinct WRS-2 path/rows")
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
print(f"verified dataset={DATASET_ID} samples={len(rows)} scenes={len(items)} values={total} bytes={total} "
      f"fill_fraction_range={min(fill_fracs):.3f}..{max(fill_fracs):.3f}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
