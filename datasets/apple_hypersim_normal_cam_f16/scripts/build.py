#!/usr/bin/env python3
"""Build apple_hypersim_normal_cam_f16 from local files only.

For every row of sources.tsv: check the downloaded member against its
sidecar (size, sha256, CRC-32, member name, zip size), decode the HDF5
`dataset` (float16[768, 1024, 3]) and write its binary16 words unchanged, in
C order (row, column, xyz component), little-endian, as one sample.  Writes
the sample index and filtered/<id>/build_stats.json.

Missing-value policy: nothing is filtered, rounded, renormalized, clipped or
imputed.  NaN/Inf words, if any, are kept with their stored bit patterns and
counted.  A frame is fatal (build fails) when:
  * the member does not match its sidecar or does not decode to
    float16[768, 1024, 3];
  * any finite component has magnitude > 8 (not a plausible normal field;
    real reconstruction-filter overshoot reaches about 5.6);
  * fewer than 50% of its pixels are finite triplets, fewer than 50% of its
    pixels have |n| within 0.01 of 1.
A frame is dropped and recorded in build_stats.json (degenerate content: e.g.
a wall filling the view) when a single pixel triplet covers more than 90% of
the frame or it has fewer than 256 distinct words.
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
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypersim_h5  # noqa: E402

DATASET_ID = "apple_hypersim_normal_cam_f16"
SERIES_ID = "normal_cam_f16"
SHAPE = (768, 1024, 3)
VALUES = SHAPE[0] * SHAPE[1] * SHAPE[2]
PIXELS = SHAPE[0] * SHAPE[1]
MAX_ABS = 8.0
MIN_FINITE_PIXEL_FRACTION = 0.5
MIN_UNIT_PIXEL_FRACTION = 0.5
UNIT_TOL = 0.01
MAX_TOP_PIXEL_FRACTION = 0.9
MIN_DISTINCT_WORDS = 256
DOMINANT_FLAG_FRACTION = 0.5


def member_base(row: dict) -> str:
    return f"{row['scene_name']}.{row['camera_name']}.frame.{int(row['frame_id']):04d}.normal_cam"


def sample_name(row: dict) -> str:
    return f"{row['scene_name']}__{row['camera_name']}__frame_{int(row['frame_id']):04d}.f16"


def frame_stats(raw: bytes) -> dict:
    words = struct.unpack(f"<{VALUES}H", raw)
    vals = struct.unpack(f"<{VALUES}e", raw)
    nan = inf = 0
    for w in words:
        if (w & 0x7C00) == 0x7C00:
            if w & 0x03FF:
                nan += 1
            else:
                inf += 1
    finite = [v for v in vals if math.isfinite(v)]
    trip = collections.Counter(zip(words[0::3], words[1::3], words[2::3]))
    finite_pix = unit_pix = 0
    for p in range(0, VALUES, 3):
        a, b, c = vals[p], vals[p + 1], vals[p + 2]
        if math.isfinite(a) and math.isfinite(b) and math.isfinite(c):
            finite_pix += 1
            if abs(math.sqrt(a * a + b * b + c * c) - 1.0) <= UNIT_TOL:
                unit_pix += 1
    top_word, top_count = trip.most_common(1)[0]
    return {
        "nan_value_count": nan,
        "inf_value_count": inf,
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "distinct_word_count": len(set(words)),
        "finite_pixel_fraction": round(finite_pix / PIXELS, 6),
        "unit_norm_pixel_fraction": round(unit_pix / PIXELS, 6),
        "top_pixel_fraction": round(top_count / PIXELS, 6),
        "top_pixel_words": [f"{w:04x}" for w in top_word],
    }


def policy_errors(st: dict) -> list[str]:
    errors = []
    if st["min"] is None or max(abs(st["min"]), abs(st["max"])) > MAX_ABS:
        errors.append(f"finite range {st['min']}..{st['max']} outside +-{MAX_ABS}")
    if st["finite_pixel_fraction"] < MIN_FINITE_PIXEL_FRACTION:
        errors.append(f"finite pixel fraction {st['finite_pixel_fraction']} < {MIN_FINITE_PIXEL_FRACTION}")
    if st["unit_norm_pixel_fraction"] < MIN_UNIT_PIXEL_FRACTION:
        errors.append(f"unit-norm pixel fraction {st['unit_norm_pixel_fraction']} < {MIN_UNIT_PIXEL_FRACTION}")
    return errors


def drop_reasons(st: dict) -> list[str]:
    """Degenerate-content rule: such frames are dropped and recorded, not fatal."""
    reasons = []
    if st["top_pixel_fraction"] > MAX_TOP_PIXEL_FRACTION:
        reasons.append(f"one pixel triplet covers {st['top_pixel_fraction']} of the frame")
    if st["distinct_word_count"] < MIN_DISTINCT_WORDS:
        reasons.append(f"only {st['distinct_word_count']} distinct words")
    return reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    ap.add_argument("--data-dir", default=".data")
    args = ap.parse_args()
    data_root = Path(args.data_dir)
    if not data_root.is_absolute():
        data_root = args.repo_root / data_root
    member_dir = data_root / "downloads" / DATASET_ID / "members"
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for d in (out_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)

    with open(args.recipe_dir / "sources.tsv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != 200:
        raise SystemExit(f"sources.tsv has {len(rows)} rows, expected 200")

    expected_names = {sample_name(r) for r in rows}
    for stale in out_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()

    index_rows = []
    flagged = []
    errors = []
    dropped = []
    for n, row in enumerate(rows, 1):
        base = member_base(row)
        member_path = member_dir / f"{base}.hdf5"
        meta = json.loads((member_dir / f"{base}.json").read_text())
        data = member_path.read_bytes()
        if (meta["member_name"] != row["member_name"] or meta["zip_size_bytes"] != int(row["zip_size_bytes"])
                or meta["member_size_bytes"] != len(data)
                or meta["member_sha256"] != hashlib.sha256(data).hexdigest()
                or f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != meta["member_crc32"]):
            raise SystemExit(f"FATAL: {member_path} does not match its sidecar")
        dec = hypersim_h5.decode_file(data, "dataset")
        ds = dec.dataset
        if dec.root_links != ["dataset"] or ds.shape != SHAPE or ds.typecode != "e" or len(dec.raw) != VALUES * 2:
            raise SystemExit(f"FATAL: {member_path}: links={dec.root_links} shape={ds.shape} type={ds.typecode}")
        st = frame_stats(dec.raw)
        bad = policy_errors(st)
        if bad:
            errors.append(f"{base}: {'; '.join(bad)}")
            continue
        drop = drop_reasons(st)
        if drop:
            dropped.append({"sample": sample_name(row), "scene_name": row["scene_name"], "reasons": drop,
                            "distinct_word_count": st["distinct_word_count"],
                            "top_pixel_fraction": st["top_pixel_fraction"]})
            print(f"DROP {base}: {'; '.join(drop)}")
            out = out_dir / sample_name(row)
            if out.exists():
                out.unlink()
            continue
        if st["top_pixel_fraction"] > DOMINANT_FLAG_FRACTION:
            flagged.append({"sample": sample_name(row), "top_pixel_fraction": st["top_pixel_fraction"]})
        out = out_dir / sample_name(row)
        tmp = out.with_suffix(".part")
        tmp.write_bytes(dec.raw)
        tmp.replace(out)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "float",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(dec.raw),
            "value_count": VALUES,
            "shape": list(SHAPE),
            "axes": ["image_row", "image_column", "normal_component_xyz"],
            "scene_name": row["scene_name"],
            "camera_name": row["camera_name"],
            "frame_id": int(row["frame_id"]),
            "member_name": row["member_name"],
            "member_sha256": meta["member_sha256"],
            "sample_sha256": hashlib.sha256(dec.raw).hexdigest(),
            **st,
        })
        if n % 20 == 0:
            print(f"built {n}/{len(rows)} last={base} unit={st['unit_norm_pixel_fraction']} top={st['top_pixel_fraction']}")
    if errors:
        for e in errors:
            print(f"POLICY FAIL {e}", file=sys.stderr)
        raise SystemExit(f"FATAL: {len(errors)} frames violate the missing-value/degeneracy policy")

    index_path = index_dir / "samples.jsonl"
    with open(index_path.with_suffix(".part"), "w", encoding="utf-8") as handle:
        for r in index_rows:
            handle.write(json.dumps(r, sort_keys=True) + "\n")
    index_path.with_suffix(".part").replace(index_path)
    total = sum(r["sample_size_bytes"] for r in index_rows)
    stats = {
        "samples": len(index_rows),
        "total_size_bytes": total,
        "total_values": sum(r["value_count"] for r in index_rows),
        "nan_value_count": sum(r["nan_value_count"] for r in index_rows),
        "inf_value_count": sum(r["inf_value_count"] for r in index_rows),
        "frames_with_nan": sum(1 for r in index_rows if r["nan_value_count"]),
        "min": min(r["min"] for r in index_rows),
        "max": max(r["max"] for r in index_rows),
        "min_unit_norm_pixel_fraction": min(r["unit_norm_pixel_fraction"] for r in index_rows),
        "frames_unit_norm_below_0.99": sum(1 for r in index_rows if r["unit_norm_pixel_fraction"] < 0.99),
        "max_top_pixel_fraction": max(r["top_pixel_fraction"] for r in index_rows),
        "dominant_value_flagged_over_0.5": flagged,
        "dropped_degenerate": dropped,
        "camera_fallbacks": [r["scene_name"] + ":" + r["camera_name"] for r in index_rows if r["camera_name"] != "cam_00"],
    }
    (filtered_dir / "build_stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("dominant_value_flagged_over_0.5", "dropped_degenerate")}, sort_keys=True))
    print(f"dropped degenerate frames: {len(dropped)}")
    print(f"dominant-value flags (top pixel triplet > {DOMINANT_FLAG_FRACTION}): {len(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
