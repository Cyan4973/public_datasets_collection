#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nsynth_test_notes_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import statistics
import tarfile
import wave
from collections import Counter
from pathlib import Path

DATASET_ID = "nsynth_test_notes_i16"
SERIES_ID = "nsynth_test_note_pcm16"
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "nsynth-test.jsonwav.tar.gz"
if not archive.exists():
    raise SystemExit(f"missing archive: {archive}")

for path in [extract_dir, samples_dir / SERIES_ID]:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

with tarfile.open(archive, "r:gz") as tf:
    members = [member for member in tf.getmembers() if member.isfile() and (member.name.endswith(".wav") or member.name.endswith("examples.json"))]
    tf.extractall(extract_dir, members=members, filter="data")

wavs = sorted(extract_dir.glob("**/audio/*.wav"))
metadata_files = sorted(extract_dir.glob("**/examples.json"))
if len(wavs) < 4000:
    raise SystemExit(f"too few WAV files: {len(wavs)}")
metadata = json.loads(metadata_files[0].read_text(encoding="utf-8")) if metadata_files else {}
if len(metadata) < 4000:
    raise SystemExit(f"too few metadata rows: {len(metadata)}")

out_dir = samples_dir / SERIES_ID
rows = []
records = []
for wav_path in wavs:
    with wave.open(str(wav_path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        frames = wav.getnframes()
        framerate = wav.getframerate()
        payload = wav.readframes(frames)
    if channels != 1 or width != 2:
        raise SystemExit(f"unexpected WAV format: {wav_path} channels={channels} width={width}")
    if len(payload) != frames * width * channels or not payload:
        raise SystemExit(f"invalid WAV payload: {wav_path}")
    note_id = wav_path.stem
    out = out_dir / f"{note_id}.bin"
    out.write_bytes(payload)
    meta = metadata.get(note_id, {})
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(payload),
        "value_count": frames,
        "sample_geometry": "1d_waveform",
        "sample_rank": 1,
        "sample_shape": [frames],
        "sample_axes": ["time"],
        "note_id": note_id,
        "framerate": framerate,
        "instrument_family": meta.get("instrument_family_str", ""),
        "pitch": meta.get("pitch", ""),
    }
    rows.append(row)
    records.append({"note_id": note_id, "frames": frames, "bytes": len(payload), "framerate": framerate, "instrument_family": row["instrument_family"], "pitch": row["pitch"]})

sizes = [row["sample_size_bytes"] for row in rows]
total = sum(sizes)
if total > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {total}")
if statistics.median(row["value_count"] for row in rows) < 1000:
    raise SystemExit("median note sample below floor")
stats = {
    "dataset_id": DATASET_ID,
    "sample_count": len(rows),
    "primary_values": sum(row["value_count"] for row in rows),
    "primary_bytes": total,
    "same_size_fraction": max(Counter(sizes).values()) / len(sizes),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_bytes={total} size_range={min(sizes)}/{statistics.median(sizes)}/{max(sizes)}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
