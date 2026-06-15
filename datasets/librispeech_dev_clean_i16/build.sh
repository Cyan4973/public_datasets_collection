#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="librispeech_dev_clean_i16"
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
import subprocess
import tarfile
from collections import Counter
from pathlib import Path

DATASET_ID = "librispeech_dev_clean_i16"
SERIES_ID = "librispeech_dev_clean_pcm16"
MAX_PRIMARY_BYTES = 1_000_000_000
SAMPLE_RATE_HZ = 16000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "dev-clean.tar.gz"

decoder = shutil.which("flac")
decoder_kind = "flac"
if decoder is None:
    decoder = shutil.which("ffmpeg")
    decoder_kind = "ffmpeg"
if decoder is None:
    raise SystemExit("missing decoder: install `flac` or `ffmpeg` before building this recipe")
if not archive.exists():
    raise SystemExit(f"missing archive: {archive}")

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

reset_dir(extract_dir)
reset_dir(samples_dir / SERIES_ID)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

with tarfile.open(archive, "r:gz") as tf:
    members = [member for member in tf.getmembers() if member.isfile() and member.name.startswith("LibriSpeech/dev-clean/")]
    if not members:
        raise SystemExit("archive contains no LibriSpeech/dev-clean files")
    tf.extractall(extract_dir, members=members)

flacs = sorted((extract_dir / "LibriSpeech" / "dev-clean").glob("*/*/*.flac"))
if len(flacs) < 2500:
    raise SystemExit(f"too few extracted FLAC utterances: {len(flacs)}")

out_dir = samples_dir / SERIES_ID
rows = []
records = []
for flac_path in flacs:
    rel_parts = flac_path.relative_to(extract_dir / "LibriSpeech" / "dev-clean").parts
    speaker, chapter, name = rel_parts
    out = out_dir / speaker / chapter / f"{Path(name).stem}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    if decoder_kind == "flac":
        cmd = [
            decoder,
            "-d",
            "--silent",
            "--force-raw-format",
            "--endian=little",
            "--sign=signed",
            "-o",
            str(out),
            str(flac_path),
        ]
    else:
        cmd = [
            decoder,
            "-v",
            "error",
            "-y",
            "-i",
            str(flac_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            str(out),
        ]
    subprocess.run(cmd, check=True)
    size = out.stat().st_size
    if size == 0 or size % 2:
        raise SystemExit(f"invalid decoded PCM size for {flac_path}: {size}")
    values = size // 2
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": size,
        "value_count": values,
        "sample_geometry": "1d_waveform",
        "sample_rank": 1,
        "sample_shape": [values],
        "sample_axes": ["time"],
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "speaker_id": speaker,
        "chapter_id": chapter,
        "source_flac": flac_path.relative_to(extract_dir).as_posix(),
    }
    rows.append(row)
    records.append({"speaker_id": speaker, "chapter_id": chapter, "utterance_id": Path(name).stem, "values": values, "bytes": size})

sizes = [row["sample_size_bytes"] for row in rows]
values = [row["value_count"] for row in rows]
total_bytes = sum(sizes)
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {total_bytes}")
if statistics.median(values) < 1000:
    raise SystemExit(f"median utterance is below floor: {statistics.median(values)} values")
if max(Counter(sizes).values()) / len(sizes) > 0.25:
    raise SystemExit("decoded utterance sizes are unexpectedly concentrated")

stats = {
    "dataset_id": DATASET_ID,
    "decoder": decoder_kind,
    "sample_count": len(rows),
    "primary_values": sum(values),
    "primary_bytes": total_bytes,
    "min_values": min(values),
    "median_values": statistics.median(values),
    "max_values": max(values),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_bytes={total_bytes} size_range={min(sizes)}/{statistics.median(sizes)}/{max(sizes)}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

