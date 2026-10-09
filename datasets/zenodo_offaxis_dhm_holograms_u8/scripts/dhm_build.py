#!/usr/bin/env python3
"""Build raw uint8 hologram samples from the locally downloaded DHM TIFFs."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import sys
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dhm_tiff  # noqa: E402

DATASET_ID = "zenodo_offaxis_dhm_holograms_u8"
SERIES_ID = "dhm_offaxis_hologram_u8"
FRAME_BYTES = 2048 * 2048


def sample_name(key: str, frame: int) -> str:
    return f"{key[:-4].replace('.', '-').replace(' ', '_')}_f{frame:05d}.bin"


def frame_stats(px: bytes) -> dict[str, object]:
    hist = collections.Counter(px)
    top_value, top_count = hist.most_common(1)[0]
    w = 2048
    # Mean absolute horizontal neighbour difference over 64 evenly spaced rows:
    # large along rows for every carrier geometry in this deposit (measured
    # 26-101 DN), small only for fringe-less frames.
    acc = 0
    n = 0
    for r in range(0, 2048, 32):
        row = px[r * w : (r + 1) * w]
        acc += sum(abs(a - b) for a, b in zip(row, row[1:]))
        n += w - 1
    return {
        "min": min(hist),
        "max": max(hist),
        "distinct_values": len(hist),
        "mode_value": top_value,
        "mode_fraction": round(top_count / len(px), 6),
        "saturated_255_fraction": round(hist.get(255, 0) / len(px), 6),
        "mean": round(sum(v * c for v, c in hist.items()) / len(px), 4),
        "mean_abs_horizontal_diff": round(acc / n, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()
    recipe = Path(args.recipe)
    root = Path(args.data_root)
    dl = root / "downloads" / DATASET_ID
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"

    with open(recipe / "videos.tsv", encoding="utf-8") as h:
        videos = {r["key"]: r for r in csv.DictReader(h, delimiter="\t")}
    with open(recipe / "selected_frames.tsv", encoding="utf-8") as h:
        selected = list(csv.DictReader(h, delimiter="\t"))
    if len(selected) != 102 or len(videos) != 17:
        raise SystemExit(f"unexpected pin counts: frames={len(selected)} videos={len(videos)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    expected_names = {sample_name(r["key"], int(r["frame"])) for r in selected}
    for stale in out_dir.glob("*.bin"):
        if stale.name not in expected_names:
            stale.unlink()

    rows = []
    digests: dict[str, str] = {}
    legacy_total = 0
    t0 = time.time()
    for i, r in enumerate(selected, 1):
        key = r["key"]
        frame = int(r["frame"])
        tif_path = dl / "tif" / key[:-4] / f"{frame:05d}_holo.tif"
        data = tif_path.read_bytes()
        if len(data) != int(r["uncompressed_size"]) or f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != r["crc32_hex"]:
            raise SystemExit(f"local TIFF does not match pinned size/CRC32: {tif_path}")
        try:
            px, meta = dhm_tiff.decode_frame(data)
        except dhm_tiff.TiffFormatError as exc:
            raise SystemExit(f"{tif_path}: {exc}")
        if len(px) != FRAME_BYTES:
            raise SystemExit(f"{tif_path}: decoded {len(px)} bytes")
        st = frame_stats(px)
        if st["distinct_values"] < 64 or st["mode_fraction"] > 0.05 or st["mean_abs_horizontal_diff"] < 8:
            raise SystemExit(f"{tif_path}: degenerate or fringe-less frame {st}")
        digest = hashlib.sha256(px).hexdigest()
        if digest in digests:
            raise SystemExit(f"{tif_path}: duplicate of {digests[digest]}")
        name = sample_name(key, frame)
        digests[digest] = name
        dest = out_dir / name
        tmp = dest.with_suffix(".bin.part")
        tmp.write_bytes(px)
        tmp.replace(dest)
        legacy_total += meta["legacy_eoi_strips"]
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(dest.relative_to(root)),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": FRAME_BYTES,
                "value_count": FRAME_BYTES,
                "shape": [2048, 2048],
                "axes": ["camera_row", "camera_col"],
                "source_zip": key,
                "source_member": r["name"],
                "source_frame": frame,
                "video_frame_count": int(videos[key]["holograms"]),
                "tiff_crc32": r["crc32_hex"],
                "legacy_eoi_strips": meta["legacy_eoi_strips"],
                "sha256": digest,
                **st,
            }
        )
        print(f"[{time.time() - t0:7.1f}s] {i}/{len(selected)} {name} min={st['min']} max={st['max']} "
              f"distinct={st['distinct_values']} hdiff={st['mean_abs_horizontal_diff']}", flush=True)

    tmp_index = index_path.with_suffix(".jsonl.part")
    with open(tmp_index, "w", encoding="utf-8") as h:
        for row in rows:
            h.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.replace(index_path)
    agg = hashlib.sha256()
    for row in rows:
        agg.update(bytes.fromhex(row["sha256"]))
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "videos": len(videos),
        "samples": len(rows),
        "total_size_bytes": FRAME_BYTES * len(rows),
        "frames_per_video": 6,
        "legacy_eoi_strips_total": legacy_total,
        "aggregate_sha256_of_sample_sha256s": agg.hexdigest(),
        "per_video": {
            k: [row["source_frame"] for row in rows if row["source_zip"] == k] for k in videos
        },
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build=ok samples={len(rows)} bytes={FRAME_BYTES * len(rows)} legacy_eoi_strips={legacy_total} "
          f"aggregate={agg.hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
