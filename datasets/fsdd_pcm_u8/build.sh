#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="fsdd_pcm_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
MIN_RECORDS="${FSDD_MIN_RECORDS:-1000}"
export REPO_ROOT DATA_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_RECORDS
python3 - <<'PY'
from __future__ import annotations

import array
import json
import os
import shutil
import sys
import wave
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
data_root = repo / os.environ["DATA_DIR"]
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_records = int(os.environ["MIN_RECORDS"])

DATASET_ID = "fsdd_pcm_u8"
FAMILY = "fsdd_pcm_u8"
rec_dir = extract_dir / "free-spoken-digit-dataset-master" / "recordings"
if not rec_dir.is_dir():
    raise SystemExit(f"missing recordings dir: {rec_dir}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_fam = samples_dir / FAMILY
out_fam.mkdir(parents=True, exist_ok=True)

rows = []
dropped = 0
for wav_path in sorted(rec_dir.glob("*.wav")):
    with wave.open(str(wav_path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise SystemExit(f"unexpected wav format: {wav_path}")
        frames = wav.getnframes()
        payload = wav.readframes(frames)
    a = array.array("h")
    a.frombytes(payload)
    if sys.byteorder == "big":
        a.byteswap()
    # 16-bit signed -> unsigned 8-bit PCM (silence -> 128)
    u8 = bytes(((s + 32768) >> 8) & 0xFF for s in a)
    if len(u8) < min_records or len(set(u8)) <= 1:
        dropped += 1
        continue
    out = out_fam / f"{wav_path.stem}_n{len(u8):06d}.bin"
    out.write_bytes(u8)
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": FAMILY,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(u8),
        "sample_geometry": "sequence",
        "sample_rank": 1,
        "recording": wav_path.stem,
        "natural_record_kind": "spoken_digit_recording",
    })

if len(rows) < 5:
    raise SystemExit(f"only {len(rows)} samples qualified (dropped={dropped})")

counts = sorted(r["value_count"] for r in rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "family": FAMILY,
    "samples": len(rows),
    "dropped": dropped,
    "primary_values": sum(counts),
    "primary_sample_bytes": sum(r["sample_size_bytes"] for r in rows),
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built family={FAMILY} samples={len(rows)} dropped={dropped} "
      f"primary_values={sum(counts)} median={median} range=[{counts[0]},{counts[-1]}]")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
