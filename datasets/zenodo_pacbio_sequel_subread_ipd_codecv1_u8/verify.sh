#!/usr/bin/env bash
# Independently re-derive every subread 'ip' array from the downloaded prefix
# (separate gzip-member inflater and aux walker, not scripts/pacbio_bam.py)
# and check samples, index, manifest totals and degeneracy.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_pacbio_sequel_subread_ipd_codecv1_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

DATA_ROOT="$DATA_ROOT" MANIFEST="$RECIPE_DIR/manifest.toml" python3 -I -B - <<'PY'
import hashlib
import json
import os
import statistics
import struct
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "zenodo_pacbio_sequel_subread_ipd_codecv1_u8"
SERIES_ID = "subread_ipd_codecv1_u8"
PREFIX_BYTES = 268435456
# SHA-256 of the pinned 256 MiB prefix (first download, 2026-10-08).
PREFIX_SHA256 = "1f5b05dd9f69dcbcc3b6c595b3a0d328d7f238f2eba2f96106dabf5b0b782ecb"
MIN_SAMPLES = 5000

root = Path(os.environ["DATA_ROOT"])
download_dir = root / "downloads" / DATASET_ID
source = download_dir / f"veillonella.subreads.prefix_{PREFIX_BYTES}.bam"
inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
sample_dir = root / "samples" / DATASET_ID / SERIES_ID
index_path = root / "index" / DATASET_ID / "samples.jsonl"
manifest = tomllib.loads(Path(os.environ["MANIFEST"]).read_text(encoding="utf-8"))

data = source.read_bytes()
assert len(data) == PREFIX_BYTES, "prefix size mismatch"
digest = hashlib.sha256(data).hexdigest()
assert digest == inventory["prefix_sha256"], "prefix sha256 differs from inventory"
if PREFIX_SHA256:
    assert digest == PREFIX_SHA256, "prefix sha256 differs from pinned value"


def inflate_members(buf):
    """Inflate concatenated gzip members; drop an incomplete final member."""
    pos = 0
    n = len(buf)
    view = memoryview(buf)
    while pos < n:
        d = zlib.decompressobj(31)
        parts = []
        p = pos
        while not d.eof and p < n:
            chunk = view[p : p + 65536]
            parts.append(d.decompress(chunk))
            p += len(chunk)
        if not d.eof:
            return  # truncated final member of the byte-range prefix
        yield b"".join(parts)
        pos = p - len(d.unused_data)


# Re-derive (name, ip bytes) for every complete record.
stream = bytearray()
cursor = 0
members = inflate_members(data)
exhausted = False


def need(n):
    global cursor, stream, exhausted
    while len(stream) - cursor < n and not exhausted:
        try:
            chunk = next(members)
        except StopIteration:
            exhausted = True
            break
        if cursor > (1 << 22):
            del stream[:cursor]
            cursor = 0
        stream += chunk
    return len(stream) - cursor >= n


def take(n):
    global cursor
    assert need(n), "header truncated"
    out = bytes(stream[cursor : cursor + n])
    cursor += n
    return out


assert take(4) == b"BAM\x01"
(l_text,) = struct.unpack("<i", take(4))
header = take(l_text).decode("ascii", "replace")
(n_ref,) = struct.unpack("<i", take(4))
assert n_ref == 0, "unexpected references"
rg_lines = [line for line in header.splitlines() if line.startswith("@RG")]
assert len(rg_lines) == 1
rg = rg_lines[0]
for needle in ("DS:READTYPE=SUBREAD;", ";Ipd:CodecV1=ip;", ";FRAMERATEHZ=80.000000", "\tPM:SEQUEL", "\tPU:m54091_180306_141024"):
    assert needle in rg, f"@RG lacks {needle!r}"
assert "Ipd:Frames" not in rg

