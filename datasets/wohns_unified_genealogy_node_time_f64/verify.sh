#!/usr/bin/env bash
# Independently re-derive every sample from the local ZIP ranges with a second
# parser/decoder (central-directory-driven member lookup, separate Blosc frame
# walker, zip-transposition unshuffle instead of strided slice assignment),
# byte-compare against the emitted samples, and re-check the missing-value
# policy, degeneracy bounds, index fields, and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="wohns_unified_genealogy_node_time_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

command -v "${ZSTD_BIN:-zstd}" >/dev/null || { echo "VERIFY FAIL: zstd CLI not found" >&2; exit 1; }
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
from __future__ import annotations

import array
import csv
import hashlib
import itertools
import json
import math
import os
import struct
import subprocess
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "tsdate_node_time_generations_f64"
EXPECTED_ARMS = 39
EXPECTED_SAMPLE_NODES = 7508
MAX_PLAUSIBLE_GENERATIONS = 1.0e6
MIN_DISTINCT = 10_000
ZSTD = os.environ.get("ZSTD_BIN", "zstd")

data_root = Path(os.environ["DATA_ROOT"])
recipe_dir = Path(os.environ["RECIPE_DIR"])
dl_dir = data_root / "downloads" / DATASET_ID
index_path = data_root / "index" / DATASET_ID / "samples.jsonl"

if sys.byteorder != "little":
    raise SystemExit("VERIFY FAIL: little-endian host assumed")


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def cd_members(cd: bytes, cd_offset: int) -> dict[str, tuple]:
    """Walk the CD from the EOCD; return name -> (method, crc, csize, usize, lho)."""
    eocd = cd.rfind(b"PK\x05\x06")
    if eocd != len(cd) - 22:
        fail("EOCD not at file end")
    count, size, offset = struct.unpack_from("<HII", cd, eocd + 10)
    if offset != cd_offset or size != eocd:
        fail("EOCD offsets inconsistent with fetched tail")
    out: dict[str, tuple] = {}
    pos = 0
    for _ in range(count):
        if cd[pos:pos + 4] != b"PK\x01\x02":
            fail("bad CD entry signature")
        method, = struct.unpack_from("<H", cd, pos + 10)
        crc, csize, usize = struct.unpack_from("<III", cd, pos + 16)
        nlen, elen, clen = struct.unpack_from("<HHH", cd, pos + 28)
        lho, = struct.unpack_from("<I", cd, pos + 42)
        name = cd[pos + 46:pos + 46 + nlen].decode()
        if name.startswith("nodes/time/") and name in out:
            fail(f"duplicate {name}")
        out[name] = (method, crc, csize, usize, lho)
        pos += 46 + nlen + elen + clen
    return out


def member(buf: bytes, base: int, entry: tuple, name: str) -> bytes:
    method, crc, csize, usize, lho = entry
    rel = lho - base
    if method != 0 or csize != usize or buf[rel:rel + 4] != b"PK\x03\x04":
        fail(f"{name}: not a stored member at its CD offset")
    nlen, elen = struct.unpack_from("<HH", buf, rel + 26)
    if buf[rel + 30:rel + 30 + nlen].decode() != name:
        fail(f"{name}: local name mismatch")
    data = buf[rel + 30 + nlen + elen: rel + 30 + nlen + elen + csize]
    if len(data) != csize or zlib.crc32(data) != crc:
        fail(f"{name}: CRC32/size mismatch")
    return data


