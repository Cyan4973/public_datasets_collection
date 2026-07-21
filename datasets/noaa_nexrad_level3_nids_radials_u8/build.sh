#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_nexrad_level3_nids_radials_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="${NEXRAD_L3_SOURCE_DOWNLOAD_DIR:-$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID}"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID download_dir=$DOWNLOAD_DIR"
MIN_SAMPLES="${NEXRAD_L3_MIN_SAMPLES:-24}"
MAX_PRIMARY_BYTES="${NEXRAD_L3_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_SAMPLES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import bz2
import csv
import json
import os
import re
import shutil
import struct
from pathlib import Path

DATASET_ID = "noaa_nexrad_level3_nids_radials_u8"
SERIES_ID = "nexrad_l3_packet16_radial_bins_u8"
PACKET_CODE = 16

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_samples = int(os.environ["MIN_SAMPLES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])


def station_from_name(name: str) -> str:
    return name.split("_", 1)[0]


def binary_start(data: bytes, product_code: str, station: str) -> int:
    marker = (product_code + station).encode("ascii") + b"\r\r\n"
    pos = data.find(marker)
    if pos < 0:
        raise ValueError("missing AWIPS product marker")
    return pos + len(marker)


def parse_product(data: bytes, product_code: str, station: str) -> dict[str, object]:
    start = binary_start(data, product_code, station)
    nids = data[start:]
    bzip_pos = nids.find(b"BZh")
    if bzip_pos < 0:
        raise ValueError("missing bzip2 symbology stream")
    prefix = nids[:bzip_pos]
    sym = bz2.decompress(nids[bzip_pos:])

    if len(sym) < 30:
        raise ValueError("symbology block too short")
    pos = 0
    divider, block_id, block_len, layer_count = struct.unpack(">HHIH", sym[pos:pos + 10])
    pos += 10
    if divider != 0xFFFF or block_id != 1 or block_len != len(sym):
        raise ValueError(f"unexpected symbology block header divider={divider} block={block_id} len={block_len}")
    if layer_count != 1:
        raise ValueError(f"expected one layer, got {layer_count}")

    layer_divider, layer_len = struct.unpack(">HI", sym[pos:pos + 6])
    pos += 6
    if layer_divider != 0xFFFF or layer_len != len(sym) - pos:
        raise ValueError(f"unexpected layer header divider={layer_divider} len={layer_len}")

    packet_code = struct.unpack(">H", sym[pos:pos + 2])[0]
    pos += 2
    if packet_code != PACKET_CODE:
        raise ValueError(f"unsupported packet code {packet_code}")

    first_bin, bin_count, i_center, j_center, scale, radial_count = struct.unpack(">hhhhHH", sym[pos:pos + 12])
    pos += 12
    if first_bin < 0 or bin_count <= 0 or radial_count <= 0:
        raise ValueError("invalid packet geometry")

    bins = bytearray()
    angles: list[int] = []
    deltas: list[int] = []
    radial_lengths: list[int] = []
    for radial_index in range(radial_count):
        if pos + 6 > len(sym):
            raise ValueError(f"truncated radial header {radial_index}")
        byte_count, start_angle, angle_delta = struct.unpack(">HHH", sym[pos:pos + 6])
        pos += 6
        if byte_count != bin_count:
            raise ValueError(f"radial {radial_index} byte_count={byte_count} != bin_count={bin_count}")
        if pos + byte_count > len(sym):
            raise ValueError(f"truncated radial data {radial_index}")
        bins.extend(sym[pos:pos + byte_count])
        pos += byte_count
        radial_lengths.append(byte_count)
        angles.append(start_angle)
        deltas.append(angle_delta)
    if pos != len(sym):
        raise ValueError(f"trailing symbology bytes: {len(sym) - pos}")
    if len(set(bins[: min(len(bins), 65536)])) <= 1:
        raise ValueError("constant decoded bin prefix")

    return {
        "bins": bytes(bins),
        "packet_code": packet_code,
        "first_bin": first_bin,
        "bin_count": bin_count,
        "radial_count": radial_count,
        "i_center": i_center,
        "j_center": j_center,
        "scale": scale,
        "angle_delta_min": min(deltas),
        "angle_delta_max": max(deltas),
        "first_angle": angles[0],
        "last_angle": angles[-1],
        "compressed_symbology_offset": start + bzip_pos,
        "compressed_prefix_bytes": len(prefix),
        "decompressed_symbology_bytes": len(sym),
        "radial_byte_count": radial_lengths[0],
    }


plan = download_dir / "download_plan.tsv"
if not plan.exists():
    raise SystemExit(f"missing download plan: {plan}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / SERIES_ID
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
product_codes: set[str] = set()
total_bytes = 0
skipped = 0

with plan.open("r", encoding="utf-8", newline="") as fh:
    for plan_row in csv.DictReader(fh, delimiter="\t"):
        product_code = plan_row["product_code"]
        product_codes.add(product_code)
        source = download_dir / plan_row["local_path"]
        if not source.is_file():
            raise SystemExit(f"missing product file: {source}")
        station = station_from_name(plan_row["name"])
        try:
            parsed = parse_product(source.read_bytes(), product_code, station)
        except Exception as exc:
            skipped += 1
            records.append({"source_name": plan_row["name"], "error": str(exc)})
            continue
        bins = parsed.pop("bins")
        if total_bytes + len(bins) > max_primary_bytes:
            break
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(plan_row["local_path"]).name)
        out = out_dir / f"{safe}_packet16_{parsed['radial_count']}x{parsed['bin_count']}.bin"
        out.write_bytes(bins)
        total_bytes += len(bins)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(bins),
            "value_count": len(bins),
            "sample_format": "raw homogeneous uint8 packet-16 radial bin matrix",
            "sample_geometry": "nids_packet16_radial_bins",
            "sample_rank": 2,
            "sample_shape": [parsed["radial_count"], parsed["bin_count"]],
            "sample_axes": ["radial", "range_bin"],
            "natural_record_kind": "nexrad_level3_packet16_product",
            "source_name": plan_row["name"],
            "source_key": plan_row["key"],
            "source_url": plan_row["url"],
            "station": station,
            "product_code": product_code,
            **parsed,
        }
        rows.append(row)
        records.append({
            "source_name": plan_row["name"],
            "product_code": product_code,
            "source_bytes": source.stat().st_size,
            "decoded_bin_bytes": len(bins),
            **parsed,
        })

if len(product_codes) != 1:
    raise SystemExit(f"mixed product codes are not allowed: {sorted(product_codes)}")
if len(rows) < min_samples:
    raise SystemExit(f"too few decoded products: {len(rows)} < {min_samples}; skipped={skipped}")

counts = sorted(int(row["value_count"]) for row in rows)
shapes = sorted({tuple(row["sample_shape"]) for row in rows})
stats = {
    "dataset_id": DATASET_ID,
    "product_code": next(iter(product_codes)),
    "samples": len(rows),
    "skipped": skipped,
    "primary_values": sum(counts),
    "primary_sample_bytes": total_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "sample_shapes": [list(shape) for shape in shapes],
    "max_primary_bytes": max_primary_bytes,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for row in sorted(rows, key=lambda item: item["sample_path"]):
        out.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built product={stats['product_code']} samples={len(rows)} "
    f"bytes={total_bytes} shape={shapes} median={stats['median_value_count']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
