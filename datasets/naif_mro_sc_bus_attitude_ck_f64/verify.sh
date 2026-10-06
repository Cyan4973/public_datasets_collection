#!/usr/bin/env bash
# Independent verification: re-decodes every pinned raw CK segment with a
# separate struct-based reader (it does not import the build modules) and
# checks samples, index, stats and manifest against it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
DATASET_ID="naif_mro_sc_bus_attitude_ck_f64"
LOG_DIR="${DATA_DIR}/logs/${DATASET_ID}"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/verify.${RUN_TS}.log" "${LOG_DIR}/verify.latest.log") 2>&1
echo "[$(date -u -Is)] verify start dataset=${DATASET_ID}"

python3 - "${SCRIPT_DIR}" "${DATA_DIR}" <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import tomllib

recipe = Path(sys.argv[1])
data = Path(sys.argv[2]).resolve()
DATASET_ID = "naif_mro_sc_bus_attitude_ck_f64"
QUAT, RATE, EPOCH = "mro_sc_bus_quaternion_f64", "mro_sc_bus_angular_rate_f64", "mro_sc_bus_sclk_epoch_ticks_f64"
downloads = data / "downloads" / DATASET_ID
samples_root = data / "samples" / DATASET_ID
index_path = data / "index" / DATASET_ID / "samples.jsonl"
stats_path = data / "filtered" / DATASET_ID / "segment_stats.json"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
if manifest.get("dataset_id") != DATASET_ID:
    fail("manifest dataset_id mismatch")
declared = {s["id"]: s for s in manifest["series"]}
if set(declared) != {QUAT, RATE, EPOCH}:
    fail(f"manifest series {sorted(declared)} unexpected")
if declared[QUAT]["role"] != "primary" or declared[RATE]["role"] != "primary" or declared[EPOCH]["role"] != "auxiliary":
    fail("manifest roles changed")

with (recipe / "sources.tsv").open(encoding="utf-8", newline="") as handle:
    sources = list(csv.DictReader(handle, delimiter="\t"))
if len(sources) != 44 or len({(r["file_name"], r["segment_ordinal"]) for r in sources}) != 44:
    fail("sources.tsv must pin 44 distinct segments")
years = sorted({int(r["year"]) for r in sources})
if years != list(range(2007, 2018)):
    fail(f"selected years {years} are not exactly 2007..2017")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
by_path = {}
for row in rows:
    for key in ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness", "element_size_bytes", "sample_size_bytes", "value_count"):
        if key not in row:
            fail(f"index row missing {key}: {row}")
    if row["dataset_id"] != DATASET_ID or row["series_id"] not in declared:
        fail(f"bad index identity {row['sample_path']}")
    if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 64, "little", 8):
        fail(f"bad numeric metadata {row['sample_path']}")
    if row["sample_path"] in by_path:
        fail(f"duplicate index path {row['sample_path']}")
    by_path[row["sample_path"]] = row
if len(rows) != 3 * len(sources):
    fail(f"index has {len(rows)} rows, expected {3 * len(sources)}")


def median_abs_step(values, stride, axis):
    col = values[axis::stride]
    return statistics.median(abs(col[i + 1] - col[i]) for i in range(len(col) - 1))


