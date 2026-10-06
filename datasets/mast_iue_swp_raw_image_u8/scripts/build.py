#!/usr/bin/env python3
"""Emit one raw uint8 768x768 SWP detector frame per pinned IUE RILO file."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iue_rilo as rilo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    data_dir = args.data_dir
    sources = rilo.read_sources(args.recipe_dir / "sources.tsv")
    if len(sources) != rilo.EXPECTED_SOURCES:
        raise SystemExit(f"expected {rilo.EXPECTED_SOURCES} sources, found {len(sources)}")
    download_dir = data_dir / "downloads" / rilo.DATASET_ID / "rilo"
    sample_root = data_dir / "samples" / rilo.DATASET_ID
    series_dir = sample_root / rilo.SERIES_ID
    index_dir = data_dir / "index" / rilo.DATASET_ID
    filtered_dir = data_dir / "filtered" / rilo.DATASET_ID
    for path in (sample_root, index_dir):
        if path.exists():
            shutil.rmtree(path)
    series_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    frames = []
    seen_hashes: dict[str, int] = {}
    aggregate = hashlib.sha256()
    histogram = [0] * 256
    for source in sources:
        image_no = int(source["image_no"])
        path = download_dir / source["filename"]
        if not path.is_file():
            raise SystemExit(f"missing local download {path}; run download.sh first")
        if path.stat().st_size != int(source["size_bytes"]):
            raise SystemExit(f"{path.name}: size {path.stat().st_size} != pinned {source['size_bytes']}")
        if source["sha256"]:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != source["sha256"]:
                raise SystemExit(f"{path.name}: SHA-256 {digest} != pinned {source['sha256']}")
        raw = rilo.gunzip_checked(path, source["gzip_crc32"], int(source["gzip_isize"]))
        pixels, cards = rilo.decode(raw, image_no)
        stats = rilo.structure_stats(pixels)
        rilo.check_structure(stats, image_no)
        sample_hash = hashlib.sha256(pixels).hexdigest()
        if sample_hash in seen_hashes:
            raise SystemExit(f"image {image_no} duplicates image {seen_hashes[sample_hash]}")
        seen_hashes[sample_hash] = image_no
        for value in pixels:
            histogram[value] += 1
        sample_path = series_dir / f"swp{image_no:05d}.u8"
        tmp = sample_path.with_suffix(".u8.part")
        tmp.write_bytes(pixels)
        tmp.rename(sample_path)
        aggregate.update(sample_hash.encode("ascii"))
        rows.append({
            "dataset_id": rilo.DATASET_ID,
            "series_id": rilo.SERIES_ID,
            "sample_path": str(sample_path.relative_to(data_dir)),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(pixels),
            "value_count": len(pixels),
            "role": "primary",
            "sample_shape": [rilo.LINES, rilo.SAMPLES],
            "sample_axes": ["vidicon_scan_line", "vidicon_sample"],
            "natural_record_kind": "iue_swp_low_dispersion_raw_camera_image",
            "source_file": source["filename"],
            "source_url": source["url"],
            "iue_camera": cards["CAMERA"],
            "iue_image": image_no,
            "obs_date_ddmmyy": cards.get("LDATEOBS", ""),
            "exposure_s": float(cards["LEXPTIME"]),
            "iue_object_class": int(cards["LIUECLAS"]),
            "thda_at_read_c": float(cards["THDAREAD"]) if cards.get("THDAREAD") else None,
            "minimum": stats["minimum"],
            "maximum": stats["maximum"],
            "distinct_values": stats["distinct_values"],
            "sha256": sample_hash,
        })
        frames.append({"image": image_no, **stats, "exposure_s": float(cards["LEXPTIME"]),
                       "object_class": int(cards["LIUECLAS"]), "target": source["target"],
                       "obs_start_time": source["obs_start_time"]})
        print(f"emitted image={image_no} bytes={len(pixels)} min={stats['minimum']} max={stats['maximum']} "
              f"distinct={stats['distinct_values']} center={stats['center_mean']} corner={stats['corner_mean_max']}")

    index_path = index_dir / "samples.jsonl"
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    summary = {
        "dataset_id": rilo.DATASET_ID,
        "series_id": rilo.SERIES_ID,
        "sample_count": len(rows),
        "total_size_bytes": total_bytes,
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "image_range": [rows[0]["iue_image"], rows[-1]["iue_image"]],
        "obs_years": sorted({f["obs_start_time"][:4] for f in frames}),
        "distinct_object_classes": len({f["object_class"] for f in frames}),
        "dn_histogram": histogram,
        "frames": frames,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"build summary samples={len(rows)} bytes={total_bytes} aggregate_sha256={aggregate.hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
