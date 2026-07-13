#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="maestro_midi_notes"
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
MIN_NOTES="${MAESTRO_MIN_NOTES:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_NOTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
import zipfile
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_notes = int(os.environ["MIN_NOTES"])

DATASET_ID = "maestro_midi_notes"
FAM_PITCH = "midi_note_pitch_u8"
FAM_VEL = "midi_note_velocity_u8"

src = download_dir / "maestro-v3.0.0-midi.zip"
if not src.is_file():
    raise SystemExit(f"missing {src}")


def read_vlq(buf: bytes, i: int) -> tuple[int, int]:
    val = 0
    while i < len(buf):
        b = buf[i]; i += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return val, i


def parse_midi(data: bytes) -> tuple[list, list]:
    """Return (pitches, velocities) from note-on events (velocity>0)."""
    pitches: list[int] = []
    velocities: list[int] = []
    if data[:4] != b"MThd":
        return pitches, velocities
    n = len(data)
    i = 8 + int.from_bytes(data[4:8], "big")  # skip header chunk
    while i + 8 <= n:
        ctype = data[i:i + 4]
        clen = int.from_bytes(data[i + 4:i + 8], "big")
        i += 8
        chunk = data[i:i + clen]
        i += clen
        if ctype != b"MTrk":
            continue
        j = 0
        status = 0
        m = len(chunk)
        while j < m:
            _dt, j = read_vlq(chunk, j)
            if j >= m:
                break
            b = chunk[j]
            if b & 0x80:
                status = b
                j += 1
            elif status == 0:
                break  # running status with no prior status -> malformed
            if status == 0xFF:  # meta event
                if j >= m:
                    break
                j += 1  # meta type
                length, j = read_vlq(chunk, j)
                j += length
            elif status in (0xF0, 0xF7):  # sysex
                length, j = read_vlq(chunk, j)
                j += length
            else:
                hi = status & 0xF0
                if hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):  # two data bytes
                    if j + 1 >= m:
                        break
                    d1 = chunk[j]; d2 = chunk[j + 1]; j += 2
                    if hi == 0x90 and d2 > 0 and 0 <= d1 <= 127:
                        pitches.append(d1)
                        velocities.append(d2)
                elif hi in (0xC0, 0xD0):  # one data byte
                    j += 1
                else:
                    break
    return pitches, velocities


if samples_dir.exists():
    shutil.rmtree(samples_dir)
(samples_dir / FAM_PITCH).mkdir(parents=True, exist_ok=True)
(samples_dir / FAM_VEL).mkdir(parents=True, exist_ok=True)


def slug(name: str) -> str:
    base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return "".join(c if c.isalnum() else "_" for c in base).strip("_")[:80]


index_rows = []
fam_counts = {FAM_PITCH: 0, FAM_VEL: 0}
files_total = 0
files_kept = 0
seen_slugs = set()

with zipfile.ZipFile(src) as z:
    members = sorted(n for n in z.namelist() if n.lower().endswith((".midi", ".mid")))
    for name in members:
        files_total += 1
        try:
            data = z.read(name)
        except Exception:
            continue
        pitches, velocities = parse_midi(data)
        if len(pitches) < min_notes:
            continue
        s = slug(name)
        if s in seen_slugs:
            s = f"{s}_{files_total}"
        seen_slugs.add(s)
        files_kept += 1
        for fam, vals in ((FAM_PITCH, pitches), (FAM_VEL, velocities)):
            if len(set(vals)) <= 1:
                continue
            out = samples_dir / fam / f"{fam}_{s}_n{len(vals):06d}.bin"
            out.write_bytes(bytes(vals))  # uint8 little-endian == raw bytes
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": fam,
                "role": "primary",
                "sample_path": out.relative_to(data_root).as_posix(),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": out.stat().st_size,
                "value_count": len(vals),
                "sample_geometry": "sequence",
                "sample_rank": 1,
                "performance": name,
                "natural_record_kind": "midi_performance",
            })
            fam_counts[fam] += 1

if fam_counts[FAM_PITCH] < 5 or fam_counts[FAM_VEL] < 5:
    raise SystemExit(f"too few samples per family: {fam_counts} (files_kept={files_kept})")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_counts,
    "samples": len(index_rows),
    "files_total": files_total,
    "files_kept": files_kept,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_counts} samples={len(index_rows)} files_kept={files_kept}/{files_total} "
    f"primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
