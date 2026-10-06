#!/usr/bin/env bash
# Independently re-derive every sample from its source GeoTIFF with a second
# decoder (separate IFD0 reader and a different predictor-undo / byte-order
# path from scripts/gwa_tiff.py), byte-compare, and re-check the NaN policy,
# plausibility and degeneracy bounds, index fields, pins and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwa_v4_country_wind_speed_100m_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
from __future__ import annotations

import array
import csv
import hashlib
import itertools
import json
import os
import statistics
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "gwa_v4_wind_speed_100m_f32"
EXPECTED_SAMPLES = 31
NAN_BITS = 0x7FC00000
VALID_SHARE_RANGE = (0.30, 0.90)
VALUE_RANGE = (0.0, 40.0)
MIN_DISTINCT_VALID = 10_000
MIN_VALID_SPAN = 0.5
DATASET_VALID_SHARE_RANGE = (0.45, 0.75)
ZSTD = os.environ.get("ZSTD_BIN", "zstd")

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"

if sys.byteorder != "little":
    raise SystemExit("VERIFY FAIL: little-endian host assumed")


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def rederive(path: Path) -> tuple[int, int, bytes]:
    """Second, independent decoder for IFD0 of a GWA v4 BigTIFF."""
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 11: 4, 12: 8, 16: 8}
    fmts = {3: "H", 4: "I", 12: "d", 16: "Q"}
    with path.open("rb") as fh:
        hdr = fh.read(16)
        magic, version, bytesize, _, ifd0 = struct.unpack("<2sHHHQ", hdr)
        if magic != b"II" or version != 43 or bytesize != 8:
            fail(f"{path.name}: not a little-endian BigTIFF")
        fh.seek(ifd0)
        (n,) = struct.unpack("<Q", fh.read(8))
        entries = {}
        for _ in range(n):
            tag, typ, count, raw = struct.unpack("<HHQ8s", fh.read(20))
            entries[tag] = (typ, count, raw)

        def get(tag):
            typ, count, raw = entries[tag]
            nbytes = sizes[typ] * count
            if nbytes <= 8:
                blob = raw[:nbytes]
            else:
                fh.seek(struct.unpack("<Q", raw)[0])
                blob = fh.read(nbytes)
            if typ == 2:
                return blob.rstrip(b"\x00").decode()
            return list(struct.unpack("<" + fmts[typ] * count, blob))

        if 254 in entries and get(254) != [0]:
            fail(f"{path.name}: first IFD is not full resolution")
        want = {258: [32], 259: [50000], 277: [1], 284: [1], 317: [3], 322: [512], 323: [512], 339: [3]}
        for tag, value in want.items():
            if get(tag) != value:
                fail(f"{path.name}: tag {tag}={get(tag)} expected {value}")
        if get(42113).strip().lower() != "nan":
            fail(f"{path.name}: GDAL_NODATA {get(42113)!r}")
        scale = get(33550)
        if abs(scale[0] - 0.0025) > 1e-12 or abs(scale[1] - 0.0025) > 1e-12:
            fail(f"{path.name}: pixel scale {scale}")
        width, height = get(256)[0], get(257)[0]
        offsets, counts = get(324), get(325)
        tile = 512
        across = -(-width // tile)
        down = -(-height // tile)
        if len(offsets) != across * down:
            fail(f"{path.name}: {len(offsets)} tiles for {width}x{height}")
        out = bytearray(width * height * 4)
        for t in range(across * down):
            fh.seek(offsets[t])
            proc = subprocess.run([ZSTD, "-dcq"], input=fh.read(counts[t]),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            raw = proc.stdout
            if proc.returncode != 0 or len(raw) != tile * tile * 4:
                fail(f"{path.name}: tile {t} zstd rc={proc.returncode} bytes={len(raw)}")
            tx, ty = t % across, t // across
            cols = min(tile, width - tx * tile)
            for r in range(min(tile, height - ty * tile)):
                row = raw[r * tile * 4:(r + 1) * tile * 4]
                # byte-wise horizontal accumulation modulo 256
                acc = bytes(itertools.accumulate(row, lambda a, b: (a + b) & 0xFF))
                # interleave MSB-first planes into big-endian words, then
                # byte-swap the words to little-endian
                be = bytearray(tile * 4)
                for k in range(4):
                    be[k::4] = acc[k * tile:(k + 1) * tile]
                words = array.array("f")
                words.frombytes(bytes(be[:cols * 4]))
                words.byteswap()
                dst = ((ty * tile + r) * width + tx * tile) * 4
                out[dst:dst + cols * 4] = words.tobytes()
        lon, lat = get(33922)[3:5]
        return width, height, bytes(out), (lon, lat)


manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1 or series[0].get("role") != "primary":
    fail("manifest primary series missing")
series = series[0]
pins = {r["iso3"]: r for r in csv.DictReader((recipe_dir / "countries.tsv").open(encoding="utf-8"), delimiter="\t")}
if len(pins) != EXPECTED_SAMPLES:
    fail(f"countries.tsv has {len(pins)} rows")

if not index_path.is_file():
    fail(f"missing index {index_path}")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != EXPECTED_SAMPLES or sorted(r.get("iso3") for r in rows) != sorted(pins):
    fail(f"index rows={len(rows)} do not cover exactly the pinned countries")

digests: set[str] = set()
total_values = total_valid = 0
for row in rows:
    iso = row["iso3"]
    pin = pins[iso]
    width, height = int(pin["width"]), int(pin["height"])
    nbytes = width * height * 4
    for key, value in {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary", "numeric_kind": "float",
        "bit_width": 32, "endianness": "little", "element_size_bytes": 4,
        "sample_size_bytes": nbytes, "value_count": width * height, "sample_shape": [height, width],
        "natural_record_kind": series["natural_record_kind"], "source_format": series["source_format"],
        "source_field": series["source_field"], "source_url": pin["url"], "units": "m/s",
        "height_above_ground_m": 100,
    }.items():
        if row.get(key) != value:
            fail(f"{iso}: index {key}={row.get(key)!r} expected {value!r}")

    source = data_root / row["source_file"]
    if not source.is_file() or source.stat().st_size != int(pin["size_bytes"]):
        fail(f"{iso}: source file missing or wrong size {source}")
    blob = source.read_bytes()
    if hashlib.md5(blob).hexdigest() != pin["etag_md5"]:
        fail(f"{iso}: source md5 != pinned ETag")
    sha = hashlib.sha256(blob).hexdigest()
    if (pin["sha256"] and sha != pin["sha256"]) or sha != row["source_sha256"]:
        fail(f"{iso}: source sha256 {sha} mismatch (pin {pin['sha256'] or '-'}, index {row['source_sha256']})")
    del blob

    sample = data_root / row["sample_path"]
    if not sample.is_file() or sample.stat().st_size != nbytes:
        fail(f"{iso}: missing or wrong-size sample {sample}")
    payload = sample.read_bytes()
    w, h, rederived, (lon, lat) = rederive(source)
    if (w, h) != (width, height) or f"{lon:.6f}" != pin["upper_left_lon"] or f"{lat:.6f}" != pin["upper_left_lat"]:
        fail(f"{iso}: geometry {w}x{h} @ {lon},{lat} differs from pins")
    if rederived != payload:
        fail(f"{iso}: sample bytes differ from independent re-derivation")
    del rederived
    digest = hashlib.sha256(payload).hexdigest()
    if digest != row["sha256"] or digest in digests:
        fail(f"{iso}: sample sha256 mismatch or duplicate")
    digests.add(digest)

    bits = array.array("I")
    bits.frombytes(payload)
    vals = array.array("f")
    vals.frombytes(payload)
    nan_count = bits.count(NAN_BITS)
    valid = [v for v in vals if v == v]
    if len(vals) - nan_count - len(valid):
        fail(f"{iso}: NaNs with a non-GDAL bit pattern present")
    share = len(valid) / len(vals)
    lo, hi = min(valid), max(valid)
    distinct = len({b for b in bits if b != NAN_BITS})
    if not VALID_SHARE_RANGE[0] <= share <= VALID_SHARE_RANGE[1]:
        fail(f"{iso}: valid share {share:.4f} outside {VALID_SHARE_RANGE}")
    if lo < VALUE_RANGE[0] or hi > VALUE_RANGE[1] or hi in (float("inf"),):
        fail(f"{iso}: value range {lo}..{hi} implausible for m/s")
    if distinct < MIN_DISTINCT_VALID or hi - lo < MIN_VALID_SPAN:
        fail(f"{iso}: degenerate raster (distinct={distinct}, span={hi - lo})")
    recomputed = {
        "nan_count": nan_count, "valid_count": len(valid), "valid_share": round(share, 6),
        "min_value_stored": lo, "max_value_stored": hi, "distinct_valid_values": distinct,
    }
    for key, value in recomputed.items():
        if row.get(key) != value:
            fail(f"{iso}: index {key}={row.get(key)!r} recomputed {value!r}")
    total_values += len(vals)
    total_valid += len(valid)
    print(f"verified iso3={iso} {height}x{width} valid_share={share:.4f} range={lo:.3f}..{hi:.3f} "
          f"distinct={distinct} re-derived=identical")

total_bytes = sum(int(r["sample_size_bytes"]) for r in rows)
if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
    fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
         f"!= realized {len(rows)}/{total_bytes}")
if total_bytes > 1_000_000_000:
    fail(f"primary bytes {total_bytes} exceed 1e9")
if statistics.median(int(r["value_count"]) for r in rows) < 1000:
    fail("median sample below floor")
dataset_share = total_valid / total_values
if not DATASET_VALID_SHARE_RANGE[0] <= dataset_share <= DATASET_VALID_SHARE_RANGE[1]:
    fail(f"dataset valid share {dataset_share:.4f} outside {DATASET_VALID_SHARE_RANGE}")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats["samples"] != len(rows) or stats["primary_sample_bytes"] != total_bytes or stats["valid_values"] != total_valid:
    fail("ingest_stats totals mismatch")
print(f"verified dataset={DATASET_ID} samples={len(rows)} values={total_values} bytes={total_bytes} "
      f"valid_share={dataset_share:.4f}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
