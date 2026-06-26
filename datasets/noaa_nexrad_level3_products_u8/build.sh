#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_nexrad_level3_products_u8"
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
MIN_SAMPLE_BYTES="${NEXRAD_L3_MIN_SAMPLE_BYTES:-1000}"
MAX_PRIMARY_BYTES="${NEXRAD_L3_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_SAMPLE_BYTES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
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
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "noaa_nexrad_level3_products_u8"
FAMILY = "nexrad_level3_nids_payload_u8"


def strip_text_header(data: bytes) -> tuple[bytes, int]:
    probe = data[:512]
    for marker in (b"\r\r\n", b"\n\n"):
        pos = probe.find(marker)
        if 0 <= pos <= 256:
            prefix = probe[:pos]
            if prefix and all(b in b"\r\n\t " or 32 <= b < 127 for b in prefix):
                start = pos + len(marker)
                return data[start:], start
    return data, 0


plan = download_dir / "download_plan.tsv"
if not plan.exists():
    raise SystemExit(f"missing download plan: {plan}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
total_bytes = 0
skipped_tiny = 0
skipped_constant = 0
product_codes: set[str] = set()

with plan.open("r", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        product_codes.add(row["product_code"])
        source = download_dir / row["local_path"]
        if not source.is_file():
            raise SystemExit(f"missing product file {source}")
        payload, header_bytes = strip_text_header(source.read_bytes())
        if len(payload) < min_sample_bytes:
            skipped_tiny += 1
            continue
        if len(set(payload[: min(len(payload), 65536)])) <= 1:
            skipped_constant += 1
            continue
        if total_bytes + len(payload) > max_primary_bytes:
            break
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(row["local_path"]).name)
        out = out_dir / f"{safe}_n{len(payload):08d}.bin"
        out.write_bytes(payload)
        total_bytes += len(payload)
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
            "sample_geometry": "nids_product_message",
            "sample_rank": 1,
            "source_name": row["name"],
            "source_key": row["key"],
            "source_url": row["url"],
            "product_code": row["product_code"],
            "stripped_transport_header_bytes": header_bytes,
            "natural_record_kind": "nexrad_level3_product_file",
        })
        records.append({
            "source_name": row["name"],
            "product_code": row["product_code"],
            "source_bytes": source.stat().st_size,
            "payload_bytes": len(payload),
            "stripped_transport_header_bytes": header_bytes,
            "first_payload_bytes_hex": payload[:16].hex(),
        })

if len(product_codes) != 1:
    raise SystemExit(f"mixed product codes are not allowed: {sorted(product_codes)}")
if len(index_rows) < 5:
    raise SystemExit(f"only {len(index_rows)} qualifying products; skipped_tiny={skipped_tiny} skipped_constant={skipped_constant}")

counts = sorted(int(r["value_count"]) for r in index_rows)
stats = {
    "dataset_id": DATASET_ID,
    "product_code": next(iter(product_codes)),
    "samples": len(index_rows),
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
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        out.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built product={stats['product_code']} samples={len(index_rows)} "
    f"bytes={total_bytes} median={stats['median_value_count']} "
    f"range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
