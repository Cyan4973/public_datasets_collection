#!/usr/bin/env python3
"""Emit one raw uint8 1024x1024 DN frame per pinned Cassini ISS NAC TABLE/FULL EDR (local files only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coiss  # noqa: E402

EXPECTED_SOURCES = 314
NATURAL_RECORD_KIND = "cassini_iss_nac_edr_table8_full_frame"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    data_dir = args.data_dir
    sources = coiss.read_sources(args.recipe_dir / "sources.tsv")
    if len(sources) != EXPECTED_SOURCES:
        raise SystemExit(f"expected {EXPECTED_SOURCES} sources, found {len(sources)}")
    download_dir = data_dir / "downloads" / coiss.DATASET_ID
    raw_dir = download_dir / "raw"
    index_dir_in = download_dir / "index"

    # The pinned list must still be exactly what the selection rule yields on the local indexes.
    rows = []
    for vol in coiss.VOLUMES:
        label = (index_dir_in / f"{vol}_index.lbl").read_text(encoding="ascii")
        rows += coiss.parse_index((index_dir_in / f"{vol}_index.tab").read_bytes(), label, vol)
    derived = coiss.selection_keys(coiss.select(rows))
    if derived != [(s["volume"], s["file_specification_name"], s["image_number"]) for s in sources]:
        raise SystemExit("selection re-derived from local index.tab files differs from sources.tsv")

    sample_root = data_dir / "samples" / coiss.DATASET_ID
    series_dir = sample_root / coiss.SERIES_ID
    index_dir = data_dir / "index" / coiss.DATASET_ID
    filtered_dir = data_dir / "filtered" / coiss.DATASET_ID
    for path in (sample_root, index_dir):
        if path.exists():
            shutil.rmtree(path)
    series_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    out_rows = []
    frames = []
    excluded = []
    seen: dict[str, str] = {}
    aggregate = hashlib.sha256()
    histogram = [0] * 256
    for source in sources:
        volume, product, image_number = source["volume"], source["product"], source["image_number"]
        img = raw_dir / f"{volume}_{product}.IMG"
        if not img.is_file():
            raise SystemExit(f"missing local download {img}; run download.sh first")
        raw = img.read_bytes()
        if len(raw) != int(source["img_size"]) or coiss.digests(raw)[0] != source["img_md5"]:
            raise SystemExit(f"{img.name}: size/MD5 differ from pin")
        pixels, stats = coiss.decode(raw, product, image_number)
        frame_hist = stats.pop("histogram")
        if stats["observation_id"] != source["observation_id"] or stats["target_name"] != source["target_name"]:
            raise SystemExit(f"{product}: VICAR observation/target disagree with the index")
        reason = coiss.excluded_reason(stats)
        frame = {"volume": volume, "product": product, "image_number": image_number,
                 "observation_id": source["observation_id"], "target_name": source["target_name"],
                 "target_desc": source["target_desc"], "filter_name": source["filter_name"],
                 "exposure_ms": float(source["exposure_ms"]), "image_time": source["image_time"], **stats}
        if reason:
            excluded.append({**frame, "reason": reason})
            print(f"excluded product={product} observation={source['observation_id']} reason={reason}")
            continue
        sample_hash = hashlib.sha256(pixels).hexdigest()
        if sample_hash in seen:
            raise SystemExit(f"{product} duplicates {seen[sample_hash]}")
        seen[sample_hash] = product
        for value, count in enumerate(frame_hist):
            histogram[value] += count
        sample_path = series_dir / f"{product}.u8"
        tmp = sample_path.with_suffix(".u8.part")
        tmp.write_bytes(pixels)
        tmp.rename(sample_path)
        aggregate.update(sample_hash.encode("ascii"))
        out_rows.append({
            "dataset_id": coiss.DATASET_ID,
            "series_id": coiss.SERIES_ID,
            "sample_path": str(sample_path.relative_to(data_dir)),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(pixels),
            "value_count": len(pixels),
            "role": "primary",
            "sample_shape": [coiss.LINES, coiss.SAMPLES],
            "sample_axes": ["ccd_line", "ccd_sample"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_url": source["img_url"],
            "volume_id": volume,
            "product": product,
            "image_number": image_number,
            "observation_id": source["observation_id"],
            "target_name": source["target_name"],
            "target_desc": source["target_desc"],
            "filter_name": source["filter_name"],
            "exposure_ms": float(source["exposure_ms"]),
            "image_time": source["image_time"],
            "minimum": stats["minimum"],
            "maximum": stats["maximum"],
            "distinct_values": stats["distinct_values"],
            "mode_share": stats["mode_share"],
            "sha256": sample_hash,
        })
        frames.append(frame)
        print(f"emitted product={product} target={source['target_name']} obs={source['observation_id']} "
              f"min={stats['minimum']} max={stats['maximum']} mean={stats['mean']} "
              f"distinct={stats['distinct_values']} mode_share={stats['mode_share']}")

    if not out_rows:
        raise SystemExit("no frames emitted")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in out_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    total = sum(row["sample_size_bytes"] for row in out_rows)
    summary = {
        "dataset_id": coiss.DATASET_ID,
        "series_id": coiss.SERIES_ID,
        "pinned_sources": len(sources),
        "sample_count": len(out_rows),
        "excluded_count": len(excluded),
        "total_size_bytes": total,
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "observations": len({row["observation_id"] for row in out_rows}),
        "image_time_range": [out_rows[0]["image_time"], out_rows[-1]["image_time"]],
        "dn_histogram": histogram,
        "excluded": excluded,
        "frames": frames,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"build summary samples={len(out_rows)} excluded={len(excluded)} bytes={total} "
          f"observations={summary['observations']} aggregate_sha256={aggregate.hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
