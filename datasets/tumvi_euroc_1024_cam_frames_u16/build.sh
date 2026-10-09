#!/usr/bin/env bash
# Decode the pinned cam1 PNG members from the local tar prefixes into raw
# little-endian uint16 1024x1024 frames (values exactly as published).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tumvi_euroc_1024_cam_frames_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I - "$RECIPE_DIR/scripts" "$DATA_ROOT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import tumvi_lib as L

data_root = Path(sys.argv[2])
download_dir = data_root / "downloads" / L.DATASET_ID
filter_dir = data_root / "filtered" / L.DATASET_ID
index_dir = data_root / "index" / L.DATASET_ID
samples_root = data_root / "samples" / L.DATASET_ID
out_dir = samples_root / L.SERIES_ID
MIN_FRAMES = int(os.environ.get("TUMVI_MIN_FRAMES", "200"))
MAX_PRIMARY_BYTES = 1_000_000_000

rows = L.load_members(Path(sys.argv[1]) / "members.tsv")
shutil.rmtree(samples_root, ignore_errors=True)
out_dir.mkdir(parents=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index = []
skipped = []
total = 0
for tar, info in L.tar_prefixes(rows).items():
    p = download_dir / f"{tar}.prefix"
    if not p.is_file():
        raise SystemExit(f"missing {p}; run download.sh first")
    buf = p.read_bytes()
    if len(buf) != info["prefix_bytes"]:
        raise SystemExit(f"{tar}: prefix size {len(buf)} != {info['prefix_bytes']}")
    rx = L.member_regex(info["sequence"])
    found = {}
    for name, typ, off, size in L.walk_tar_prefix(buf):
        if typ == b"5":
            continue
        if typ not in (b"0", b"\0") or not rx.match(name):
            raise SystemExit(f"{tar}: unexpected member {name!r} (only mav0/cam1/data/*.png allowed)")
        found[name] = (off, size)
    if list(found) != [m["member"] for m in info["members"]]:
        raise SystemExit(f"{tar}: member list differs from pinned table")
    for m in info["members"]:
        off, size = found[m["member"]]
        if (off, size) != (m["data_offset"], m["size"]):
            raise SystemExit(f"{m['member']}: offset/size differ from pin")
        chunks, vals = L.decode_png_gray16(buf[off:off + size])
        if L.last_idat_crc(chunks) != m["last_idat_crc"]:
            raise SystemExit(f"{m['member']}: last IDAT CRC differs from pin")
        st = L.frame_stats(vals)
        if st["low_nibble_nonzero"]:
            raise SystemExit(f"{m['member']}: {st['low_nibble_nonzero']} pixels with nonzero low nibble (expected 12-bit MSB-aligned)")
        reason = None
        if st["min"] == st["max"]:
            reason = "constant"
        elif st["mode_fraction"] > L.MAX_MODE_FRACTION:
            reason = f"dominated_by_value_{st['mode_value']}"
        if reason:
            skipped.append({"member": m["member"], "reason": reason, **st})
            print(f"skip {m['member']} reason={reason} mode_fraction={st['mode_fraction']}")
            continue
        payload = L.le_bytes(vals)
        out = out_dir / L.sample_name(m)
        out.write_bytes(payload)
        total += len(payload)
        if total > MAX_PRIMARY_BYTES:
            raise SystemExit(f"primary output exceeds cap: {total}")
        index.append({
            "dataset_id": L.DATASET_ID,
            "series_id": L.SERIES_ID,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(payload),
            "value_count": len(vals),
            "sample_geometry": "2d_raster",
            "sample_rank": 2,
            "sample_shape": [L.HEIGHT, L.WIDTH],
            "sample_axes": ["y", "x"],
            "natural_record_kind": "tumvi_cam1_frame",
            "sequence": m["sequence"],
            "source_tar": tar,
            "source_member": m["member"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "min": st["min"],
            "max": st["max"],
            "distinct_values": st["distinct"],
            "mode_value": st["mode_value"],
            "mode_fraction": st["mode_fraction"],
        })

if len(index) < MIN_FRAMES:
    raise SystemExit(f"only {len(index)} frames (< {MIN_FRAMES}); skipped={len(skipped)}")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in index:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
stats = {
    "dataset_id": L.DATASET_ID,
    "pinned_members": len(rows),
    "frames": len(index),
    "primary_bytes": total,
    "skipped": skipped,
    "sequences": sorted({r["sequence"] for r in index}),
    "max_mode_fraction": max(r["mode_fraction"] for r in index),
    "global_min": min(r["min"] for r in index),
    "global_max": max(r["max"] for r in index),
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"built frames={len(index)} skipped={len(skipped)} sequences={len(stats['sequences'])} "
      f"primary_bytes={total} range={stats['global_min']}..{stats['global_max']} "
      f"max_mode_fraction={stats['max_mode_fraction']}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
