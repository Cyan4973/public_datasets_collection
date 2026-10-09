#!/usr/bin/env python3
"""Independent verification for srsp_scotland_phase1_lidar_scan_angle_i8.

usage: verify_samples.py RECIPE_DIR DATA_ROOT REPO_ROOT [WORKERS]

  * index rows: required keys, int8 little-endian, one row per pinned tile,
    no extra files in the series directory, sizes match value counts;
  * manifest sample_count / total_size_bytes equal the realized output;
  * every sample is re-derived from its local LAZ tile (fresh decode, scan
    angle read through a signed memoryview at record offset 16) and must be
    byte-identical to the stored .bin; the decoded count must equal the LAS
    header count;
  * the same degeneracy policy as the build is recomputed from the stored
    bytes: >= 5 distinct values, no value above half the points, max-min
    span >= 10 degrees, all values within -90..+90;
  * repository floors and the 1 GB cap; reports the realized range.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import statistics
import sys
import tomllib
from multiprocessing import Pool
from pathlib import Path

DATASET_ID = "srsp_scotland_phase1_lidar_scan_angle_i8"
SERIES_ID = "srsp_phase1_scan_angle_rank_i8"
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]
CTX: dict = {}


def init(repo_root: str, data_root: str) -> None:
    sys.path.insert(0, str(Path(repo_root) / "tools" / "laz"))
    import laszip  # noqa: E402
    CTX["laszip"] = laszip
    CTX["data_root"] = Path(data_root)


def check(job: tuple) -> dict:
    key, sample_rel = job
    laszip = CTX["laszip"]
    root = CTX["data_root"]
    src = root / "downloads" / DATASET_ID / "laz" / Path(key).name
    stored = (root / sample_rel).read_bytes()
    hdr = laszip.read_header(str(src))
    if hdr["point_record_length"] != 28 or hdr["point_format"] != 1:
        raise RuntimeError(f"{src.name}: unexpected point layout")
    pos = 0
    for _, count, records in laszip.iter_chunks(str(src), header=hdr):
        view = memoryview(records).cast("b")
        derived = view[16::28].tobytes()
        if len(derived) != count or stored[pos:pos + count] != derived:
            raise RuntimeError(f"{src.name}: stored sample differs from re-derived scan angles near point {pos}")
        pos += count
    if pos != len(stored) or pos != hdr["point_count"]:
        raise RuntimeError(f"{src.name}: re-derived {pos} values, stored {len(stored)}, header {hdr['point_count']}")
    hist = collections.Counter(memoryview(stored).cast("b"))
    n = len(stored)
    lo, hi = min(hist), max(hist)
    mode_value, mode_count = hist.most_common(1)[0]
    problems = []
    if len(hist) < 5:
        problems.append(f"{len(hist)} distinct values")
    if mode_count > n / 2:
        problems.append(f"value {mode_value} holds {mode_count / n:.3f}")
    if hi - lo < 10:
        problems.append(f"span {lo}..{hi}")
    if lo < -90 or hi > 90:
        problems.append(f"outside -90..90 ({lo}..{hi})")
    if problems:
        raise RuntimeError(f"{src.name}: degenerate or invalid scan angles: {'; '.join(problems)}")
    return {"name": src.name, "n": n, "min": lo, "max": hi, "distinct": len(hist),
            "zero": hist.get(0, 0), "mode": mode_value, "mode_share": mode_count / n,
            "sha256": hashlib.sha256(stored).hexdigest(), "hist": dict(hist)}


def main() -> None:
    recipe, root, repo = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    manifest = tomllib.loads((recipe / "manifest.toml").read_text())
    series = [s for s in manifest["series"] if s.get("role") == "primary"]
    if [s["id"] for s in series] != [SERIES_ID]:
        raise SystemExit(f"expected exactly one primary series {SERIES_ID}")
    tiles = list(csv.DictReader((recipe / "scripts" / "tiles.tsv").open(newline=""), delimiter="\t"))
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if len(rows) != len(tiles):
        raise SystemExit(f"index rows {len(rows)} != pinned tiles {len(tiles)}")
    by_key = {}
    for r in rows:
        missing = [k for k in INDEX_KEYS if k not in r]
        if missing:
            raise SystemExit(f"index row missing {missing}: {r.get('sample_path')}")
        if (r["dataset_id"], r["series_id"], r["numeric_kind"], int(r["bit_width"]), r["endianness"],
                int(r["element_size_bytes"])) != (DATASET_ID, SERIES_ID, "int", 8, "little", 1):
            raise SystemExit(f"unexpected index typing: {r['sample_path']}")
        p = root / r["sample_path"]
        if not p.is_file() or p.stat().st_size != int(r["sample_size_bytes"]) or int(r["value_count"]) != p.stat().st_size:
            raise SystemExit(f"size mismatch or missing: {r['sample_path']}")
        if r["source_key"] in by_key:
            raise SystemExit(f"duplicate tile in index: {r['source_key']}")
        by_key[r["source_key"]] = r
    if set(by_key) != {t["key"] for t in tiles}:
        raise SystemExit("index tiles differ from the pinned tile list")
    on_disk = sorted(p.name for p in (root / "samples" / DATASET_ID / SERIES_ID).iterdir())
    if on_disk != sorted(Path(r["sample_path"]).name for r in rows):
        raise SystemExit("series directory holds files not in the index (or misses some)")

    jobs = [(t["key"], by_key[t["key"]]["sample_path"]) for t in tiles]
    results = []
    with Pool(workers, initializer=init, initargs=(str(repo), str(root))) as pool:
        for res in pool.imap(check, jobs):
            results.append(res)
    for t, res in zip(tiles, results):
        r = by_key[t["key"]]
        if r.get("sample_sha256") and r["sample_sha256"] != res["sha256"]:
            raise SystemExit(f"{res['name']}: index sample_sha256 mismatch")
        if (r.get("min"), r.get("max")) != (res["min"], res["max"]):
            raise SystemExit(f"{res['name']}: index min/max disagree with stored bytes")
    shas = [res["sha256"] for res in results]
    if len(set(shas)) != len(shas):
        raise SystemExit("duplicate sample contents")

    counts = [res["n"] for res in results]
    total = sum(counts)
    median = statistics.median(counts)
    if total < 10_000 and total < 102_400:
        raise SystemExit("below aggregate floor")
    if median < 1_000:
        raise SystemExit(f"median sample values {median} below 1,000")
    if total > 1_000_000_000:
        raise SystemExit(f"primary bytes {total} exceed 1 GB cap")
    s = series[0]
    if int(s["sample_count"]) != len(results) or int(s["total_size_bytes"]) != total:
        raise SystemExit(f"manifest sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} "
                         f"!= realized {len(results)}/{total}")
    overall = collections.Counter()
    for res in results:
        overall.update(res["hist"])
    spans = sorted(res["max"] - res["min"] for res in results)
    print(f"realized scan angle range {min(overall)}..{max(overall)} degrees; per-tile span "
          f"min={spans[0]} median={spans[len(spans) // 2]} max={spans[-1]}; "
          f"overall zero fraction {overall.get(0, 0) / total:.4f}; "
          f"max per-tile mode share {max(r['mode_share'] for r in results):.3f}")
    print(f"verified family={SERIES_ID} samples={len(results)} total_values={total} "
          f"median_values={median} min_values={min(counts)} max_values={max(counts)}")


if __name__ == "__main__":
    main()
