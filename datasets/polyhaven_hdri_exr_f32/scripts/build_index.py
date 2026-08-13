#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


DATASET_ID = "polyhaven_hdri_exr_f32"
SERIES_ID = "hdri_float_planes_f32"
EXPECTED = {
    "abandoned_greenhouse_1k.exr": {
        "shape": (512, 1024), "channels": {"B", "G", "R"}, "compression": "zip",
        "sha256": "3ff5b53e171333ad410f8c0b7f491d0c3f3bd25a01b6d3f1262b710389a96d64",
    },
    "ph_brown_photostudio_02_8k.exr": {
        "shape": (4096, 8192), "channels": {"B", "G", "R"}, "compression": "piz",
        "sha256": "a1c7a7edf1bfb9cb7f9a252e7281f2f10767befdb9cb6c6a28209730a46e9642",
    },
    "ph_golden_gate_hills_4k.exr": {
        "shape": (2048, 4096), "channels": {"B", "G", "R"}, "compression": "zip",
        "sha256": "e0d76ca478552cef5f6b03e40be4943a1f4a4908ba17e308e9598f802681215f",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--filtered-dir", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--sample-dir", type=Path, required=True)
    args = parser.parse_args()

    decoded: list[dict[str, str]] = []
    for path in sorted(args.filtered_dir.glob("decode_*.tsv")):
        with path.open(newline="", encoding="utf-8") as handle:
            decoded.extend(csv.DictReader(handle, delimiter="\t"))
    if len(decoded) != 9:
        raise SystemExit(f"expected nine decoded RGB channel rows, found {len(decoded)}")

    observed = {name: set() for name in EXPECTED}
    rows = []
    for item in decoded:
        source = item["source_file"]
        if source not in EXPECTED:
            raise SystemExit(f"unexpected source row: {source}")
        spec = EXPECTED[source]
        height, width = spec["shape"]
        if (int(item["height"]), int(item["width"])) != (height, width):
            raise SystemExit(f"geometry mismatch: {item}")
        if item["compression"] != spec["compression"]:
            raise SystemExit(f"compression mismatch: {item}")
        if int(item["finite_count"]) != int(item["value_count"]):
            raise SystemExit(f"non-finite values: {item}")
        observed[source].add(item["channel"])
        output = args.sample_dir / item["output_file"]
        size = width * height * 4
        if output.stat().st_size != size:
            raise SystemExit(f"output size mismatch: {output}")
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": width * height,
            "sample_format": "raw OpenEXR FLOAT32 channel plane",
            "sample_geometry": "2d_hdr_radiance_plane",
            "sample_rank": 2,
            "sample_shape": [height, width],
            "sample_axes": ["y", "x"],
            "natural_record_kind": "openexr_channel_plane",
            "source_path": (args.download_dir / source).relative_to(args.data_root).as_posix(),
            "source_sha256": spec["sha256"],
            "container_format": "openexr",
            "channel": item["channel"],
            "compression": item["compression"],
            "minimum": float(item["min_value"]),
            "maximum": float(item["max_value"]),
            "zero_count": int(item["zero_count"]),
            "sha256": sha256_file(output),
        })

    for source, spec in EXPECTED.items():
        if observed[source] != spec["channels"]:
            raise SystemExit(f"channel inventory mismatch for {source}: {observed[source]}")

    rows.sort(key=lambda row: (row["source_path"], row["channel"]))
    args.index_dir.mkdir(parents=True, exist_ok=True)
    with (args.index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    sizes = [row["sample_size_bytes"] for row in rows]
    values = [row["value_count"] for row in rows]
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_count": 3,
        "sample_count": 9,
        "primary_values": sum(values),
        "primary_bytes": sum(sizes),
        "median_sample_values": statistics.median(values),
        "median_sample_bytes": statistics.median(sizes),
        "tinyexr_version": "v1.0.12",
        "tinyexr_sha256": "e3eb50490af81dc3f5f067cf7f62955894d5db8f88a091c19bc4eef8e468095f",
    }
    if stats["primary_values"] != 127401984 or stats["primary_bytes"] != 509607936:
        raise SystemExit(f"aggregate size mismatch: {stats}")
    (args.filtered_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
