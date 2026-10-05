#!/usr/bin/env bash
# Independently re-derive every sample from its source COG (separate decoder
# from scripts/goes_cog.py), byte-compare, and re-check codes, fill policy,
# degeneracy bounds, index fields and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mpc_goes18_abi_cmi_c13_fulldisk_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export DATA_ROOT RECIPE_DIR DATASET_ID
python3 - <<'PY'
from __future__ import annotations

import array
import hashlib
import json
import os
import statistics
import struct
import sys
import tomllib
import zlib
from collections import Counter
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "goes18_abi_cmi_c13_fulldisk_bt_code_u16"
N = 5424
VALUES = N * N
SAMPLE_BYTES = VALUES * 2
TILE = 512
TILES_PER_SIDE = 11  # 10 full tiles + one 304-pixel edge tile
EXPECTED_SAMPLES = 12
EXPECTED_MONTHS = [f"2025-{m:02d}" for m in (10, 11, 12)] + [f"2026-{m:02d}" for m in range(1, 10)]
FILL = 65535
MAX_CODE = 4095
SCALE = 0.06145332
OFFSET = 89.620003
FILL_FRACTION_RANGE = (0.15, 0.35)
MIN_DISTINCT_CODES = 1000
MEDIAN_BT_RANGE_K = (200.0, 305.0)

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def rederive(path: Path) -> bytes:
    """Independent primary-IFD decode: seek-based tag reads, tile-row assembly."""
    with path.open("rb") as fh:
        head = fh.read(8)
        if head[:4] != b"II*\x00":
            fail(f"{path.name}: not little-endian classic TIFF")
        ifd = struct.unpack("<I", head[4:])[0]
        fh.seek(ifd)
        (count,) = struct.unpack("<H", fh.read(2))
        entries = {}
        for _ in range(count):
            tag, typ, n, raw = struct.unpack("<HHI4s", fh.read(12))
            entries[tag] = (typ, n, raw)

        def ints(tag: int) -> list[int]:
            typ, n, raw = entries[tag]
            fmt = {3: "H", 4: "I"}[typ]
            size = struct.calcsize(fmt) * n
            if size <= 4:
                return list(struct.unpack("<" + fmt * n, raw[:size]))
            fh.seek(struct.unpack("<I", raw)[0])
            return list(struct.unpack("<" + fmt * n, fh.read(size)))

        def text(tag: int) -> str:
            typ, n, raw = entries[tag]
            if n <= 4:
                return raw[:n].rstrip(b"\x00").decode()
            fh.seek(struct.unpack("<I", raw)[0])
            return fh.read(n).rstrip(b"\x00").decode()

        want = {256: N, 257: N, 258: 16, 259: 8, 277: 1, 284: 1, 317: 1, 322: TILE, 323: TILE, 339: 1}
        for tag, value in want.items():
            if ints(tag) != [value]:
                fail(f"{path.name}: TIFF tag {tag}={ints(tag)} expected {value}")
        if text(42113).strip() != "65535":
            fail(f"{path.name}: GDAL nodata {text(42113)!r}")
        meta = text(42112)
        for needle in ('name="NETCDF_VARNAME" sample="0">CMI_C13<', 'name="CMI_C13#scale_factor">0.06145332<',
                       'name="CMI_C13#add_offset">89.620003<', 'name="NC_GLOBAL#platform_ID">G18<',
                       'name="NC_GLOBAL#scene_id">Full Disk<'):
            if needle not in meta:
                fail(f"{path.name}: GDAL metadata lacks {needle}")
        offsets, counts = ints(324), ints(325)
        if len(offsets) != TILES_PER_SIDE ** 2 or len(counts) != TILES_PER_SIDE ** 2:
            fail(f"{path.name}: tile table length {len(offsets)}")
        out = bytearray()
        for ty in range(TILES_PER_SIDE):
            row_tiles = []
            for tx in range(TILES_PER_SIDE):
                k = ty * TILES_PER_SIDE + tx
                fh.seek(offsets[k])
                blob = zlib.decompressobj().decompress(fh.read(counts[k]))
                if len(blob) != TILE * TILE * 2:
                    fail(f"{path.name}: tile {k} inflated to {len(blob)} bytes")
                row_tiles.append(blob)
            rows_here = min(TILE, N - ty * TILE)
            last_w = (N - (TILES_PER_SIDE - 1) * TILE) * 2
            for r in range(rows_here):
                base = r * TILE * 2
                for tx, blob in enumerate(row_tiles):
                    width = TILE * 2 if tx < TILES_PER_SIDE - 1 else last_w
                    out += blob[base:base + width]
        if len(out) != SAMPLE_BYTES:
            fail(f"{path.name}: re-derived {len(out)} bytes")
        return bytes(out)


manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
if len(series) != 1 or series[0].get("role") != "primary":
    fail("manifest primary series missing")
series = series[0]

if not index_path.is_file():
    fail(f"missing index {index_path}")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != EXPECTED_SAMPLES:
    fail(f"index rows={len(rows)} expected={EXPECTED_SAMPLES}")

months = []
digests = set()
fill_fracs = []
for row in rows:
    for key, value in {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary", "numeric_kind": "uint",
        "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
        "sample_size_bytes": SAMPLE_BYTES, "value_count": VALUES, "sample_shape": [N, N],
        "natural_record_kind": series["natural_record_kind"], "source_format": series["source_format"],
        "source_field": series["source_field"], "fill_value": FILL,
    }.items():
        if row.get(key) != value:
            fail(f"index {row.get('month')}: {key}={row.get(key)!r} expected {value!r}")
    if not row["scan_start_utc"].startswith(row["month"] + "-15T20:00:"):
        fail(f"scan {row['scan_start_utc']} is not the 20:00 UTC slot on the 15th of {row['month']}")
    if row["stac_item_id"][-14:] != row["source_netcdf"].split("_s", 1)[1][:14]:
        fail(f"item/netcdf mismatch {row['stac_item_id']} {row['source_netcdf']}")
    months.append(row["month"])

    sample = data_root / row["sample_path"]
    if not sample.is_file() or sample.stat().st_size != SAMPLE_BYTES:
        fail(f"missing or wrong-size sample {sample}")
    payload = sample.read_bytes()
    source = data_root / row["source_file"]
    if not source.is_file():
        fail(f"missing source COG {source}")
    if rederive(source) != payload:
        fail(f"{sample.name}: bytes differ from independent re-derivation of {source.name}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != row["sha256"] or digest in digests:
        fail(f"{sample.name}: sha256 mismatch or duplicate")
    digests.add(digest)

    values = array.array("H")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    hist = Counter(values)
    bad = [v for v in hist if v > MAX_CODE and v != FILL]
    if bad:
        fail(f"{sample.name}: codes outside 0..4095 and != 65535: {sorted(bad)[:10]}")
    fill = hist.get(FILL, 0)
    valid = VALUES - fill
    codes = sorted(v for v in hist if v != FILL)
    frac = fill / VALUES
    if not FILL_FRACTION_RANGE[0] <= frac <= FILL_FRACTION_RANGE[1]:
        fail(f"{sample.name}: fill fraction {frac:.4f}")
    if len(codes) < MIN_DISTINCT_CODES:
        fail(f"{sample.name}: only {len(codes)} distinct valid codes (degenerate)")
    corners = (values[0], values[N - 1], values[VALUES - N], values[VALUES - 1])
    if corners != (FILL,) * 4 or values[(N // 2) * N + N // 2] == FILL:
        fail(f"{sample.name}: disk geometry wrong (corners {corners})")
    running, median_code = 0, codes[-1]
    for code in codes:
        running += hist[code]
        if running >= (valid + 1) // 2:
            median_code = code
            break
    median_bt = OFFSET + SCALE * median_code
    if not MEDIAN_BT_RANGE_K[0] <= median_bt <= MEDIAN_BT_RANGE_K[1]:
        fail(f"{sample.name}: median BT {median_bt:.2f} K")
    expected_index = {
        "fill_count": fill, "valid_count": valid, "valid_code_min": codes[0], "valid_code_max": codes[-1],
        "valid_code_median": median_code, "distinct_valid_codes": len(codes),
        "min_value_stored": codes[0], "max_value_stored": FILL if fill else codes[-1],
    }
    for key, value in expected_index.items():
        if row.get(key) != value:
            fail(f"{sample.name}: index {key}={row.get(key)} recomputed {value}")
    fill_fracs.append(frac)
    print(f"verified {row['month']} {sample.name} fill={frac:.4f} codes={codes[0]}..{codes[-1]} "
          f"distinct={len(codes)} median_bt={median_bt:.2f}K re-derived=identical")

if sorted(months) != EXPECTED_MONTHS:
    fail(f"months {sorted(months)} != {EXPECTED_MONTHS}")
total = sum(int(r["sample_size_bytes"]) for r in rows)
if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
    fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != {len(rows)}/{total}")
if total > 1_000_000_000:
    fail(f"primary bytes {total} exceed 1e9")
if statistics.median(int(r["value_count"]) for r in rows) < 1000:
    fail("median sample below floor")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats["samples"] != len(rows) or stats["primary_sample_bytes"] != total:
    fail("ingest_stats totals mismatch")
print(f"verified dataset={DATASET_ID} samples={len(rows)} values={total // 2} bytes={total} "
      f"fill_fraction_range={min(fill_fracs):.4f}..{max(fill_fracs):.4f}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
