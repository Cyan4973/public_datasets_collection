#!/usr/bin/env python3
"""Emit one raw uint8 800x800 DN frame per pinned Voyager 2 ISSN Saturn raw image."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgiss  # noqa: E402

EXPECTED_SOURCES = 339
NATURAL_RECORD_KIND = "voyager_iss_decompressed_raw_vidicon_frame"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    data_dir = args.data_dir
    sources = vgiss.read_sources(args.recipe_dir / "sources.tsv")
    if len(sources) != EXPECTED_SOURCES:
        raise SystemExit(f"expected {EXPECTED_SOURCES} sources, found {len(sources)}")
    download_dir = data_dir / "downloads" / vgiss.DATASET_ID
    raw_dir = download_dir / "raw"

    # The pinned list must still be exactly what the selection rule yields on the local index.
    index_rows = vgiss.parse_index(download_dir / "index" / "INDEX.TAB")
    derived = [(r["image_number"], r["file_specification_name"][: -len(".LBL")]) for r in vgiss.select(index_rows)]
    if derived != [(s["image_number"], s["volume_path"]) for s in sources]:
        raise SystemExit("selection re-derived from local INDEX.TAB differs from sources.tsv")

    sample_root = data_dir / "samples" / vgiss.DATASET_ID
    series_dir = sample_root / vgiss.SERIES_ID
    index_dir = data_dir / "index" / vgiss.DATASET_ID
    filtered_dir = data_dir / "filtered" / vgiss.DATASET_ID
    for path in (sample_root, index_dir):
        if path.exists():
            shutil.rmtree(path)
    series_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    frames = []
    excluded = []
    seen: dict[str, str] = {}
    aggregate = hashlib.sha256()
    histogram = [0] * 256
    histogram_exact = 0
    for source in sources:
        product, image_number = source["product"], source["image_number"]
        img = raw_dir / f"{product}_RAW.IMG"
        lbl = raw_dir / f"{product}_RAW.LBL"
        if not img.is_file() or not lbl.is_file():
            raise SystemExit(f"missing local download for {product}; run download.sh first")
        lbl_blob = lbl.read_bytes()
        if len(lbl_blob) != int(source["lbl_size"]) or vgiss.digests(lbl_blob)[0] != source["lbl_md5"]:
            raise SystemExit(f"{lbl.name}: size/MD5 differ from pin")
        label = vgiss.check_label(lbl_blob.decode("ascii"), image_number, product)
        raw = img.read_bytes()
        if len(raw) != int(source["img_size"]) or vgiss.digests(raw)[0] != source["img_md5"]:
            raise SystemExit(f"{img.name}: size/MD5 differ from pin")
        pixels, stats = vgiss.decode(raw, image_number, product)
        frame_hist = stats.pop("histogram")
        reason = vgiss.excluded_reason(stats)
        frame = {"product": product, "image_number": image_number, "target_name": source["target_name"],
                 "filter_name": source["filter_name"], "exposure_s": float(source["exposure_s"]),
                 "shutter_mode": source["shutter_mode"], "image_time": source["image_time"], **stats}
        if reason:
            excluded.append({**frame, "reason": reason})
            print(f"excluded product={product} reason={reason}")
            continue
        sample_hash = hashlib.sha256(pixels).hexdigest()
        if sample_hash in seen:
            raise SystemExit(f"{product} duplicates {seen[sample_hash]}")
        seen[sample_hash] = product
        for value, count in enumerate(frame_hist):
            histogram[value] += count
        histogram_exact += int(stats["embedded_histogram_exact"])
        sample_path = series_dir / f"{product}.u8"
        tmp = sample_path.with_suffix(".u8.part")
        tmp.write_bytes(pixels)
        tmp.rename(sample_path)
        aggregate.update(sample_hash.encode("ascii"))
        rows.append({
            "dataset_id": vgiss.DATASET_ID,
            "series_id": vgiss.SERIES_ID,
            "sample_path": str(sample_path.relative_to(data_dir)),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(pixels),
            "value_count": len(pixels),
            "role": "primary",
            "sample_shape": [vgiss.LINES, vgiss.SAMPLES],
            "sample_axes": ["vidicon_line", "vidicon_sample"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_url": source["img_url"],
            "product_id": label["PRODUCT_ID"],
            "image_number": image_number,
            "image_id": source["image_id"],
            "image_time": source["image_time"],
            "target_name": source["target_name"],
            "filter_name": source["filter_name"],
            "exposure_s": float(source["exposure_s"]),
            "shutter_mode": source["shutter_mode"],
            "fill_lines": stats["fill_lines"],
            "zero_pixels": stats["zero_pixels"],
            "minimum": stats["minimum"],
            "maximum": stats["maximum"],
            "distinct_values": stats["distinct_values"],
            "sha256": sample_hash,
        })
        frames.append(frame)
        print(f"emitted product={product} target={source['target_name']} filter={source['filter_name']} "
              f"exp={source['exposure_s']} min={stats['minimum']} max={stats['maximum']} mean={stats['mean']} "
              f"fill_lines={stats['fill_lines']} hist_exact={stats['embedded_histogram_exact']}")

    if not rows:
        raise SystemExit("no frames emitted")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    total = sum(row["sample_size_bytes"] for row in rows)
    summary = {
        "dataset_id": vgiss.DATASET_ID,
        "series_id": vgiss.SERIES_ID,
        "pinned_sources": len(sources),
        "sample_count": len(rows),
        "excluded_count": len(excluded),
        "total_size_bytes": total,
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "embedded_histogram_exact_frames": histogram_exact,
        "frames_with_fill_lines": sum(1 for f in frames if f["fill_lines"]),
        "image_time_range": [rows[0]["image_time"], rows[-1]["image_time"]],
        "dn_histogram": histogram,
        "excluded": excluded,
        "frames": frames,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"build summary samples={len(rows)} excluded={len(excluded)} bytes={total} "
          f"hist_exact={histogram_exact} aggregate_sha256={aggregate.hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
