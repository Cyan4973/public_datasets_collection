#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="chbmit_physionet"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import hashlib
import json
import os
import random
import re
import struct
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

channel_specs = [
    ("F7-T7|F7-T3", "F7-T7", "chbmit_f7_t7_1d_var"),
    ("FZ-CZ", "FZ-CZ", "chbmit_fz_cz_1d_var"),
    ("F8-T8|F8-T4", "F8-T8", "chbmit_f8_t8_1d_var"),
]
max_sample_bytes = int(os.environ.get("CHBMIT_MAX_SAMPLE_BYTES", str(1024 * 1024)))
min_shard_bytes = int(os.environ.get("CHBMIT_MIN_SHARD_BYTES", str(512 * 1024)))
shard_seed = int(os.environ.get("CHBMIT_SHARD_SEED", "20260422"))
if max_sample_bytes < 2 or min_shard_bytes < 2 or min_shard_bytes > max_sample_bytes:
    raise SystemExit("invalid shard byte settings")
if max_sample_bytes % 2 or min_shard_bytes % 2:
    raise SystemExit("shard byte settings must be divisible by 2")
max_samples = max_sample_bytes // 2
min_samples = min_shard_bytes // 2


def normalize_label(label: str) -> str:
    s = label.strip().upper().rstrip(".")
    s = re.sub(r"\s+", "", s)
    if s.startswith("EEG"):
        s = s[3:]
    return s


def parse_int_field(raw: bytes) -> int:
    text = raw.decode("ascii", errors="replace").strip()
    if not text:
        raise RuntimeError("empty EDF integer field")
    return int(float(text))


def parse_float_field(raw: bytes) -> float:
    text = raw.decode("ascii", errors="replace").strip()
    if not text:
        raise RuntimeError("empty EDF float field")
    return float(text)


def parse_edf_header(fh):
    fh.read(8)
    fh.read(80)
    fh.read(80)
    fh.read(8)
    fh.read(8)
    header_bytes = parse_int_field(fh.read(8))
    fh.read(44)
    n_records = parse_int_field(fh.read(8))
    duration_sec = parse_float_field(fh.read(8))
    ns = parse_int_field(fh.read(4))
    labels = [fh.read(16).decode("ascii", errors="replace").strip() for _ in range(ns)]
    for _ in range(ns):
        fh.read(80)
    for _ in range(ns):
        fh.read(8)
    for _ in range(ns):
        fh.read(8)
    for _ in range(ns):
        fh.read(8)
    for _ in range(ns):
        fh.read(8)
    for _ in range(ns):
        fh.read(8)
    for _ in range(ns):
        fh.read(80)
    samples_per_record = [parse_int_field(fh.read(8)) for _ in range(ns)]
    for _ in range(ns):
        fh.read(32)
    return {
        "header_bytes": header_bytes,
        "n_records": n_records,
        "duration_sec": duration_sec,
        "ns": ns,
        "labels": labels,
        "samples_per_record": samples_per_record,
    }


def deterministic_lengths(total_samples: int, min_samples: int, max_samples: int, seed_material: str):
    if total_samples <= max_samples:
        return [total_samples]
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    remaining = total_samples
    out = []
    while remaining > max_samples:
        low = min_samples
        high = max_samples
        room = remaining - min_samples
        if room < high:
            high = room
        if high < low:
            high = low
        n = rng.randint(low, high)
        out.append(n)
        remaining -= n
    if remaining:
        out.append(remaining)
    return out


records_path = download_dir / "RECORDS.selected"
if not records_path.exists():
    raise SystemExit(f"missing selection file: {records_path}")
records = [line.strip() for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if not records:
    raise SystemExit("empty RECORDS.selected")

for _spec, _canon, family in channel_specs:
    (samples_dir / family).mkdir(parents=True, exist_ok=True)

rows = []
inventory = []
for rel in records:
    edf_path = download_dir / rel
    if not edf_path.exists():
        raise SystemExit(f"missing selected EDF: {edf_path}")
    with edf_path.open("rb") as fh:
        meta = parse_edf_header(fh)
        normalized = [normalize_label(x) for x in meta["labels"]]
        match_by_index = {}
        for spec, canonical, family in channel_specs:
            aliases = [normalize_label(tok) for tok in spec.split("|") if tok.strip()]
            matches = [i for i, label in enumerate(normalized) if label in aliases]
            if not matches:
                raise SystemExit(f"missing channel {spec} in {edf_path}")
            match_by_index[matches[0]] = (canonical, family, normalized[matches[0]])

        signal_bytes = [n * 2 for n in meta["samples_per_record"]]
        fh.seek(meta["header_bytes"])
        buffers = {family: bytearray() for _spec, _canonical, family in channel_specs}
        for _ in range(meta["n_records"]):
            for idx, n_bytes in enumerate(signal_bytes):
                block = fh.read(n_bytes)
                if len(block) != n_bytes:
                    raise SystemExit(f"unexpected EOF in {edf_path}")
                if idx in match_by_index:
                    _canonical, family, _matched = match_by_index[idx]
                    buffers[family].extend(block)

    stem = edf_path.stem
    for _spec, canonical, family in channel_specs:
        payload = bytes(buffers[family])
        total_samples = len(payload) // 2
        matched_label = None
        for idx, triple in match_by_index.items():
            if triple[1] == family:
                matched_label = triple[2]
                break
        lengths = deterministic_lengths(total_samples, min_samples, max_samples, f"{shard_seed}:{rel}:{family}")
        byte_off = 0
        for shard_idx, n_samples in enumerate(lengths):
            part_bytes = n_samples * 2
            if len(lengths) == 1:
                fname = f"{stem}_1d_n{n_samples}.bin"
            else:
                fname = f"{stem}_part{shard_idx:02d}_1d_n{n_samples}.bin"
            out = samples_dir / family / fname
            out.write_bytes(payload[byte_off:byte_off + part_bytes])
            byte_off += part_bytes
            rows.append({
                "dataset_id": "chbmit_physionet",
                "series_id": family,
                "sample_path": str(out.relative_to(repo / data_dir)),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": out.stat().st_size,
                "value_count": n_samples,
            })
            inventory.append((rel, family, matched_label, n_samples, out.stat().st_size, out.name))

filter_dir.mkdir(parents=True, exist_ok=True)
with (filter_dir / "inventory.tsv").open("w", encoding="utf-8") as fh:
    fh.write("record\tseries_id\tmatched_label\tsamples\tbytes\toutput_file\n")
    for row in inventory:
        fh.write("\t".join(str(x) for x in row) + "\n")

index_dir.mkdir(parents=True, exist_ok=True)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
