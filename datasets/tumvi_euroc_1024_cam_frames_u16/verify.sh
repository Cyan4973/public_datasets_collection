#!/usr/bin/env bash
# Independently re-derive every frame from the local tar prefixes and check
# the emitted samples, the index, the skip list and the manifest scope.
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
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I - "$RECIPE_DIR" "$DATA_ROOT" <<'PY'
from __future__ import annotations

import collections
import hashlib
import json
import os
import struct
import sys
import tomllib
from pathlib import Path

recipe = Path(sys.argv[1])
sys.dont_write_bytecode = True
sys.path.insert(0, str(recipe / "scripts"))
import tumvi_lib as L

data_root = Path(sys.argv[2])
download_dir = data_root / "downloads" / L.DATASET_ID
index_path = data_root / "index" / L.DATASET_ID / "samples.jsonl"
stats_path = data_root / "filtered" / L.DATASET_ID / "ingest_stats.json"
out_dir = data_root / "samples" / L.DATASET_ID / L.SERIES_ID
MIN_FRAMES = int(os.environ.get("TUMVI_MIN_FRAMES", "200"))
CHECK_MANIFEST = os.environ.get("TUMVI_SKIP_MANIFEST_CHECK", "0") != "1"

rows = L.load_members(recipe / "scripts" / "members.tsv")
index = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
by_member = {r["source_member"]: r for r in index}
if len(by_member) != len(index):
    raise SystemExit("duplicate source members in index")
if len({r["sample_path"] for r in index}) != len(index):
    raise SystemExit("duplicate sample paths in index")
skipped = {s["member"]: s["reason"] for s in stats["skipped"]}
if set(skipped) & set(by_member):
    raise SystemExit("member both skipped and emitted")
if len(index) < MIN_FRAMES:
    raise SystemExit(f"only {len(index)} frames (< {MIN_FRAMES})")

total = 0
seen_files = set()
for tar, info in L.tar_prefixes(rows).items():
    buf = (download_dir / f"{tar}.prefix").read_bytes()
    walked = [(n, o, s) for n, t, o, s in L.walk_tar_prefix(buf) if t != b"5"]
    if walked != [(m["member"], m["data_offset"], m["size"]) for m in info["members"]]:
        raise SystemExit(f"{tar}: prefix members differ from pin")
    for m in info["members"]:
        data = buf[m["data_offset"]:m["data_offset"] + m["size"]]
        chunks, vals = L.decode_png_gray16(data)
        if L.last_idat_crc(chunks) != m["last_idat_crc"]:
            raise SystemExit(f"{m['member']}: last IDAT CRC differs from pin")
        counts = collections.Counter(vals)
        mode_value, mode_count = counts.most_common(1)[0]
        mode_fraction = mode_count / len(vals)
        if any(v % 16 for v in counts):
            raise SystemExit(f"{m['member']}: value not a multiple of 16")
        if len(counts) == 1 or mode_fraction > L.MAX_MODE_FRACTION:
            if m["member"] not in skipped:
                raise SystemExit(f"{m['member']}: degenerate frame was emitted")
            continue
        if m["member"] in skipped:
            raise SystemExit(f"{m['member']}: valid frame was skipped")
        r = by_member.get(m["member"])
        if r is None:
            raise SystemExit(f"{m['member']}: missing from index")
        expect = {
            "dataset_id": L.DATASET_ID, "series_id": L.SERIES_ID, "role": "primary",
            "numeric_kind": "uint", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "value_count": 1024 * 1024,
            "sample_size_bytes": 2 * 1024 * 1024, "sample_shape": [1024, 1024],
            "natural_record_kind": "tumvi_cam1_frame", "sequence": m["sequence"],
            "min": min(counts), "max": max(counts), "distinct_values": len(counts),
            "mode_value": mode_value,
            "sample_path": f"samples/{L.DATASET_ID}/{L.SERIES_ID}/{L.sample_name(m)}",
        }
        for k, v in expect.items():
            if r.get(k) != v:
                raise SystemExit(f"{m['member']}: index field {k}={r.get(k)!r} expected {v!r}")
        path = data_root / r["sample_path"]
        raw = path.read_bytes()
        if len(raw) != 2 * 1024 * 1024:
            raise SystemExit(f"{path}: wrong size")
        # Independent big-endian -> little-endian reference from the PNG row bytes.
        ref = struct.pack(f"<{len(vals)}H", *vals)
        if raw != ref:
            raise SystemExit(f"{path}: sample bytes differ from re-decoded PNG")
        if hashlib.sha256(raw).hexdigest() != r["sha256"]:
            raise SystemExit(f"{path}: sha256 mismatch")
        seen_files.add(path.name)
        total += len(raw)

if seen_files != {p.name for p in out_dir.iterdir()}:
    raise SystemExit("sample directory contains files not in the index")
if total != stats["primary_bytes"] or len(index) != stats["frames"]:
    raise SystemExit("ingest stats disagree with re-derived output")
if total > 1_000_000_000:
    raise SystemExit("primary bytes exceed 1 GB cap")
if CHECK_MANIFEST:
    man = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    s = [x for x in man["series"] if x["id"] == L.SERIES_ID][0]
    if int(s["sample_count"]) != len(index) or int(s["total_size_bytes"]) != total:
        raise SystemExit(f"manifest scope {s['sample_count']}/{s['total_size_bytes']} != realized {len(index)}/{total}")
print(f"verified frames={len(index)} skipped={len(skipped)} primary_bytes={total} "
      f"sequences={len({r['sequence'] for r in index})}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
