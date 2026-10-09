#!/usr/bin/env python3
"""Independent verification for apple_hypersim_normal_cam_f16.

* re-derives the frame selection from the downloaded, sha256-pinned split CSV
  and requires it to equal sources.tsv; checks the README license statement
* for every sample: member sha256/CRC vs sidecar, fresh HDF5 decode must be
  byte-identical to the sample file, sample sha256 vs index, index fields
* recomputes all per-frame statistics through an independent binary16
  conversion (explicit sign/exponent/mantissa bit arithmetic, cross-checked
  against struct's 'e' codec for all 65,536 words) and enforces the same
  fatal missing-value policy as build.py and re-derives the degenerate-frame
  drop set, which must equal build_stats.json and be absent from the output
* rejects duplicates, stray files, constant samples; checks floors, the 1 GB
  cap and the manifest's sample_count / total_size_bytes
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypersim_h5  # noqa: E402
import selection  # noqa: E402

DATASET_ID = "apple_hypersim_normal_cam_f16"
SERIES_ID = "normal_cam_f16"
SHAPE = (768, 1024, 3)
VALUES = SHAPE[0] * SHAPE[1] * SHAPE[2]
PIXELS = SHAPE[0] * SHAPE[1]
SAMPLE_BYTES = VALUES * 2
CSV_SHA256 = "47b7cce12f4659ffa31cf05e8fbf2aee3d69e1929d07b5ea25506603b69d5ce6"
README_SHA256 = "1141b4943d26a33e0c3b5efc0660db5088b0a972d51e2e52c7ef60044e7b851d"
LICENSE_LINE = ("The Hypersim Dataset is licensed under the [Creative Commons Attribution-ShareAlike 3.0 "
                "Unported License](http://creativecommons.org/licenses/by-sa/3.0/).")
MAX_ABS = 8.0
MIN_FINITE_PIXEL_FRACTION = 0.5
MIN_UNIT_PIXEL_FRACTION = 0.5
UNIT_TOL = 0.01
MAX_TOP_PIXEL_FRACTION = 0.9
MIN_DISTINCT_WORDS = 256
MAX_PRIMARY_BYTES = 1_000_000_000


def half_bits(word: int) -> float:
    sign = -1.0 if word & 0x8000 else 1.0
    exp = (word >> 10) & 0x1F
    frac = word & 0x3FF
    if exp == 0x1F:
        return math.nan if frac else sign * math.inf
    if exp == 0:
        return sign * frac * 2.0 ** -24
    return sign * (1.0 + frac / 1024.0) * 2.0 ** (exp - 15)


def build_table() -> list[float]:
    table = [half_bits(w) for w in range(65536)]
    ref = struct.unpack("<65536e", struct.pack("<65536H", *range(65536)))
    for w in range(65536):
        a, b = table[w], ref[w]
        if not ((a != a and b != b) or a == b):
            raise SystemExit(f"binary16 conversion mismatch at word {w:04x}: {a} vs {b}")
    return table


def stats(raw: bytes, table: list[float]) -> dict:
    words = struct.unpack(f"<{VALUES}H", raw)
    nan = sum(1 for w in words if (w & 0x7C00) == 0x7C00 and w & 0x3FF)
    inf = sum(1 for w in words if (w & 0x7FFF) == 0x7C00)
    lo, hi = math.inf, -math.inf
    for w in set(words):
        v = table[w]
        if math.isfinite(v):
            lo = min(lo, v)
            hi = max(hi, v)
    finite_pix = unit_pix = 0
    trip = collections.Counter()
    for p in range(PIXELS):
        a, b, c = words[3 * p], words[3 * p + 1], words[3 * p + 2]
        trip[(a, b, c)] += 1
        x, y, z = table[a], table[b], table[c]
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
            finite_pix += 1
            if abs(math.sqrt(x * x + y * y + z * z) - 1.0) <= UNIT_TOL:
                unit_pix += 1
    return {
        "nan_value_count": nan,
        "inf_value_count": inf,
        "min": None if lo == math.inf else lo,
        "max": None if hi == -math.inf else hi,
        "distinct_word_count": len(set(words)),
        "finite_pixel_fraction": round(finite_pix / PIXELS, 6),
        "unit_norm_pixel_fraction": round(unit_pix / PIXELS, 6),
        "top_pixel_fraction": round(trip.most_common(1)[0][1] / PIXELS, 6),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    ap.add_argument("--data-dir", default=".data")
    args = ap.parse_args()
    data_root = Path(args.data_dir)
    if not data_root.is_absolute():
        data_root = args.repo_root / data_root
    dl = data_root / "downloads" / DATASET_ID
    member_dir = dl / "members"
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    fails: list[str] = []

    # ---- upstream metadata, selection
    csv_path = dl / "upstream" / "metadata_images_split_scene_v1.csv"
    readme = dl / "upstream" / "README.md"
    if hashlib.sha256(csv_path.read_bytes()).hexdigest() != CSV_SHA256:
        fails.append("split CSV sha256 mismatch")
    if hashlib.sha256(readme.read_bytes()).hexdigest() != README_SHA256:
        fails.append("README sha256 mismatch")
    if LICENSE_LINE not in readme.read_text(encoding="utf-8"):
        fails.append("README lacks the CC BY-SA 3.0 statement")
    with open(args.recipe_dir / "sources.tsv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    derived = selection.select(str(csv_path))
    if [{k: r[k] for k in selection.COLUMNS} for r in rows] != derived:
        fails.append("sources.tsv differs from the selection re-derived from the split CSV")

    # ---- index: every source member is decoded and classified independently
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {}
    for idx in index:
        if idx.get("sample_path") in by_path:
            fails.append(f"duplicate index row {idx.get('sample_path')}")
        by_path[idx.get("sample_path")] = idx
    build_stats = json.loads((data_root / "filtered" / DATASET_ID / "build_stats.json").read_text())
    recorded_drops = {d["sample"] for d in build_stats.get("dropped_degenerate", [])}
    table = build_table()
    seen_sha: set[str] = set()
    expected_files = set()
    expected_drops = set()
    unit_fracs = []
    for row in rows:
        base = f"{row['scene_name']}.{row['camera_name']}.frame.{int(row['frame_id']):04d}.normal_cam"
        name = f"{row['scene_name']}__{row['camera_name']}__frame_{int(row['frame_id']):04d}.f16"
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{name}"
        member = (member_dir / f"{base}.hdf5").read_bytes()
        meta = json.loads((member_dir / f"{base}.json").read_text())
        msha = hashlib.sha256(member).hexdigest()
        if (msha != meta["member_sha256"]
                or f"{zlib.crc32(member) & 0xFFFFFFFF:08x}" != meta["member_crc32"]
                or meta["member_name"] != row["member_name"]):
            fails.append(f"{name}: member identity mismatch")
            continue
        dec = hypersim_h5.decode_file(member, "dataset")
        if dec.dataset.shape != SHAPE or dec.dataset.typecode != "e" or len(dec.raw) != SAMPLE_BYTES:
            fails.append(f"{name}: member does not decode to float16{SHAPE}")
            continue
        st = stats(dec.raw, table)
        # fatal policy (same as build.py)
        if st["min"] is None or max(abs(st["min"]), abs(st["max"])) > MAX_ABS:
            fails.append(f"{name}: finite range {st['min']}..{st['max']}")
        if st["finite_pixel_fraction"] < MIN_FINITE_PIXEL_FRACTION:
            fails.append(f"{name}: finite pixel fraction {st['finite_pixel_fraction']}")
        if st["unit_norm_pixel_fraction"] < MIN_UNIT_PIXEL_FRACTION:
            fails.append(f"{name}: unit-norm pixel fraction {st['unit_norm_pixel_fraction']}")
        # drop rule (same as build.py): degenerate content
        if st["top_pixel_fraction"] > MAX_TOP_PIXEL_FRACTION or st["distinct_word_count"] < MIN_DISTINCT_WORDS:
            expected_drops.add(name)
            if rel in by_path or (sample_dir / name).exists():
                fails.append(f"{name}: degenerate frame (top={st['top_pixel_fraction']}, "
                             f"distinct={st['distinct_word_count']}) was emitted")
            continue
        expected_files.add(name)
        idx = by_path.get(rel)
        if idx is None:
            fails.append(f"{name}: non-degenerate frame missing from index")
            continue
        want = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "float", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": SAMPLE_BYTES, "value_count": VALUES,
            "shape": list(SHAPE), "scene_name": row["scene_name"], "camera_name": row["camera_name"],
            "frame_id": int(row["frame_id"]), "member_name": row["member_name"], "member_sha256": msha,
        }
        for key, value in want.items():
            if idx.get(key) != value:
                fails.append(f"{name}: index {key}={idx.get(key)!r}, expected {value!r}")
        sample = (sample_dir / name).read_bytes()
        if sample != dec.raw:
            fails.append(f"{name}: sample bytes differ from a fresh decode of the member")
            continue
        ssha = hashlib.sha256(sample).hexdigest()
        if ssha != idx.get("sample_sha256"):
            fails.append(f"{name}: sample sha256 differs from index")
        if ssha in seen_sha:
            fails.append(f"{name}: duplicate sample content")
        seen_sha.add(ssha)
        if sample == sample[:2] * VALUES:
            fails.append(f"{name}: constant sample")
        for key, value in st.items():
            if idx.get(key) != value:
                fails.append(f"{name}: index {key}={idx.get(key)!r}, recomputed {value!r}")
        unit_fracs.append(st["unit_norm_pixel_fraction"])
    if expected_drops != recorded_drops:
        fails.append(f"drop set {sorted(expected_drops)} != build_stats record {sorted(recorded_drops)}")
    if len(index) != len(expected_files):
        fails.append(f"index has {len(index)} rows, expected {len(expected_files)}")
    stray = sorted(p.name for p in sample_dir.iterdir() if p.name not in expected_files)
    if stray:
        fails.append(f"stray sample files: {stray[:5]}")

    # ---- floors, cap, manifest
    total = sum(int(r["sample_size_bytes"]) for r in index)
    values = sum(int(r["value_count"]) for r in index)
    counts = sorted(int(r["value_count"]) for r in index)
    median = counts[len(counts) // 2] if counts else 0
    if not (values >= 10_000 or total >= 100_000) or median < 1_000:
        fails.append(f"below floor: values={values} bytes={total} median={median}")
    if total > MAX_PRIMARY_BYTES:
        fails.append(f"primary bytes {total} exceed cap")
    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fails.append("manifest lacks the primary series")
    elif series[0]["sample_count"] != len(index) or series[0]["total_size_bytes"] != total:
        fails.append(f"manifest scope {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
                     f"!= realized {len(index)}/{total}")

    if fails:
        for f in fails[:50]:
            print(f"FAIL {f}", file=sys.stderr)
        print(f"verify FAILED with {len(fails)} problems", file=sys.stderr)
        return 1
    print(f"verify ok: samples={len(index)} values={values} bytes={total} median_values={median} "
          f"min_unit_norm_fraction={min(unit_fracs)} dropped_degenerate={sorted(expected_drops)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
