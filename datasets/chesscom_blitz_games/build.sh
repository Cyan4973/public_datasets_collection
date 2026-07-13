#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="chesscom_blitz_games"
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
MIN_PLAYER_RECORDS="${CHESSCOM_MIN_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_PLAYER_RECORDS
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
pages_dir = Path(os.environ["DOWNLOAD_DIR"]) / "pages"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_records = int(os.environ["MIN_PLAYER_RECORDS"])

DATASET_ID = "chesscom_blitz_games"
U16_MAX = 0xFFFF
# family -> declared (numeric_kind, bit_width, struct code)
FAMILIES = {
    "chesscom_blitz_rating_u16": ("uint", 16, "H"),
    "chesscom_blitz_plies_u16": ("uint", 16, "H"),
}

if not pages_dir.is_dir():
    raise SystemExit(f"missing pages dir: {pages_dir}")

# Per player (one chronological stream each), keep only standard rated blitz games.
ratings = defaultdict(list)  # player -> [white,black, white,black, ...] in game order
plies = defaultdict(list)    # player -> [plies_per_game ...]
games_total = 0
games_kept = 0

# filenames are "<player>__<yyyy>_<mm>.json"; sort sorts each player chronologically.
for path in sorted(pages_dir.glob("*__*.json")):
    player = path.name.split("__", 1)[0]
    try:
        games = json.loads(path.read_text(encoding="utf-8")).get("games", [])
    except Exception:
        continue
    for g in games:
        games_total += 1
        if g.get("time_class") != "blitz" or g.get("rules") != "chess":
            continue
        if not g.get("rated", False):
            continue
        try:
            wr = int(g["white"]["rating"])
            br = int(g["black"]["rating"])
        except (KeyError, TypeError, ValueError):
            continue
        tcn = g.get("tcn")
        if not isinstance(tcn, str) or not tcn:
            continue
        ply = len(tcn) // 2  # TCN encodes 2 chars per half-move
        if not (0 < wr <= U16_MAX and 0 < br <= U16_MAX and 0 < ply <= U16_MAX):
            continue
        ratings[player].extend((wr, br))
        plies[player].append(ply)
        games_kept += 1

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

FAMILY_SOURCE = {
    "chesscom_blitz_rating_u16": ratings,
    "chesscom_blitz_plies_u16": plies,
}

index_rows = []
fam_summary = {}
for fam, (kind, bits, code) in FAMILIES.items():
    src = FAMILY_SOURCE[fam]
    qualifying = sorted(p for p, vals in src.items()
                        if len(vals) >= min_records and len(set(vals)) > 1)
    if len(qualifying) < 5:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for player in qualifying:
        vals = src[player]
        out = samples_dir / fam / f"{fam}_{player}_n{len(vals):06d}.bin"
        out.write_bytes(struct.pack("<" + code * len(vals), *vals))
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "player": player,
            "natural_record_kind": "chesscom_player_blitz_stream",
        })
    fam_summary[fam] = len(qualifying)

if not fam_summary:
    raise SystemExit(
        f"no family qualified (games_total={games_total} games_kept={games_kept}); "
        f"need >=5 players with >={min_records} values")

primary_values = sum(r["value_count"] for r in index_rows)
primary_bytes = sum(r["sample_size_bytes"] for r in index_rows)
counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "families": fam_summary,
    "samples": len(index_rows),
    "games_total": games_total,
    "games_kept": games_kept,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_summary} samples={len(index_rows)} "
    f"games_kept={games_kept}/{games_total} primary_values={primary_values} "
    f"median={median} range=[{counts[0]},{counts[-1]}]")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