def decode_blosc(frame: bytes) -> bytes:
    version, _vlz, flags, typesize = frame[0], frame[1], frame[2], frame[3]
    nbytes, blocksize, cbytes = struct.unpack_from("<iii", frame, 4)
    if version != 2 or cbytes != len(frame) or typesize != 8:
        fail("blosc header mismatch")
    if flags & 0x02:  # memcpyed: raw, unshuffled payload
        return frame[16:16 + nbytes]
    if (flags >> 5) != 4 or not flags & 0x10 or flags & 0x04:
        fail(f"unsupported blosc flags 0x{flags:02x}")
    nblocks = (nbytes + blocksize - 1) // blocksize
    starts = struct.unpack_from(f"<{nblocks}i", frame, 16)
    pieces = []
    covered = 0
    for b in range(nblocks):
        bsize = min(blocksize, nbytes - b * blocksize)
        csize, = struct.unpack_from("<i", frame, starts[b])
        covered += 4 + csize
        payload = frame[starts[b] + 4:starts[b] + 4 + csize]
        if csize == bsize:
            block = payload
        else:
            proc = subprocess.run([ZSTD, "--decompress", "--stdout", "--quiet"], input=payload,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            block = proc.stdout
            if proc.returncode != 0 or len(block) != bsize:
                fail(f"zstd block {b}: rc={proc.returncode} len={len(block)} want {bsize}")
        if flags & 0x01:
            m = bsize // typesize
            planes = [block[j * m:(j + 1) * m] for j in range(typesize)]
            block = bytes(itertools.chain.from_iterable(zip(*planes))) + bytes(block[m * typesize:])
        pieces.append(block)
    if 16 + 4 * nblocks + covered != len(frame):
        fail("blosc blocks do not cover the frame exactly")
    out = b"".join(pieces)
    if len(out) != nbytes:
        fail("blosc nbytes mismatch")
    return out


manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
if len(series) != 1 or series[0].get("role") != "primary":
    fail("manifest primary series missing")
series = series[0]
if (series["numeric_kind"], series["bit_width"], series["endianness"]) != ("float", 64, "little"):
    fail("manifest numeric type mismatch")
pins = list(csv.DictReader((recipe_dir / "resources.tsv").open(encoding="utf-8"), delimiter="\t"))
if len(pins) != EXPECTED_ARMS:
    fail(f"resources.tsv rows {len(pins)}")
if not index_path.is_file():
    fail("missing sample index")
rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
by_arm = {r.get("arm"): r for r in rows}
if len(rows) != EXPECTED_ARMS or sorted(by_arm) != sorted(p["arm"] for p in pins):
    fail("index rows do not cover exactly the pinned arms")

total_values = total_bytes = 0
digests = set()
for pin in pins:
    arm = pin["arm"]
    row = by_arm[arm]
    for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                      ("bit_width", 64), ("endianness", "little"), ("element_size_bytes", 8),
                      ("role", "primary"), ("source_field", "nodes/time")):
        if row.get(key) != want:
            fail(f"{arm}: index {key}={row.get(key)!r}")
    cd = (dl_dir / f"{arm}.cd.bin").read_bytes()
    buf = (dl_dir / f"{arm}.nodes_time.bin").read_bytes()
    members = cd_members(cd, int(pin["cd_offset"]))
    if sorted(k for k in members if k.startswith("nodes/time/")) != ["nodes/time/.zarray", "nodes/time/0"]:
        fail(f"{arm}: nodes/time is not single-chunk")
    base = int(pin["range_start"])
    zarray = json.loads(member(buf, base, members["nodes/time/.zarray"], "nodes/time/.zarray"))
    frame = member(buf, base, members["nodes/time/0"], "nodes/time/0")
    if f"{members['nodes/time/0'][1]:08x}" != pin["chunk_crc32"]:
        fail(f"{arm}: chunk CRC32 differs from pin")
    if (zarray.get("dtype"), zarray.get("shape"), zarray.get("compressor", {}).get("cname")) != \
            ("<f8", zarray.get("chunks"), "zstd"):
        fail(f"{arm}: zarray schema {zarray}")
    n = zarray["shape"][0]
    raw = decode_blosc(frame)
    if len(raw) != 8 * n:
        fail(f"{arm}: decoded bytes {len(raw)} != shape*8")
    sample = data_root / row["sample_path"]
    if not sample.is_file() or sample.read_bytes() != raw:
        fail(f"{arm}: sample bytes differ from independent re-derivation")
    if row["value_count"] != n or row["sample_size_bytes"] != 8 * n or sample.stat().st_size != 8 * n:
        fail(f"{arm}: index sizes")
    vals = struct.unpack(f"<{n}d", raw)
    if any(v != v or v in (math.inf, -math.inf) or v < 0 for v in vals):
        fail(f"{arm}: non-finite or negative node time")
    zeros = [i for i, v in enumerate(vals) if v == 0.0]
    if zeros != list(range(EXPECTED_SAMPLE_NODES)):
        fail(f"{arm}: zeros are not exactly the leading {EXPECTED_SAMPLE_NODES} sample nodes")
    vmax = max(vals)
    distinct = len(set(vals))
    if vmax > MAX_PLAUSIBLE_GENERATIONS or distinct < MIN_DISTINCT or vmax <= 0:
        fail(f"{arm}: degenerate/implausible max={vmax} distinct={distinct}")
    if row["max_value_stored"] != vmax or row["distinct_values"] != distinct \
            or row["sample_node_zero_count"] != len(zeros):
        fail(f"{arm}: index stats differ from recomputation")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != row["sha256"] or digest in digests:
        fail(f"{arm}: sha256 mismatch or duplicate")
    digests.add(digest)
    total_values += n
    total_bytes += 8 * n
    print(f"verified arm={arm} nodes={n} max={vmax:.6f} distinct={distinct}", flush=True)

if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
    fail(f"manifest totals {series.get('sample_count')}/{series.get('total_size_bytes')} != "
         f"{len(rows)}/{total_bytes}")
counts = sorted(r["value_count"] for r in rows)
if total_values < 10_000 or counts[len(counts) // 2] < 1_000 or total_bytes > 1_000_000_000:
    fail("acceptance floor/cap violated")
print(f"verify ok dataset={DATASET_ID} samples={len(rows)} values={total_values} bytes={total_bytes}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
