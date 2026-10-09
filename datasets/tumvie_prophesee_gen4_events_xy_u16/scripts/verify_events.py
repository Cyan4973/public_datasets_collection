#!/usr/bin/env python3
"""Independent verification of the TUM-VIE event-window samples.

* index: exactly 42 rows (21 sequences x {x, y}) with the required fields,
  correct sizes, and paths that exist;
* re-derivation: for every sequence the window is re-resolved from the cached
  HDF5 metadata, checked against sequences.tsv, re-decoded from the cached
  chunk spans, and compared byte-for-byte with the emitted sample;
* content: every x <= 1279 and y <= 719 (recomputed from the sample file, not
  copied from the index), min/max/distinct/sha256 equal to the index, no
  constant or near-constant series, no duplicate samples, x and y windows of
  a sequence cover the same event indices;
* manifest: per-series sample_count / total_size_bytes equal realized output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tumvie_events as E  # noqa: E402
import tumvie_h5 as T  # noqa: E402

REQUIRED = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
            "element_size_bytes", "sample_size_bytes", "value_count"]
SAMPLE_VALUES = T.WINDOW_CHUNKS * T.CHUNK_ELEMS
SAMPLE_BYTES = SAMPLE_VALUES * 2


def fail(msg: str) -> None:
    print(f"VERIFY FAILED: {msg}", file=sys.stderr)
    raise SystemExit(1)


def stats(raw: bytes) -> tuple[int, int, int, float]:
    counts = Counter(memoryview(raw).cast("H"))
    return min(counts), max(counts), len(counts), max(counts.values()) / (len(raw) // 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()
    recipe_dir, data_root = Path(args.recipe_dir), Path(args.data_root)

    index_path = data_root / "index" / E.DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seqs = [r["sequence"] for r in E.load_sequences(recipe_dir)]
    if len(rows) != 2 * len(seqs):
        fail(f"index has {len(rows)} rows, expected {2 * len(seqs)}")
    by_key = {}
    for r in rows:
        for k in REQUIRED:
            if k not in r:
                fail(f"index row lacks {k}: {r.get('sample_path')}")
        if r["dataset_id"] != E.DATASET_ID or r["numeric_kind"] != "uint" or r["bit_width"] != 16 \
                or r["endianness"] != "little" or r["element_size_bytes"] != 2:
            fail(f"bad type fields in {r['sample_path']}")
        if r["sample_size_bytes"] != SAMPLE_BYTES or r["value_count"] != SAMPLE_VALUES:
            fail(f"bad size fields in {r['sample_path']}")
        axis = {v: k for k, v in E.SERIES.items()}.get(r["series_id"])
        if axis is None:
            fail(f"unknown series {r['series_id']}")
        key = (r["sequence"], axis)
        if key in by_key:
            fail(f"duplicate index row {key}")
        by_key[key] = r
        expect_path = f"samples/{E.DATASET_ID}/{r['series_id']}/{r['sequence']}.u16"
        if r["sample_path"] != expect_path:
            fail(f"sample_path {r['sample_path']} != {expect_path}")

    shas = set()
    for seq in seqs:
        plan = E.check_plan(recipe_dir, data_root, seq)
        decoded = E.decode_window(data_root, seq, plan)
        rx, ry = by_key.get((seq, "x")), by_key.get((seq, "y"))
        if rx is None or ry is None:
            fail(f"{seq}: missing x or y sample")
        for field in ("event_index_start", "event_index_end", "window_start_chunk", "stream_event_count"):
            if rx[field] != ry[field]:
                fail(f"{seq}: x/y {field} differ ({rx[field]} vs {ry[field]})")
        if rx["event_index_start"] != plan["event_index_start"] or rx["event_index_end"] != plan["event_index_end"]:
            fail(f"{seq}: index event range differs from re-derived plan")
        if rx["event_index_end"] - rx["event_index_start"] != SAMPLE_VALUES:
            fail(f"{seq}: window length mismatch")
        for axis, r in (("x", rx), ("y", ry)):
            path = data_root / r["sample_path"]
            raw = path.read_bytes()
            if len(raw) != SAMPLE_BYTES:
                fail(f"{path} has {len(raw)} bytes")
            if raw != decoded[axis]:
                fail(f"{path} differs from the re-decoded events/{axis} window")
            sha = hashlib.sha256(raw).hexdigest()
            if sha != r["sha256"]:
                fail(f"{path} sha256 differs from index")
            if sha in shas:
                fail(f"{path} duplicates another sample")
            shas.add(sha)
            lo, hi, distinct, top = stats(raw)
            if hi > E.LIMITS[axis]:
                fail(f"{path}: max {hi} > {E.LIMITS[axis]}")
            if (lo, hi, distinct) != (r["min"], r["max"], r["distinct_values"]):
                fail(f"{path}: min/max/distinct {(lo, hi, distinct)} != index")
            if lo == hi or distinct < (256 if axis == "x" else 128) or top > 0.25:
                fail(f"{path}: degenerate (distinct={distinct}, top fraction={top:.3f})")
        if decoded["x"] == decoded["y"]:
            fail(f"{seq}: x and y identical")
        print(f"verified {seq} x[{by_key[(seq, 'x')]['min']},{by_key[(seq, 'x')]['max']}] "
              f"y[{by_key[(seq, 'y')]['min']},{by_key[(seq, 'y')]['max']}]", flush=True)

    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    for s in manifest["series"]:
        mine = [r for r in rows if r["series_id"] == s["id"]]
        if s["sample_count"] != len(mine) or s["total_size_bytes"] != sum(r["sample_size_bytes"] for r in mine):
            fail(f"manifest series {s['id']}: sample_count/total_size_bytes {s['sample_count']}/"
                 f"{s['total_size_bytes']} != realized {len(mine)}/{sum(r['sample_size_bytes'] for r in mine)}")
    total = sum(r["sample_size_bytes"] for r in rows)
    print(f"verify_ok samples={len(rows)} bytes={total} values={total // 2}")


if __name__ == "__main__":
    main()
