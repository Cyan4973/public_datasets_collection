#!/usr/bin/env python3
"""Plan, validate, build and verify the uq-hiddenstates Gemma-4-31B-it L45 MMLU-Pro recipe.

Pure standard library. Network I/O lives in download.sh (curl); this script only
parses what curl fetched.

Layout of the upstream shards: NPY v1/v2/v3 files, dtype '<f2', C order,
shape (rows, 5376). Traces are concatenated row blocks; the pinned index
(gemma_mmlupro_L45.idx.json) maps each item to (shard, off, n). One trace is
the contiguous raw-data byte range

    header_len + off * 10752 .. header_len + (off + n) * 10752 - 1

of its shard, where header_len is parsed from the downloaded NPY header.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import struct
import sys
import tomllib
from collections import Counter
from pathlib import Path

DATASET_ID = "hf_uq_gemma4_31b_mmlupro_residual_f16"
SERIES_ID = "gemma4_31b_it_resid_l45_mmlupro_f16"
HIDDEN = 5376
ROW_BYTES = HIDDEN * 2
STRIDE = 37
SHARDS = [
    {"name": "gemma_mmlupro_L45.part00.npy", "rows": 1995868, "size": 21459572864},
    {"name": "gemma_mmlupro_L45.part01.npy", "rows": 1371501, "size": 14746378880},
]
HEADER_PROBE_BYTES = 1024
RECIPE_DIR = Path(__file__).resolve().parent.parent
SELECTION_TSV = RECIPE_DIR / "scripts" / "selected_items.tsv"
MANIFEST = RECIPE_DIR / "manifest.toml"

# Degeneracy thresholds (per trace / per token row).
MIN_DISTINCT_CODES_PER_TRACE = 4096
MIN_DISTINCT_CODES_PER_ROW = 256
MAX_MODE_FRACTION = 0.05
MAX_ZERO_FRACTION = 0.05

# High byte of a little-endian float16 has exponent bits 0x7C; all ones means inf/NaN.
_NONFINITE_HI = bytes(b for b in range(256) if (b & 0x7C) == 0x7C)
_FINITE_HI = bytes(b for b in range(256) if (b & 0x7C) != 0x7C)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def require_little_endian_host() -> None:
    if sys.byteorder != "little":
        fail("memoryview casts assume a little-endian host")


# ----------------------------------------------------------------------------
# Index, selection and NPY header parsing
# ----------------------------------------------------------------------------

def load_index(path: Path) -> dict:
    idx = json.loads(path.read_text(encoding="utf-8"))
    expect = {"model": "gemma", "ds": "mmlupro", "li": 45, "L": 60, "hidden": HIDDEN, "format": "sharded-v1"}
    for key, value in expect.items():
        if idx.get(key) != value:
            fail(f"index field {key}={idx.get(key)!r}, expected {value!r}")
    shards = idx.get("shards")
    if [(s.get("name"), s.get("rows")) for s in shards] != [(s["name"], s["rows"]) for s in SHARDS]:
        fail(f"index shards changed: {shards}")
    items = idx["items"]
    if len(items) != 1000:
        fail(f"index has {len(items)} items, expected 1000")
    if sum(i["n"] for i in items) != idx["tot_tokens"]:
        fail("index tot_tokens does not equal the sum of item lengths")
    # Items must tile each shard contiguously in index order, with no trace spanning shards.
    pos = [0] * len(SHARDS)
    for item in items:
        s = item["shard"]
        if item["off"] != pos[s] or item["n"] <= 0 or not (0 < item["prompt_len"] < item["n"]):
            fail(f"index item {item['id']} breaks contiguity or has bad lengths")
        pos[s] += item["n"]
    for s, shard in enumerate(SHARDS):
        if pos[s] != shard["rows"]:
            fail(f"shard {s} items cover {pos[s]} rows, header says {shard['rows']}")
    return idx


def derive_selection(idx: dict) -> list[dict]:
    items = idx["items"]
    sel = []
    for p in range(0, len(items), STRIDE):
        it = items[p]
        sel.append({"item_pos": p, "item_id": str(it["id"]), "shard": it["shard"], "off": it["off"],
                    "n": it["n"], "prompt_len": it["prompt_len"], "y": it["y"]})
    return sel


def load_pinned_selection() -> list[dict]:
    lines = SELECTION_TSV.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        rec = dict(zip(head, line.split("\t")))
        rows.append({"item_pos": int(rec["item_pos"]), "item_id": rec["item_id"], "shard": int(rec["shard"]),
                     "off": int(rec["off"]), "n": int(rec["n"]), "prompt_len": int(rec["prompt_len"]),
                     "y": int(rec["y"])})
    return rows


def selection(idx: dict) -> list[dict]:
    sel = derive_selection(idx)
    if sel != load_pinned_selection():
        fail("selection derived from the index (every 37th item) differs from scripts/selected_items.tsv")
    if len({s["item_id"] for s in sel}) != len(sel):
        fail("duplicate item ids in selection")
    return sel


def parse_npy_header(raw: bytes, shard: dict) -> int:
    """Return the data offset (total header length) after validating dtype, order and shape."""
    if raw[:6] != b"\x93NUMPY":
        fail(f"{shard['name']}: not an NPY file")
    major = raw[6]
    if major == 1:
        hlen = struct.unpack("<H", raw[8:10])[0]
        start = 10
    elif major in (2, 3):
        hlen = struct.unpack("<I", raw[8:12])[0]
        start = 12
    else:
        fail(f"{shard['name']}: unsupported NPY version {major}")
    data_off = start + hlen
    if data_off > len(raw):
        fail(f"{shard['name']}: header longer than the probed {len(raw)} bytes")
    header = ast.literal_eval(raw[start:data_off].decode("latin1").strip())
    if header.get("descr") != "<f2":
        fail(f"{shard['name']}: descr {header.get('descr')!r}, expected '<f2'")
    if header.get("fortran_order") is not False:
        fail(f"{shard['name']}: not C order")
    if tuple(header.get("shape", ())) != (shard["rows"], HIDDEN):
        fail(f"{shard['name']}: shape {header.get('shape')} != ({shard['rows']}, {HIDDEN})")
    if data_off % 16 or data_off + shard["rows"] * ROW_BYTES != shard["size"]:
        fail(f"{shard['name']}: header length {data_off} inconsistent with pinned file size {shard['size']}")
    return data_off


def header_offsets(download_dir: Path) -> list[int]:
    offs = []
    for s, shard in enumerate(SHARDS):
        raw = (download_dir / f"header_part{s:02d}.bin").read_bytes()
        if len(raw) != HEADER_PROBE_BYTES:
            fail(f"header_part{s:02d}.bin has {len(raw)} bytes, expected {HEADER_PROBE_BYTES}")
        offs.append(parse_npy_header(raw, shard))
    return offs


def trace_path(download_dir: Path, item: dict) -> Path:
    return download_dir / "traces" / f"item_{item['item_id']}.f16"


def sample_rel(item: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/mmlupro_item_{item['item_id']}.bin"


# ----------------------------------------------------------------------------
# Content checks
# ----------------------------------------------------------------------------

def nonfinite_count(raw: bytes) -> int:
    return len(raw[1::2].translate(None, _FINITE_HI))


def code_stats(raw: bytes) -> dict:
    """Histogram-based statistics over float16 bit patterns (build path)."""
    codes = memoryview(raw).cast("H")
    hist = Counter(codes)
    total = len(codes)
    pos = [c for c in hist if c < 0x8000]
    neg = [c for c in hist if c >= 0x8000]
    def f16(code: int) -> float:
        return struct.unpack("<e", struct.pack("<H", code))[0]
    maximum = f16(max(pos)) if pos else -f16(min(neg) & 0x7FFF)
    minimum = -f16(max(neg) & 0x7FFF) if neg else f16(min(pos))
    zeros = hist.get(0, 0) + hist.get(0x8000, 0)
    mode_code, mode_count = hist.most_common(1)[0]
    entropy = -sum(c / total * math.log2(c / total) for c in hist.values())
    low3 = sum(c for code, c in hist.items() if code & 7)
    return {"distinct_codes": len(hist), "min": minimum, "max": maximum, "zero_fraction": zeros / total,
            "mode_fraction": mode_count / total, "order0_entropy_bits": round(entropy, 4),
            "low3_mantissa_nonzero_fraction": low3 / total}


def row_checks(raw: bytes, n: int) -> int:
    """Return the minimum distinct-code count over token rows; fail on duplicated adjacent rows."""
    mv = memoryview(raw)
    min_distinct = HIDDEN
    prev = None
    for r in range(n):
        row = bytes(mv[r * ROW_BYTES:(r + 1) * ROW_BYTES])
        if row == prev:
            fail(f"row {r} duplicates the previous row")
        prev = row
        d = len(set(memoryview(row).cast("H")))
        min_distinct = min(min_distinct, d)
    return min_distinct


def check_trace(raw: bytes, item: dict, label: str) -> None:
    if len(raw) != item["n"] * ROW_BYTES:
        fail(f"{label}: {len(raw)} bytes, expected {item['n'] * ROW_BYTES}")
    bad = nonfinite_count(raw)
    if bad:
        fail(f"{label}: {bad} non-finite float16 values")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------------------
# Subcommands
# ----------------------------------------------------------------------------

def cmd_check_headers(args: argparse.Namespace) -> None:
    offs = header_offsets(Path(args.download_dir))
    print("header data offsets:", offs)


def cmd_plan(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    idx = load_index(download_dir / "gemma_mmlupro_L45.idx.json")
    offs = header_offsets(download_dir)
    for item in selection(idx):
        start = offs[item["shard"]] + item["off"] * ROW_BYTES
        end = start + item["n"] * ROW_BYTES - 1
        print(SHARDS[item["shard"]]["name"], item["item_id"], start, end, item["n"] * ROW_BYTES)


def cmd_validate(args: argparse.Namespace) -> None:
    require_little_endian_host()
    download_dir = Path(args.download_dir)
    idx = load_index(download_dir / "gemma_mmlupro_L45.idx.json")
    header_offsets(download_dir)
    lines = ["item_id\tbytes\tsha256"]
    total = 0
    for item in selection(idx):
        path = trace_path(download_dir, item)
        if not path.is_file():
            fail(f"missing {path}")
        raw = path.read_bytes()
        check_trace(raw, item, path.name)
        lines.append(f"{item['item_id']}\t{len(raw)}\t{sha256_bytes(raw)}")
        total += len(raw)
    (download_dir / "trace_sha256.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"validated {len(lines) - 1} traces, {total} bytes, all finite")


def cmd_build(args: argparse.Namespace) -> None:
    require_little_endian_host()
    download_dir = Path(args.download_dir)
    samples_dir = Path(args.samples_dir) / SERIES_ID
    data_dir = Path(args.data_dir)
    idx = load_index(download_dir / "gemma_mmlupro_L45.idx.json")
    header_offsets(download_dir)
    pinned_sha = {}
    for line in (download_dir / "trace_sha256.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        iid, nbytes, sha = line.split("\t")
        pinned_sha[iid] = (int(nbytes), sha)
    samples_dir.mkdir(parents=True, exist_ok=True)
    sel = selection(idx)
    expected_names = {Path(sample_rel(i)).name for i in sel}
    for stale in samples_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()
    rows = []
    agg = {"samples": 0, "values": 0, "bytes": 0, "min": math.inf, "max": -math.inf}
    for item in sel:
        raw = trace_path(download_dir, item).read_bytes()
        check_trace(raw, item, f"item {item['item_id']}")
        sha = sha256_bytes(raw)
        if pinned_sha.get(item["item_id"]) != (len(raw), sha):
            fail(f"item {item['item_id']}: download changed since validation")
        st = code_stats(raw)
        if st["distinct_codes"] < MIN_DISTINCT_CODES_PER_TRACE:
            fail(f"item {item['item_id']}: only {st['distinct_codes']} distinct codes")
        if st["mode_fraction"] > MAX_MODE_FRACTION or st["zero_fraction"] > MAX_ZERO_FRACTION:
            fail(f"item {item['item_id']}: degenerate distribution {st}")
        min_row = row_checks(raw, item["n"])
        if min_row < MIN_DISTINCT_CODES_PER_ROW:
            fail(f"item {item['item_id']}: a token row has only {min_row} distinct codes")
        rel = sample_rel(item)
        out = data_dir / rel
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, out)
        row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "float", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": len(raw), "value_count": len(raw) // 2,
            "shape": [item["n"], HIDDEN], "axes": ["token_position", "hidden_dim"],
            "item_id": item["item_id"], "index_position": item["item_pos"],
            "source_shard": SHARDS[item["shard"]]["name"], "row_offset": item["off"],
            "token_count": item["n"], "prompt_len": item["prompt_len"], "y_incorrect": item["y"],
            "min": st["min"], "max": st["max"], "distinct_codes": st["distinct_codes"],
            "min_row_distinct_codes": min_row, "zero_fraction": st["zero_fraction"],
            "order0_entropy_bits": st["order0_entropy_bits"],
            "low3_mantissa_nonzero_fraction": st["low3_mantissa_nonzero_fraction"], "sha256": sha,
        }
        rows.append(row)
        agg["samples"] += 1
        agg["values"] += len(raw) // 2
        agg["bytes"] += len(raw)
        agg["min"] = min(agg["min"], st["min"])
        agg["max"] = max(agg["max"], st["max"])
        print(f"item {item['item_id']}: n={item['n']} distinct={st['distinct_codes']} "
              f"range=[{st['min']}, {st['max']}] H0={st['order0_entropy_bits']} min_row_distinct={min_row}")
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    stats = Path(args.stats)
    stats.parent.mkdir(parents=True, exist_ok=True)
    stats.write_text(json.dumps(agg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built {agg['samples']} samples, {agg['values']} values, {agg['bytes']} bytes")


def cmd_verify(args: argparse.Namespace) -> None:
    """Independent re-derivation: re-plan from index + headers, re-read sources, recompute stats differently."""
    require_little_endian_host()
    download_dir = Path(args.download_dir)
    data_dir = Path(args.data_dir)
    idx = load_index(download_dir / "gemma_mmlupro_L45.idx.json")
    header_offsets(download_dir)
    sel = derive_selection(idx)
    if sel != load_pinned_selection():
        fail("selection mismatch")
    index_rows = [json.loads(l) for l in Path(args.index).read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(index_rows) != len(sel):
        fail(f"index has {len(index_rows)} rows, expected {len(sel)}")
    sample_dir = data_dir / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(Path(sample_rel(i)).name for i in sel):
        fail(f"unexpected files in {sample_dir}")
    seen = set()
    total_bytes = 0
    for item, row in zip(sel, index_rows):
        rel = sample_rel(item)
        if row["sample_path"] != rel or row["item_id"] != item["item_id"]:
            fail(f"index row order/path mismatch for item {item['item_id']}")
        for key, value in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                           ("bit_width", 16), ("endianness", "little"), ("element_size_bytes", 2),
                           ("token_count", item["n"]), ("shape", [item["n"], HIDDEN]), ("y_incorrect", item["y"])):
            if row.get(key) != value:
                fail(f"item {item['item_id']}: index {key}={row.get(key)!r}, expected {value!r}")
        sample = (data_dir / rel).read_bytes()
        source = trace_path(download_dir, item).read_bytes()
        if sample != source:
            fail(f"item {item['item_id']}: sample bytes differ from the downloaded NPY row range")
        if len(sample) != item["n"] * ROW_BYTES or row["sample_size_bytes"] != len(sample) \
                or row["value_count"] * 2 != len(sample):
            fail(f"item {item['item_id']}: size mismatch")
        sha = hashlib.sha256(sample).hexdigest()
        if sha != row["sha256"] or sha in seen:
            fail(f"item {item['item_id']}: sha mismatch or duplicate sample")
        seen.add(sha)
        vals = memoryview(sample).cast("e")
        # Independent finiteness check on decoded floats (build used the exponent byte mask).
        lo = min(vals)
        hi = max(vals)
        if not (math.isfinite(lo) and math.isfinite(hi)) or any(v != v for v in (lo, hi)):
            fail(f"item {item['item_id']}: non-finite values")
        if nonfinite_count(sample):
            fail(f"item {item['item_id']}: non-finite values")
        if lo != row["min"] or hi != row["max"] or not lo < hi:
            fail(f"item {item['item_id']}: min/max {lo},{hi} != index {row['min']},{row['max']}")
        distinct = len(set(memoryview(sample).cast("H")))
        if distinct != row["distinct_codes"] or distinct < MIN_DISTINCT_CODES_PER_TRACE:
            fail(f"item {item['item_id']}: distinct codes {distinct} (index {row['distinct_codes']})")
        # Per-hidden-channel non-constancy (column view of the [n, 5376] matrix).
        codes = memoryview(sample).cast("H")
        constant_cols = sum(1 for c in range(HIDDEN) if len(set(codes[c::HIDDEN])) == 1)
        if constant_cols:
            fail(f"item {item['item_id']}: {constant_cols} constant hidden channels")
        total_bytes += len(sample)
        print(f"verified item {item['item_id']}: n={item['n']} range=[{lo}, {hi}] distinct={distinct}")
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
    if series["sample_count"] != len(sel) or series["total_size_bytes"] != total_bytes:
        fail(f"manifest totals {series['sample_count']}/{series['total_size_bytes']} != realized {len(sel)}/{total_bytes}")
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if stats["samples"] != len(sel) or stats["bytes"] != total_bytes:
        fail("ingest_stats.json disagrees with realized output")
    print(f"verify ok: {len(sel)} samples, {total_bytes} bytes")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check-headers", "plan", "validate", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", required=True)
        if name in ("build", "verify"):
            p.add_argument("--data-dir", required=True)
            p.add_argument("--samples-dir", required=name == "build")
            p.add_argument("--index", required=True)
            p.add_argument("--stats", required=True)
    args = ap.parse_args()
    {"check-headers": cmd_check_headers, "plan": cmd_plan, "validate": cmd_validate,
     "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
