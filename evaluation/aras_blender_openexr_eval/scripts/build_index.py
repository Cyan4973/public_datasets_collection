#!/usr/bin/env python3
"""Build the evaluation-only sample index from native EXR channel planes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


DATASET_ID = "aras_blender_openexr_eval"
SERIES = {
    "HALF": ("blender_exr_channel_plane_f16", 16, 2),
    "FLOAT": ("blender_exr_channel_plane_f32", 32, 4),
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--eval-root", required=True, type=Path)
    args = parser.parse_args()

    selected = [
        row
        for row in csv.DictReader(args.selection.open(encoding="utf-8"), delimiter="\t")
        if row["kind"] == "exr"
    ]
    expected = {
        row["name"]: {
            "width": int(row["width"]),
            "height": int(row["height"]),
            "HALF": int(row["half_channels"]),
            "FLOAT": int(row["float_channels"]),
        }
        for row in selected
    }
    filtered = args.eval_root / "filtered"
    samples = args.eval_root / "samples"
    index = args.eval_root / "index" / "samples.jsonl"
    rows: list[dict[str, object]] = []
    observed_counts = {name: {"HALF": 0, "FLOAT": 0} for name in expected}

    for stats_path in sorted(filtered.glob("decode_*.tsv")):
        for source in csv.DictReader(stats_path.open(encoding="utf-8"), delimiter="\t"):
            source_name = source["source_file"]
            pixel_type = source["pixel_type"]
            if source_name not in expected or pixel_type not in SERIES:
                raise SystemExit(f"unexpected decoded source/type: {source_name} {pixel_type}")
            width, height = int(source["width"]), int(source["height"])
            if (width, height) != (expected[source_name]["width"], expected[source_name]["height"]):
                raise SystemExit(f"geometry mismatch: {source_name}")
            series_id, bit_width, element_size = SERIES[pixel_type]
            observed_counts[source_name][pixel_type] += 1
            output = samples / source["output_file"]
            value_count = int(source["value_count"])
            sample_size = int(source["sample_size_bytes"])
            if value_count != width * height or sample_size != value_count * element_size:
                raise SystemExit(f"decoded count mismatch: {source_name} {source['channel']}")
            if not output.is_file() or output.stat().st_size != sample_size:
                raise SystemExit(f"missing or wrong-size output: {output}")
            constant = source["is_constant"] == "true"
            finite_count = int(source["finite_count"])
            nonfinite_count = int(source["nonfinite_count"])
            if finite_count + nonfinite_count != value_count:
                raise SystemExit(f"finite accounting mismatch: {output}")
            row: dict[str, object] = {
                "dataset_id": DATASET_ID,
                "series_id": series_id,
                "role": "evaluation",
                "intended_use": "evaluation_only",
                "training_eligible": False,
                "redistribution_authorized": False,
                "benchmark_eligible": not constant,
                "benchmark_exclusion_reason": "constant_plane" if constant else "",
                "sample_path": output.relative_to(args.eval_root).as_posix(),
                "source_sample": f"downloads/{source_name}",
                "source_channel_index": int(source["channel_index"]),
                "source_channel": source["channel"],
                "source_pixel_type": pixel_type,
                "container_format": "openexr",
                "compression": source["compression"],
                "numeric_kind": "float",
                "bit_width": bit_width,
                "endianness": "little",
                "element_size_bytes": element_size,
                "sample_format": f"raw homogeneous little-endian IEEE-754 binary{bit_width} OpenEXR channel plane",
                "sample_geometry": "2d_openexr_channel_plane",
                "sample_rank": 2,
                "sample_shape": [height, width],
                "sample_axes": ["y", "x"],
                "natural_record_kind": "openexr_channel_plane",
                "value_count": value_count,
                "sample_size_bytes": sample_size,
                "finite_count": finite_count,
                "nonfinite_count": nonfinite_count,
                "zero_count": int(source["zero_count"]),
                "is_constant": constant,
                "minimum_finite": float(source["min_value"]) if source["min_value"] else None,
                "maximum_finite": float(source["max_value"]) if source["max_value"] else None,
                "sha256": sha256(output),
            }
            rows.append(row)

    if len(rows) != 121 or len({(row["source_sample"], row["source_channel_index"]) for row in rows}) != 121:
        raise SystemExit(f"expected 121 unique channel planes, found {len(rows)}")
    for name, counts in observed_counts.items():
        for pixel_type in SERIES:
            if counts[pixel_type] != expected[name][pixel_type]:
                raise SystemExit(f"channel count mismatch: {name} {pixel_type} {counts[pixel_type]}")

    rows.sort(key=lambda row: (str(row["source_sample"]), int(row["source_channel_index"])))
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")

    series_stats = {}
    for pixel_type, (series_id, bit_width, _) in SERIES.items():
        subset = [row for row in rows if row["source_pixel_type"] == pixel_type]
        series_stats[series_id] = {
            "bit_width": bit_width,
            "sample_count": len(subset),
            "benchmark_eligible_count": sum(bool(row["benchmark_eligible"]) for row in subset),
            "constant_count": sum(bool(row["is_constant"]) for row in subset),
            "nonfinite_plane_count": sum(int(row["nonfinite_count"]) > 0 for row in subset),
            "value_count": sum(int(row["value_count"]) for row in subset),
            "size_bytes": sum(int(row["sample_size_bytes"]) for row in subset),
        }
    stats = {
        "dataset_id": DATASET_ID,
        "intended_use": "evaluation_only",
        "training_eligible": False,
        "redistribution_authorized": False,
        "source_count": len(selected),
        "sample_count": len(rows),
        "benchmark_eligible_count": sum(bool(row["benchmark_eligible"]) for row in rows),
        "constant_count": sum(bool(row["is_constant"]) for row in rows),
        "total_values": sum(int(row["value_count"]) for row in rows),
        "total_size_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "series": series_stats,
    }
    (filtered / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
