#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bam_read_mapq_u8"
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
from __future__ import annotations

import json
import os
import shutil
import statistics
import zlib
from array import array
from pathlib import Path

DATASET_ID = "bam_read_mapq_u8"
SERIES_ID = "bam_read_mapq_u8"
MAX_PRIMARY_BYTES = int(os.environ.get("BAM_MAX_PRIMARY_BYTES", "1000000000"))
MIN_PRIMARY_BYTES = int(os.environ.get("BAM_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_PRIMARY_VALUES = int(os.environ.get("BAM_MIN_PRIMARY_VALUES", "100000"))
MIN_MEDIAN_VALUES = int(os.environ.get("BAM_MIN_MEDIAN_VALUES", "10000"))
MIN_READS_PER_SAMPLE = int(os.environ.get("BAM_MIN_READS_PER_SAMPLE", "10000"))
MIN_SAMPLE_COUNT = int(os.environ.get("BAM_MIN_SAMPLE_COUNT", "5"))
# A BAM record is at least 32 bytes of fixed fields; guard against mis-parse.
MIN_RECORD_BYTES = 32
MAX_RECORD_BYTES = int(os.environ.get("BAM_MAX_RECORD_BYTES", "10000000"))

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
out_dir = samples_dir / SERIES_ID


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def bgzf_decompress_prefix(data: bytes) -> bytes:
    """Concatenate the decompressed payloads of every COMPLETE BGZF block in a
    (possibly truncated) BAM prefix. BGZF = concatenated gzip members each
    carrying a 'BC' extra subfield with the block size; the final partial block
    of a byte-range prefix is dropped."""
    out = []
    n = len(data)
    pos = 0
    while pos + 12 <= n:
        if data[pos] != 0x1F or data[pos + 1] != 0x8B or (data[pos + 3] & 0x04) == 0:
            break  # not a BGZF/gzip-with-FEXTRA block
        xlen = int.from_bytes(data[pos + 10 : pos + 12], "little")
        if pos + 12 + xlen > n:
            break
        extra = data[pos + 12 : pos + 12 + xlen]
        bsize = None
        i = 0
        while i + 4 <= len(extra):
            si1, si2 = extra[i], extra[i + 1]
            slen = int.from_bytes(extra[i + 2 : i + 4], "little")
            if si1 == 66 and si2 == 67 and slen == 2:
                bsize = int.from_bytes(extra[i + 4 : i + 6], "little") + 1
                break
            i += 4 + slen
        if bsize is None or bsize <= 12 + xlen + 8:
            break
        if pos + bsize > n:
            break  # truncated final block in the prefix
        cdata = data[pos + 12 + xlen : pos + bsize - 8]
        try:
            out.append(zlib.decompress(cdata, -15))
        except zlib.error:
            break
        pos += bsize
    return b"".join(out)


def bam_mapq_stream(uncompressed: bytes) -> array:
    """Walk a decompressed BAM stream and return the per-read MAPQ bytes (uint8).
    Stops cleanly at the truncated tail of a prefix."""
    u = uncompressed
    n = len(u)
    if n < 12 or u[:4] != b"BAM\x01":
        raise ValueError("not a BAM stream (missing 'BAM\\1' magic)")
    l_text = int.from_bytes(u[4:8], "little")
    off = 8 + l_text
    if off + 4 > n:
        raise ValueError("BAM header text truncated before reference list")
    n_ref = int.from_bytes(u[off : off + 4], "little")
    off += 4
    for _ in range(n_ref):
        if off + 4 > n:
            raise ValueError("BAM reference list truncated")
        l_name = int.from_bytes(u[off : off + 4], "little")
        off += 4 + l_name + 4  # name + l_ref
        if off > n:
            raise ValueError("BAM reference list truncated")
    mapq = array("B")
    while off + 4 <= n:
        block_size = int.from_bytes(u[off : off + 4], "little")
        if block_size < MIN_RECORD_BYTES or block_size > MAX_RECORD_BYTES:
            break  # implausible -> truncated tail or mis-parse
        end = off + 4 + block_size
        if end > n:
            break  # truncated final record in the prefix
        mapq.append(u[off + 4 + 9])  # MAPQ = body byte 9 (after refID,pos,l_read_name)
        off = end
    return mapq


def read_plan() -> list[dict]:
    plan = download_dir / "download_plan.tsv"
    if not plan.exists():
        raise SystemExit(f"missing download plan: {plan}; run download.sh first")
    rows = []
    for line in plan.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append({"local_name": parts[0], "url": parts[1] if len(parts) > 1 else "", "bytes": parts[2] if len(parts) > 2 else ""})
    return rows


reset_dir(out_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
total_bytes = 0
dropped_constant = 0
dropped_small = 0

for sample_index, plan_row in enumerate(read_plan(), start=1):
    source = download_dir / str(plan_row["local_name"])
    if not source.exists():
        raise SystemExit(f"missing download: {source}")
    uncompressed = bgzf_decompress_prefix(source.read_bytes())
    mapq = bam_mapq_stream(uncompressed)
    if len(mapq) < MIN_READS_PER_SAMPLE:
        dropped_small += 1
        print(f"drop small sample: {source.name} reads={len(mapq)}")
        continue
    if mapq.count(mapq[0]) == len(mapq):
        dropped_constant += 1
        print(f"drop constant sample: {source.name}")
        continue
    payload = mapq.tobytes()
    total_bytes += len(payload)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
    stem = source.stem
    out = out_dir / f"{sample_index:02d}_{stem}_mapq.bin"
    out.write_bytes(payload)
    mn, mx = min(mapq), max(mapq)
    distinct = len(set(mapq))
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": len(payload),
        "value_count": len(mapq),
        "sample_geometry": "1d_sequence",
        "sample_rank": 1,
        "sample_axes": ["read"],
        "natural_record_kind": "bam_read_mapq_stream",
        "source_path": source.as_posix(),
        "source_url": plan_row.get("url", ""),
        "read_count": len(mapq),
        "mapq_min": mn,
        "mapq_max": mx,
        "mapq_distinct": distinct,
    }
    rows.append(row)
    records.append(
        {
            "local_name": plan_row["local_name"],
            "url": plan_row.get("url", ""),
            "source_bytes": source.stat().st_size,
            "sample_path": row["sample_path"],
            "read_count": len(mapq),
            "sample_bytes": len(payload),
            "mapq_min": mn,
            "mapq_max": mx,
            "mapq_distinct": distinct,
        }
    )
    print(f"built {source.name}: reads={len(mapq)} mapq_range={mn}-{mx} distinct={distinct}")

if dropped_constant or dropped_small:
    print(f"dropped samples: constant={dropped_constant} too_small={dropped_small}")

sizes = [int(r["sample_size_bytes"]) for r in rows]
values = [int(r["value_count"]) for r in rows]
if not rows:
    raise RuntimeError("no BAM MAPQ samples survived")
if len(rows) < MIN_SAMPLE_COUNT:
    raise RuntimeError(f"expected at least {MIN_SAMPLE_COUNT} BAM samples, built {len(rows)}")
if sum(sizes) < MIN_PRIMARY_BYTES or sum(values) < MIN_PRIMARY_VALUES:
    raise RuntimeError("primary payload below aggregate floor")
if statistics.median(values) < MIN_MEDIAN_VALUES:
    raise RuntimeError("median sample below floor")

stats = {
    "dataset_id": DATASET_ID,
    "record_count": len(records),
    "total_primary_bytes": sum(sizes),
    "total_primary_values": sum(values),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_values={sum(values)} primary_bytes={sum(sizes)}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
