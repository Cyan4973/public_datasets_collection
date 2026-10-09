#!/usr/bin/env bash
# Independently re-check the built samples: re-parse each local FLAC's
# STREAMINFO (own parser, not the build helper), require the sample to be
# exactly total_samples*2 int16 values whose MD5 equals the FLAC MD5 signature
# (proof of a bit-exact lossless decode), recompute the statistics recorded in
# the index, and enforce the same degenerate-output policy as build.sh.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="musopen_chopin_solo_piano_pcm_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

export DATA_ROOT RECIPE_DIR DATASET_ID
python3 -I - <<'PY'
import hashlib
import json
import os
import statistics
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "chopin_solo_piano_pcm_s16_stereo"
data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
flac_dir = data_root / "downloads" / DATASET_ID / "flac"
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
if sys.byteorder != "little":
    raise SystemExit("verify assumes a little-endian host")


def fail(msg):
    raise SystemExit(f"VERIFY FAILED: {msg}")


def streaminfo(path):
    with path.open("rb") as fh:
        head = fh.read(42)
    if head[:4] != b"fLaC" or head[4] & 0x7F != 0:
        fail(f"{path.name}: not a FLAC stream starting with STREAMINFO")
    bits = int.from_bytes(head[18:26], "big")  # sr(20) ch-1(3) bps-1(5) total(36)
    return {
        "sample_rate": bits >> 44,
        "channels": ((bits >> 41) & 0x7) + 1,
        "bps": ((bits >> 36) & 0x1F) + 1,
        "total": bits & ((1 << 36) - 1),
        "md5": head[26:42].hex(),
    }


manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1 or series[0]["role"] != "primary":
    fail("manifest must declare exactly one primary series " + SERIES_ID)
series = series[0]

pinned_lines = (recipe_dir / "scripts" / "pinned_files.tsv").read_text(encoding="utf-8").splitlines()
hdr = pinned_lines[0].split("\t")
pinned = [dict(zip(hdr, l.split("\t"))) for l in pinned_lines[1:] if l.strip()]
pinned_ids = [p["sample_id"] for p in pinned]

if not index_path.is_file():
    fail(f"missing index {index_path}")
rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
if [r["sample_id"] for r in rows] != pinned_ids:
    fail("index sample ids differ from the pinned piece list (missing, extra, or reordered pieces)")
expected_files = {f"{sid}.bin" for sid in pinned_ids}
out_dir = data_root / series["output_path"]
actual_files = {p.name for p in out_dir.iterdir()}
if actual_files != expected_files:
    fail(f"sample directory content mismatch: extra={sorted(actual_files - expected_files)[:5]} missing={sorted(expected_files - actual_files)[:5]}")

values, sizes = [], []
total_seconds = 0.0
for row, pin in zip(rows, pinned):
    sid = row["sample_id"]
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID or row.get("role") != "primary":
        fail(f"{sid}: wrong identity fields")
    if (row["numeric_kind"], int(row["bit_width"]), row["endianness"], int(row["element_size_bytes"])) != ("int", 16, "little", 2):
        fail(f"{sid}: wrong numeric representation")
    si = streaminfo(flac_dir / f"{sid}.flac")
    if (si["sample_rate"], si["channels"], si["bps"]) != (44100, 2, 16):
        fail(f"{sid}: source FLAC is not 44.1 kHz / stereo / 16-bit: {si}")
    if si["total"] != int(pin["total_samples"]) or si["md5"] != pin["streaminfo_md5"]:
        fail(f"{sid}: source FLAC STREAMINFO differs from the pinned table")
    path = data_root / row["sample_path"]
    pcm = path.read_bytes()
    if len(pcm) != si["total"] * 4 or int(row["sample_size_bytes"]) != len(pcm) or int(row["value_count"]) != si["total"] * 2:
        fail(f"{sid}: size {len(pcm)} != total_samples*2ch*2B {si['total'] * 4} (or index disagrees)")
    if hashlib.md5(pcm).hexdigest() != si["md5"]:
        fail(f"{sid}: sample MD5 != FLAC STREAMINFO MD5 signature")
    arr = array("h")
    arr.frombytes(pcm)
    lo, hi = min(arr), max(arr)
    if lo == hi:
        fail(f"{sid}: constant sample")
    if (lo, hi) != (row["min"], row["max"]):
        fail(f"{sid}: min/max {lo}/{hi} differ from index {row['min']}/{row['max']}")
    zero_fraction = arr.count(0) / len(arr)
    if abs(zero_fraction - row["zero_fraction"]) > 1e-6 or zero_fraction > 0.5:
        fail(f"{sid}: zero fraction {zero_fraction:.6f} (index {row['zero_fraction']}, limit 0.5)")
    frames = len(arr) // 2
    # leading/trailing all-zero frames, recomputed frame-by-frame at the edges
    lead = 0
    while lead < frames and arr[2 * lead] == 0 and arr[2 * lead + 1] == 0:
        lead += 1
    trail = 0
    while trail < frames - lead and arr[2 * (frames - 1 - trail)] == 0 and arr[2 * (frames - 1 - trail) + 1] == 0:
        trail += 1
    if round(lead / 44100, 4) != row["leading_silence_s"] or round(trail / 44100, 4) != row["trailing_silence_s"]:
        fail(f"{sid}: edge silence {lead}/{trail} frames disagrees with index")
    if (lead + trail) / frames > 0.5:
        fail(f"{sid}: dominated by leading/trailing digital silence")
    if arr[0::2] == arr[1::2]:
        fail(f"{sid}: left and right channels identical")
    if len(set(arr)) < 1024:
        fail(f"{sid}: fewer than 1024 distinct values")
    if not any(v & 1 for v in arr):
        fail(f"{sid}: no odd sample values (padded below 16-bit)")
    values.append(len(arr))
    sizes.append(len(pcm))
    total_seconds += frames / 44100
    print(f"ok {sid} frames={frames} range={lo}..{hi} zero_frac={zero_fraction:.4f} lead={lead / 44100:.3f}s trail={trail / 44100:.3f}s")

if series["sample_count"] != len(rows):
    fail(f"manifest sample_count {series['sample_count']} != {len(rows)}")
if series["total_size_bytes"] != sum(sizes):
    fail(f"manifest total_size_bytes {series['total_size_bytes']} != {sum(sizes)}")
if sum(sizes) > 1_000_000_000:
    fail("primary bytes exceed 1 GB cap")
if statistics.median(values) < 1000 or sum(values) < 10000:
    fail("below primary floors")
print(f"verified samples={len(rows)} primary_values={sum(values)} primary_bytes={sum(sizes)} "
      f"median_values={statistics.median(values)} hours={total_seconds / 3600:.3f}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