FIXED = {ord("A"): 1, ord("c"): 1, ord("C"): 1, ord("s"): 2, ord("S"): 2, ord("i"): 4, ord("I"): 4, ord("f"): 4}
derived = []  # (name, ip_bytes) in file order, after the drop policy
dropped_empty = dropped_constant = 0
while need(4):
    (bs,) = struct.unpack_from("<i", stream, cursor)
    assert 32 <= bs < (1 << 26), f"bad block size {bs}"
    if not need(4 + bs):
        break
    rec = bytes(stream[cursor + 4 : cursor + 4 + bs])
    cursor += 4 + bs
    l_name = rec[8]
    n_cig = struct.unpack_from("<H", rec, 12)[0]
    l_seq = struct.unpack_from("<i", rec, 16)[0]
    name = rec[32 : 32 + l_name - 1].decode("ascii")
    p = 32 + l_name + 4 * n_cig + (l_seq + 1) // 2 + l_seq
    ip = None
    while p < bs:
        tag, t = rec[p : p + 2], rec[p + 2]
        p += 3
        if t in FIXED:
            p += FIXED[t]
        elif t in (ord("Z"), ord("H")):
            p = rec.index(b"\x00", p) + 1
        elif t == ord("B"):
            sub = rec[p]
            (cnt,) = struct.unpack_from("<I", rec, p + 1)
            width = {ord("c"): 1, ord("C"): 1, ord("s"): 2, ord("S"): 2, ord("i"): 4, ord("I"): 4, ord("f"): 4}[sub]
            if tag == b"ip":
                assert sub == ord("C"), f"{name}: ip subtype {chr(sub)}"
                ip = rec[p + 5 : p + 5 + cnt]
            p += 5 + cnt * width
        else:
            raise AssertionError(f"{name}: unknown aux type {t}")
    assert p == bs, f"{name}: aux walk overran"
    assert ip is not None and len(ip) == l_seq, f"{name}: ip missing or wrong length"
    if not ip:
        dropped_empty += 1
        continue
    if ip.count(ip[0]) == len(ip):
        dropped_constant += 1
        continue
    derived.append((name, ip))

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
assert len(rows) == len(derived), f"index has {len(rows)} rows, re-derived {len(derived)}"
assert len(rows) >= MIN_SAMPLES, f"too few samples: {len(rows)}"
indexed_paths = set()
total_bytes = 0
lengths = []
global_counts = [0] * 256
for row, (name, ip) in zip(rows, derived):
    for key in ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness", "element_size_bytes", "sample_size_bytes", "value_count"):
        assert key in row, f"index row lacks {key}"
    assert row["dataset_id"] == DATASET_ID and row["series_id"] == SERIES_ID
    assert (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) == ("uint", 8, "little", 1)
    assert row["read_name"] == name, f"order mismatch at {name}"
    path = root / row["sample_path"]
    payload = path.read_bytes()
    assert payload == ip, f"sample bytes differ for {name}"
    assert row["value_count"] == row["sample_size_bytes"] == len(payload)
    assert row["code_min"] == min(ip) and row["code_max"] == max(ip) and row["code_distinct"] == len(set(ip))
    indexed_paths.add(path.name)
    total_bytes += len(payload)
    lengths.append(len(payload))
    if len(lengths) % 1000 == 1:
        for b in payload:
            global_counts[b] += 1
on_disk = {p.name for p in sample_dir.iterdir()}
assert on_disk == indexed_paths, f"stale or missing sample files: {len(on_disk ^ indexed_paths)}"
assert len({name for name, _ in derived}) == len(derived), "duplicate subread names"
assert statistics.median(lengths) >= 1000, "median below floor"
assert total_bytes <= 1_000_000_000
distinct_codes = sum(1 for c in global_counts if c)
assert distinct_codes >= 64, f"degenerate code alphabet in spot check: {distinct_codes}"

series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
assert series["sample_count"] == len(rows), f"manifest sample_count {series['sample_count']} != {len(rows)}"
assert series["total_size_bytes"] == total_bytes, f"manifest total_size_bytes {series['total_size_bytes']} != {total_bytes}"
print(
    f"verify ok samples={len(rows)} values={total_bytes} median={statistics.median(lengths)} "
    f"min_len={min(lengths)} max_len={max(lengths)} dropped_empty={dropped_empty} "
    f"dropped_constant={dropped_constant} spot_distinct_codes={distinct_codes} prefix_sha256={digest}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
