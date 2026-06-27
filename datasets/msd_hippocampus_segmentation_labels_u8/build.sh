#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="msd_hippocampus_segmentation_labels_u8"
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

MAX_LABELS="${MSD_HIPPOCAMPUS_MAX_LABELS:-0}"
MAX_PRIMARY_BYTES="${MSD_HIPPOCAMPUS_MAX_PRIMARY_BYTES:-950000000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MAX_LABELS MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import struct
import tarfile
from collections import Counter
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
max_labels = int(os.environ["MAX_LABELS"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "msd_hippocampus_segmentation_labels_u8"
FAMILY = "hippocampus_segmentation_label_u8"
ARCHIVE = download_dir / "Task04_Hippocampus.tar"

DATATYPES = {
    2: ("uint8", 1, "B"),
    4: ("int16", 2, "h"),
    8: ("int32", 4, "i"),
    256: ("int8", 1, "b"),
    512: ("uint16", 2, "H"),
    768: ("uint32", 4, "I"),
}


def parse_nifti_u8(blob: bytes, name: str) -> tuple[bytes, dict[str, object]]:
    try:
        data = gzip.decompress(blob)
    except gzip.BadGzipFile as exc:
        raise ValueError("not a gzipped NIfTI file") from exc
    if len(data) < 352:
        raise ValueError("decompressed NIfTI too small")
    if struct.unpack_from("<I", data, 0)[0] == 348:
        endian = "<"
        endianness = "little"
    elif struct.unpack_from(">I", data, 0)[0] == 348:
        endian = ">"
        endianness = "big"
    else:
        raise ValueError("bad NIfTI sizeof_hdr")
    magic = data[344:348]
    if magic not in {b"n+1\0", b"n+2\0"}:
        raise ValueError(f"unsupported NIfTI magic {magic!r}")
    dims = struct.unpack_from(endian + "8h", data, 40)
    rank = int(dims[0])
    if rank != 3:
        raise ValueError(f"expected 3D label volume, got rank={rank}")
    shape = [int(v) for v in dims[1:4]]
    if any(v <= 0 for v in shape):
        raise ValueError(f"invalid shape {shape}")
    value_count = math.prod(shape)
    datatype = struct.unpack_from(endian + "h", data, 70)[0]
    bitpix = struct.unpack_from(endian + "h", data, 72)[0]
    vox_offset = int(struct.unpack_from(endian + "f", data, 108)[0])
    scl_slope = struct.unpack_from(endian + "f", data, 112)[0]
    scl_inter = struct.unpack_from(endian + "f", data, 116)[0]
    if datatype not in DATATYPES:
        raise ValueError(f"unsupported NIfTI datatype {datatype}")
    type_name, item_size, fmt = DATATYPES[datatype]
    if bitpix != item_size * 8:
        raise ValueError(f"datatype/bitpix mismatch datatype={datatype} bitpix={bitpix}")
    if scl_slope not in (0.0, 1.0) or scl_inter != 0.0:
        raise ValueError(f"scaled labels rejected slope={scl_slope} intercept={scl_inter}")
    expected_bytes = value_count * item_size
    payload = data[vox_offset : vox_offset + expected_bytes]
    if len(payload) != expected_bytes:
        raise ValueError(f"truncated payload expected={expected_bytes} got={len(payload)}")
    if datatype == 2:
        out = bytes(payload)
    else:
        values = struct.iter_unpack(endian + fmt, payload)
        converted = bytearray()
        for (value,) in values:
            if value < 0 or value > 255:
                raise ValueError(f"label out of uint8 range: {value}")
            converted.append(int(value))
        out = bytes(converted)
    meta = {
        "source_datatype": type_name,
        "source_datatype_code": datatype,
        "source_bitpix": bitpix,
        "source_endianness": endianness,
        "sample_shape": shape,
        "value_count": value_count,
        "vox_offset": vox_offset,
    }
    return out, meta


if not ARCHIVE.exists():
    raise SystemExit(f"missing archive: {ARCHIVE}")
if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / FAMILY
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows: list[dict[str, object]] = []
records: list[dict[str, object]] = []
skipped_invalid = 0
skipped_constant = 0
total_bytes = 0

with tarfile.open(ARCHIVE, "r") as tf:
    members = sorted(
        [
            m
            for m in tf.getmembers()
            if m.isfile()
            and "/labelsTr/" in m.name
            and m.name.endswith(".nii.gz")
            and not Path(m.name).name.startswith("._")
        ],
        key=lambda m: m.name,
    )
    if max_labels > 0:
        members = members[:max_labels]
    for member in members:
        extracted = tf.extractfile(member)
        if extracted is None:
            skipped_invalid += 1
            continue
        try:
            labels, meta = parse_nifti_u8(extracted.read(), member.name)
        except ValueError as exc:
            skipped_invalid += 1
            print(f"skip_invalid member={member.name} reason={exc}")
            continue
        histogram = Counter(labels)
        if len(histogram) <= 1:
            skipped_constant += 1
            continue
        if total_bytes + len(labels) > max_primary_bytes:
            break
        stem = Path(member.name).name.removesuffix(".nii.gz")
        out = out_dir / f"{stem}_labels_u8_{meta['sample_shape'][0]}x{meta['sample_shape'][1]}x{meta['sample_shape'][2]}.bin"
        out.write_bytes(labels)
        total_bytes += len(labels)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": FAMILY,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(labels),
            "value_count": int(meta["value_count"]),
            "sample_geometry": "3d_label_volume",
            "sample_rank": 3,
            "sample_shape": meta["sample_shape"],
            "sample_axes": ["i", "j", "k"],
            "source_archive_member": member.name,
            "source_datatype": meta["source_datatype"],
            "source_datatype_code": meta["source_datatype_code"],
            "source_bitpix": meta["source_bitpix"],
            "source_endianness": meta["source_endianness"],
            "natural_record_kind": "nifti_label_volume",
        }
        rows.append(row)
        records.append({
            "source_archive_member": member.name,
            "source_bytes_compressed": member.size,
            "sample_path": row["sample_path"],
            "sample_bytes": len(labels),
            "value_count": int(meta["value_count"]),
            "shape": meta["sample_shape"],
            "source_datatype": meta["source_datatype"],
            "distinct_values": len(histogram),
            "min_value": min(histogram),
            "max_value": max(histogram),
            "histogram": {str(k): int(v) for k, v in sorted(histogram.items())},
        })

if len(rows) < 5:
    raise SystemExit(
        f"only {len(rows)} qualifying labels; skipped_invalid={skipped_invalid} "
        f"skipped_constant={skipped_constant}"
    )
counts = sorted(int(r["value_count"]) for r in rows)
stats = {
    "dataset_id": DATASET_ID,
    "samples": len(rows),
    "skipped_invalid": skipped_invalid,
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
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(rows)} bytes={total_bytes} median={stats['median_value_count']} "
    f"range=[{stats['min_value_count']},{stats['max_value_count']}]"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
