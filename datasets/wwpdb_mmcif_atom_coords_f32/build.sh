#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wwpdb_mmcif_atom_coords_f32"
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

MIN_ATOMS="${WWPDB_MIN_ATOMS:-100}"
MAX_PRIMARY_BYTES="${WWPDB_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_ATOMS MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import shlex
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_atoms = int(os.environ["MIN_ATOMS"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "wwpdb_mmcif_atom_coords_f32"
FAMILY = "atom_cartesian_xyz_f32"


def tokenize_mmcif_line(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def parse_coords(text: str) -> list[tuple[float, float, float]]:
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_":
            i += 1
            continue
        i += 1
        tags: list[str] = []
        while i < len(lines) and lines[i].lstrip().startswith("_"):
            tags.append(lines[i].strip().split()[0])
            i += 1
        if not tags or not any(tag.startswith("_atom_site.") for tag in tags):
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("loop_", "#", "_")):
                i += 1
            continue
        try:
            x_idx = tags.index("_atom_site.Cartn_x")
            y_idx = tags.index("_atom_site.Cartn_y")
            z_idx = tags.index("_atom_site.Cartn_z")
        except ValueError:
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("loop_", "#", "_")):
                i += 1
            continue
        coords: list[tuple[float, float, float]] = []
        row: list[str] = []
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()
            if not stripped or stripped == "#":
                i += 1
                break
            if stripped == "loop_" or stripped.startswith("_"):
                break
            if stripped.startswith(";"):
                raise ValueError("semicolon multiline values inside atom_site loop are unsupported")
            row.extend(tokenize_mmcif_line(raw))
            while len(row) >= len(tags):
                current = row[: len(tags)]
                row = row[len(tags) :]
                try:
                    values = [current[x_idx], current[y_idx], current[z_idx]]
                    if any(v in {".", "?"} for v in values):
                        raise ValueError("missing coordinate token")
                    x, y, z = (float(v) for v in values)
                except Exception as exc:
                    raise ValueError(f"invalid coordinate row: {current}") from exc
                if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                    raise ValueError("non-finite coordinate")
                coords.append((x, y, z))
            i += 1
        if coords:
            return coords
    raise ValueError("no atom_site Cartesian coordinate loop found")


plan = download_dir / "download_plan.tsv"
if not plan.exists():
    raise SystemExit(f"missing download plan: {plan}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_invalid = 0
skipped_tiny = 0
skipped_constant = 0
total_bytes = 0

with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        source = download_dir / row["local_path"]
        if not source.is_file():
            raise SystemExit(f"missing source {source}")
        try:
            text = gzip.open(source, "rt", encoding="utf-8", errors="replace").read()
            coords = parse_coords(text)
        except Exception as exc:
            skipped_invalid += 1
            print(f"skip_invalid pdb_id={row['pdb_id']} reason={exc}")
            continue
        atom_count = len(coords)
        if atom_count < min_atoms:
            skipped_tiny += 1
            continue
        payload = bytearray()
        min_coord = math.inf
        max_coord = -math.inf
        for xyz in coords:
            for value in xyz:
                min_coord = min(min_coord, value)
                max_coord = max(max_coord, value)
                payload.extend(struct.pack("<f", value))
        if len(set(payload[: min(len(payload), 65536)])) <= 1 or min_coord == max_coord:
            skipped_constant += 1
            continue
        if total_bytes + len(payload) > max_primary_bytes:
            break
        pdb_id = row["pdb_id"]
        out = out_dir / f"{pdb_id}_atom_xyz_f32_n{atom_count:08d}.bin"
        out.write_bytes(payload)
        total_bytes += len(payload)
        index_row = {
            "dataset_id": DATASET_ID,
            "series_id": FAMILY,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(payload),
            "value_count": atom_count * 3,
            "sample_geometry": "3d_point_set_xyz",
            "sample_rank": 2,
            "sample_shape": [atom_count, 3],
            "sample_axes": ["atom", "xyz"],
            "source_pdb_id": pdb_id,
            "source_url": row["url"],
            "source_path": source.as_posix(),
            "atom_count": atom_count,
            "natural_record_kind": "mmcif_structure",
        }
        rows.append(index_row)
        records.append({
            "pdb_id": pdb_id,
            "source_bytes": source.stat().st_size,
            "atom_count": atom_count,
            "value_count": atom_count * 3,
            "sample_bytes": len(payload),
            "min_coord": min_coord,
            "max_coord": max_coord,
        })

if len(rows) < 2:
    raise SystemExit(
        f"only {len(rows)} qualifying structures; skipped_invalid={skipped_invalid} "
        f"skipped_tiny={skipped_tiny} skipped_constant={skipped_constant}"
    )
counts = sorted(int(r["value_count"]) for r in rows)
stats = {
    "dataset_id": DATASET_ID,
    "samples": len(rows),
    "skipped_invalid": skipped_invalid,
    "skipped_tiny": skipped_tiny,
    "skipped_constant": skipped_constant,
    "primary_values": sum(counts),
    "primary_sample_bytes": total_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "max_primary_bytes": max_primary_bytes,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for row in sorted(rows, key=lambda r: r["sample_path"]):
        out.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(rows)} bytes={total_bytes} median_values={stats['median_value_count']} "
    f"atoms_range=[{min(r['atom_count'] for r in records)},{max(r['atom_count'] for r in records)}]"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
