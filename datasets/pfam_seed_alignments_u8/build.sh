#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="pfam_seed_alignments_u8"
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
MIN_SAMPLE_BYTES="${PFAM_MIN_SAMPLE_BYTES:-1000}"
MAX_FAMILIES="${PFAM_MAX_FAMILIES:-0}"
MAX_PRIMARY_BYTES="${PFAM_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_SAMPLE_BYTES MAX_FAMILIES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_sample_bytes = int(os.environ["MIN_SAMPLE_BYTES"])
max_families = int(os.environ["MAX_FAMILIES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "pfam_seed_alignments_u8"
FAMILY = "pfam_seed_alignment_symbols_u8"
ACCESSION_RE = re.compile(r"^#=GF\s+AC\s+(PF\d+)")
ID_RE = re.compile(r"^#=GF\s+ID\s+(\S+)")

src = download_dir / "Pfam-A.seed.gz"
if not src.is_file():
    raise SystemExit(f"missing {src}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
fam_dir = samples_dir / FAMILY
fam_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
seen_ids: set[str] = set()
blocks_seen = 0
rows_seen = 0
qualified = 0
too_small = 0
constant = 0
total_primary_bytes = 0


def finish_block(accession: str | None, family_id: str | None, rows: list[tuple[str, str]]) -> bool:
    global qualified, too_small, constant, total_primary_bytes
    if not rows:
        return False
    sid = accession or family_id
    if sid is None:
        raise SystemExit("Stockholm block missing #=GF AC and #=GF ID")
    if sid in seen_ids:
        raise SystemExit(f"duplicate family id/accession: {sid}")
    seen_ids.add(sid)

    lengths = {len(seq) for _name, seq in rows}
    if len(lengths) != 1:
        raise SystemExit(f"unequal alignment row lengths in {sid}: {sorted(lengths)[:5]}")
    width = lengths.pop()
    if width == 0:
        raise SystemExit(f"empty alignment width in {sid}")

    try:
        payload = "".join(seq for _name, seq in rows).encode("ascii")
    except UnicodeEncodeError as exc:
        raise SystemExit(f"non-ASCII alignment symbols in {sid}") from exc
    if any(b <= 32 or b >= 127 for b in payload):
        raise SystemExit(f"unexpected control/non-ASCII symbol in {sid}")
    if len(payload) < min_sample_bytes:
        too_small += 1
        return False
    if len(set(payload)) <= 1:
        constant += 1
        return False
    if total_primary_bytes + len(payload) > max_primary_bytes:
        return True

    safe_id = sid.replace(".", "_")
    out = fam_dir / f"{safe_id}_rows{len(rows):04d}_cols{width:05d}_n{len(payload):08d}.bin"
    out.write_bytes(payload)
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": FAMILY,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(payload),
        "sample_geometry": f"alignment_{len(rows)}x{width}",
        "sample_rank": 2,
        "pfam_accession": accession,
        "pfam_id": family_id,
        "alignment_rows": len(rows),
        "alignment_columns": width,
        "natural_record_kind": "pfam_seed_stockholm_block",
    })
    total_primary_bytes += len(payload)
    qualified += 1
    if max_families > 0 and qualified >= max_families:
        return True
    return False


stop = False
accession: str | None = None
family_id: str | None = None
rows: list[tuple[str, str]] = []
in_block = False
with gzip.open(src, "rt", encoding="utf-8", errors="replace") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped == "# STOCKHOLM 1.0":
            if in_block and rows:
                raise SystemExit("new Stockholm block before previous terminator")
            in_block = True
            accession = None
            family_id = None
            rows = []
            continue
        if not in_block:
            if stripped:
                raise SystemExit(f"content outside Stockholm block: {stripped[:80]!r}")
            continue
        if stripped == "//":
            blocks_seen += 1
            rows_seen += len(rows)
            stop = finish_block(accession, family_id, rows)
            accession = None
            family_id = None
            rows = []
            in_block = False
            if stop:
                break
            continue
        if not stripped:
            continue
        m = ACCESSION_RE.match(line)
        if m:
            accession = m.group(1)
            continue
        m = ID_RE.match(line)
        if m:
            family_id = m.group(1)
            continue
        if stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 2:
            raise SystemExit(f"malformed alignment row: {stripped[:80]!r}")
        name, seq = parts
        rows.append((name, seq))

if in_block:
    raise SystemExit("unterminated final Stockholm block")
if len(index_rows) < 25:
    raise SystemExit(f"only {len(index_rows)} qualifying families")

counts = sorted(int(r["value_count"]) for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "blocks_seen": blocks_seen,
    "rows_seen": rows_seen,
    "qualified_families": len(index_rows),
    "too_small_families": too_small,
    "constant_families": constant,
    "primary_values": sum(counts),
    "primary_sample_bytes": total_primary_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "max_primary_bytes": max_primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={len(index_rows)} blocks_seen={blocks_seen} bytes={total_primary_bytes} "
    f"median={stats['median_value_count']} range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