expected_paths = set()
quaternion_digests = set()
checked = 0
for src in sources:
    stem = src["file_name"][:-3]
    ordinal = int(src["segment_ordinal"])
    raw = (downloads / "segments" / f"{stem}__seg{ordinal:02d}.be").read_bytes()
    pin = src["segment_sha256"].strip()
    if pin not in ("", "-") and hashlib.sha256(raw).hexdigest() != pin:
        fail(f"{stem} #{ordinal}: raw segment sha256 differs from pin")
    count = len(raw) // 8
    if len(raw) % 8:
        fail(f"{stem} #{ordinal}: raw size not a multiple of 8")
    words = struct.unpack(f">{count}d", raw)
    nints, n = words[-2], words[-1]
    if n != int(n) or nints != int(nints) or n < 1 or nints < 1:
        fail(f"{stem} #{ordinal}: bad trailer")
    n, nints = int(n), int(nints)
    if (n, nints) != (int(src["n_records"]), int(src["nints"])):
        fail(f"{stem} #{ordinal}: trailer differs from pin")
    if count != 8 * n + (n - 1) // 100 + nints + (nints - 1) // 100 + 2:
        fail(f"{stem} #{ordinal}: segment length inconsistent with N={n} NINTS={nints}")
    epochs = words[7 * n : 8 * n]
    if any(b <= a for a, b in zip(epochs, epochs[1:])):
        fail(f"{stem} #{ordinal}: epochs not strictly increasing")
    if epochs[0] < float(src["sclk_begin"]) or epochs[-1] > float(src["sclk_end"]):
        fail(f"{stem} #{ordinal}: epochs outside pinned coverage")
    directory = words[8 * n : 8 * n + (n - 1) // 100]
    if any(directory[j] != epochs[100 * (j + 1) - 1] for j in range(len(directory))):
        fail(f"{stem} #{ordinal}: epoch directory mismatch")
    quats = [c for i in range(n) for c in words[7 * i : 7 * i + 4]]
    rates = [c for i in range(n) for c in words[7 * i + 4 : 7 * i + 7]]
    if not all(math.isfinite(v) for v in quats + rates):
        fail(f"{stem} #{ordinal}: non-finite pointing values")
    worst = max(abs(math.sqrt(sum(c * c for c in quats[4 * i : 4 * i + 4])) - 1.0) for i in range(n))
    if worst > 1e-6:
        fail(f"{stem} #{ordinal}: quaternion norm deviation {worst}")
    steps = [median_abs_step(rates, 3, a) for a in range(3)]
    if max(steps) < 2e-6:
        fail(f"{stem} #{ordinal}: rate step medians {steps} are not gyro-era telemetry")
    expected = {
        QUAT: struct.pack(f"<{4 * n}d", *quats),
        RATE: struct.pack(f"<{3 * n}d", *rates),
        EPOCH: struct.pack(f"<{n}d", *epochs),
    }
    shapes = {QUAT: [n, 4], RATE: [n, 3], EPOCH: [n]}
    for series, payload in expected.items():
        rel = f"samples/{DATASET_ID}/{series}/{stem}_seg{ordinal:02d}.bin"
        expected_paths.add(rel)
        row = by_path.get(rel)
        if row is None:
            fail(f"missing index row {rel}")
        stored = (data / rel).read_bytes()
        if stored != payload:
            fail(f"{rel}: stored bytes differ from independent decode")
        values = struct.unpack(f"<{len(stored) // 8}d", stored)
        if row["value_count"] != len(values) or row["sample_size_bytes"] != len(stored) or row.get("shape") != shapes[series]:
            fail(f"{rel}: index counts/shape wrong")
        if min(values) == max(values):
            fail(f"{rel}: constant sample")
        if row.get("min") != min(values) or row.get("max") != max(values):
            fail(f"{rel}: index min/max differ from stored doubles")
        if row.get("role") != declared[series]["role"]:
            fail(f"{rel}: index role differs from manifest")
        if series != EPOCH:
            for axis in range(shapes[series][1]):
                column = values[axis :: shapes[series][1]]
                if min(column) == max(column):
                    fail(f"{rel}: component {axis} is constant")
        if series == QUAT:
            digest = hashlib.sha256(stored).hexdigest()
            if digest in quaternion_digests:
                fail(f"{rel}: duplicate quaternion sample")
            quaternion_digests.add(digest)
    checked += 1

if set(by_path) != expected_paths:
    fail("index lists samples not derived from sources.tsv")
on_disk = {p.relative_to(data).as_posix() for p in samples_root.rglob("*") if p.is_file()}
if on_disk != expected_paths:
    fail(f"stray or missing sample files: {sorted(on_disk ^ expected_paths)[:5]}")

primary_counts = [r["value_count"] for r in rows if declared[r["series_id"]]["role"] == "primary"]
primary_bytes = sum(r["sample_size_bytes"] for r in rows if declared[r["series_id"]]["role"] == "primary")
if sum(primary_counts) < 10_000 and primary_bytes < 102_400:
    fail("primary aggregate floor not met")
if statistics.median(primary_counts) < 1_000:
    fail("median primary sample below 1,000 values")
if primary_bytes > 1_000_000_000:
    fail("primary output exceeds 1 GB")
for series, spec in declared.items():
    chosen = [r for r in rows if r["series_id"] == series]
    size = sum(r["sample_size_bytes"] for r in chosen)
    if spec.get("sample_count") != len(chosen) or spec.get("total_size_bytes") != size:
        fail(f"manifest {series}: sample_count/total_size_bytes {spec.get('sample_count')}/{spec.get('total_size_bytes')} != realized {len(chosen)}/{size}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("primary_value_count") != sum(primary_counts) or stats.get("primary_sample_bytes") != primary_bytes:
    fail("build stats disagree with the verified index")

print(f"verified segments={checked} primary_samples={len(primary_counts)} primary_values={sum(primary_counts)} primary_bytes={primary_bytes} median_values={statistics.median(primary_counts)}")
PY
echo "[$(date -u -Is)] verify complete"
