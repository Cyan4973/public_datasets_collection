#!/usr/bin/env python3
"""Build int16 tri-axial vibration samples from the pinned CNC_Machining runs.

One sample per upstream HDF5 file (one execution of one machining operation):
the complete ``vibration_data`` array of shape (n, 3), emitted row-major as
interleaved X, Y, Z signed 16-bit little-endian integers.

Width policy (applied per file, never per value): every stored value must be
finite, exactly integral and within [-32768, 32767].  A file that violates
this anywhere is dropped whole and reported; nothing is rounded, clipped,
rescaled or imputed.  A float ``-0.0`` is the integer 0 and is counted, not
dropped.  Files whose whole sample, or any single axis, is constant are
dropped as degenerate; exact duplicate outputs are dropped after their first
occurrence.  The realized counts are written to ingest_stats.json.
"""
from __future__ import annotations

import argparse
import array
import collections
import csv
import hashlib
import json
import math
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cnc_h5  # noqa: E402

DATASET_ID = "bosch_cnc_milling_ciss_vibration_i16"
SERIES_ID = "cnc_ciss_vibration_xyz_i16"
EXPECTED_FILES = 1163
EXPECTED_SOURCE_BYTES = 642_164_273
DTYPE_TYPECODES = {"float32": "f", "float64": "d", "int64": "q"}
NATURAL_RECORD_KIND = "complete_cnc_machining_operation_run_vibration_record"
SOURCE_FORMAT = "HDF5 file per machining run (superblock v0, chunked, deflate)"
SOURCE_FIELD = "vibration_data[n, 3] tri-axial acceleration (X, Y, Z)"
SAMPLE_FORMAT = "raw little-endian int16 array, row-major (n, 3), interleaved X,Y,Z"
SAMPLE_GEOMETRY = "time_by_axis_2d_row_major"
SAMPLE_AXES = ["time_sample_2khz", "accelerometer_axis_xyz"]


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def load_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_FILES:
        raise SystemExit(f"sources.tsv lists {len(rows)} files, expected {EXPECTED_FILES}")
    if sum(int(r["size_bytes"]) for r in rows) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("sources.tsv byte total changed")
    paths = [r["path"] for r in rows]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise SystemExit("sources.tsv must be sorted by unique path")
    return rows


def classify_values(values: array.array, typecode: str) -> dict[str, int]:
    counts = {"non_finite": 0, "non_integral": 0, "out_of_int16": 0, "negative_zero": 0}
    is_float = typecode in "fd"
    for v in values:
        if is_float:
            if not math.isfinite(v):
                counts["non_finite"] += 1
                continue
            if not v.is_integer():
                counts["non_integral"] += 1
                continue
            if v == 0.0 and math.copysign(1.0, v) < 0:
                counts["negative_zero"] += 1
        if not -32768 <= v <= 32767:
            counts["out_of_int16"] += 1
    return counts


def to_int16(raw: bytes, typecode: str) -> tuple[array.array | None, dict[str, int]]:
    """Return (int16 array, anomaly counts); array is None when the file must be dropped."""
    values = array.array(typecode)
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    try:
        ints = array.array("h", map(int, values))
    except (OverflowError, ValueError):
        return None, classify_values(values, typecode)
    if array.array(typecode, ints).tobytes() == values.tobytes():
        return ints, {"non_finite": 0, "non_integral": 0, "out_of_int16": 0, "negative_zero": 0}
    counts = classify_values(values, typecode)
    if counts["non_finite"] or counts["non_integral"] or counts["out_of_int16"]:
        return None, counts
    return ints, counts  # only negative zeros differ bitwise; values are exact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    args = parser.parse_args()
    data_root = Path(args.data_dir) if Path(args.data_dir).is_absolute() else args.repo_root / args.data_dir
    data_root = data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    output_dir = samples_root / SERIES_ID
    temp_dir = samples_root / f".{SERIES_ID}.tmp"
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not (download_dir / "download_validation.json").is_file():
        raise SystemExit("missing validated downloads; run download.sh first")

    sources = load_sources(args.recipe_dir / "sources.tsv")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    index_rows: list[dict[str, object]] = []
    dropped: list[dict[str, object]] = []
    seen_hashes: dict[str, str] = {}
    aggregate = hashlib.sha256()
    negative_zero_total = 0
    global_min = 32767
    global_max = -32768
    chunk_shapes: collections.Counter = collections.Counter()
    filter_pipelines: collections.Counter = collections.Counter()
    try:
        for number, src in enumerate(sources, 1):
            path = download_dir / src["path"]
            buf = path.read_bytes()
            if len(buf) != int(src["size_bytes"]) or blob_sha1(buf) != src["git_blob_sha1"]:
                raise SystemExit(f"source identity mismatch: {src['path']}")
            decoded = cnc_h5.decode_file(buf)
            ds = decoded.dataset
            if decoded.root_links != ["vibration_data"]:
                raise SystemExit(f"{src['path']}: unexpected root links {decoded.root_links}")
            rows, cols = int(src["rows"]), int(src["cols"])
            if ds.shape != (rows, cols) or cols != 3:
                raise SystemExit(f"{src['path']}: shape {ds.shape} != pinned ({rows}, {cols})")
            if ds.typecode != DTYPE_TYPECODES[src["container_dtype"]]:
                raise SystemExit(f"{src['path']}: container dtype {ds.typecode} != pinned {src['container_dtype']}")
            chunk_shapes["column_chunks" if ds.chunk_shape and ds.chunk_shape[1] == 1 else "other_chunks"] += 1
            filter_pipelines["+".join(cnc_h5.SUPPORTED_FILTERS[f[0]] for f in ds.filters)] += 1

            ints, anomalies = to_int16(decoded.raw, ds.typecode)
            base = {"source_path": src["path"], "container_dtype": src["container_dtype"], **anomalies}
            if ints is None:
                reasons = [k for k in ("non_finite", "non_integral", "out_of_int16") if anomalies[k]]
                dropped.append({**base, "reason": "+".join(reasons)})
                print(f"drop {src['path']}: {reasons} {anomalies}")
                continue
            axes = [ints[i::3] for i in range(3)]
            axis_ranges = [(min(a), max(a)) for a in axes]
            if any(lo == hi for lo, hi in axis_ranges):
                dropped.append({**base, "reason": "constant_axis", "axis_ranges": axis_ranges})
                print(f"drop {src['path']}: constant axis {axis_ranges}")
                continue
            payload = ints.tobytes() if sys.byteorder == "little" else _swapped(ints)
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_hashes:
                dropped.append({**base, "reason": "duplicate_output", "duplicate_of": seen_hashes[digest]})
                print(f"drop {src['path']}: duplicate of {seen_hashes[digest]}")
                continue
            seen_hashes[digest] = src["path"]
            negative_zero_total += anomalies["negative_zero"]
            rel = Path(src["machine"]) / src["operation"] / src["label"] / (Path(src["path"]).stem + ".bin")
            target = temp_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            aggregate.update(payload)
            lo = min(a[0] for a in axis_ranges)
            hi = max(a[1] for a in axis_ranges)
            global_min = min(global_min, lo)
            global_max = max(global_max, hi)
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": (output_dir / rel).relative_to(data_root).as_posix(),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(payload),
                "value_count": len(ints),
                "sample_format": SAMPLE_FORMAT,
                "sample_geometry": SAMPLE_GEOMETRY,
                "sample_rank": 2,
                "sample_shape": [rows, 3],
                "sample_axes": SAMPLE_AXES,
                "natural_record_kind": NATURAL_RECORD_KIND,
                "source_format": SOURCE_FORMAT,
                "source_field": SOURCE_FIELD,
                "source_path": src["path"],
                "source_size_bytes": int(src["size_bytes"]),
                "source_git_blob_sha1": src["git_blob_sha1"],
                "source_container_dtype": src["container_dtype"],
                "source_chunk_shape": list(ds.chunk_shape or ()),
                "machine": src["machine"],
                "operation": src["operation"],
                "label": src["label"],
                "timeframe": src["timeframe"],
                "run_index": src["run_index"],
                "minimum": lo,
                "maximum": hi,
                "axis_minimum": [a[0] for a in axis_ranges],
                "axis_maximum": [a[1] for a in axis_ranges],
                "distinct_values": len(set(ints)),
                "negative_zero_values": anomalies["negative_zero"],
                "sha256": digest,
            })
            if number % 100 == 0:
                print(f"progress {number}/{len(sources)} kept={len(index_rows)} dropped={len(dropped)}", flush=True)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temp_dir.replace(output_dir)
    except BaseException:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise

    if len(index_rows) < 100:
        raise SystemExit(f"too few kept samples: {len(index_rows)}")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_index = index_path.with_suffix(".jsonl.tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in index_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.replace(index_path)

    counts = sorted(int(r["value_count"]) for r in index_rows)

    def tally(key: str) -> dict[str, int]:
        return dict(sorted(collections.Counter(str(r[key]) for r in index_rows).items()))

    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_files": len(sources),
        "source_bytes": EXPECTED_SOURCE_BYTES,
        "kept_samples": len(index_rows),
        "dropped_files": len(dropped),
        "dropped": dropped,
        "dropped_by_reason": dict(collections.Counter(str(d["reason"]) for d in dropped)),
        "total_values": sum(counts),
        "total_size_bytes": 2 * sum(counts),
        "min_sample_values": counts[0],
        "median_sample_values": statistics.median(counts),
        "max_sample_values": counts[-1],
        "minimum": global_min,
        "maximum": global_max,
        "negative_zero_values": negative_zero_total,
        "kept_by_machine": tally("machine"),
        "kept_by_timeframe": tally("timeframe"),
        "kept_by_label": tally("label"),
        "kept_by_operation": tally("operation"),
        "kept_by_container_dtype": tally("source_container_dtype"),
        "chunk_layouts": dict(chunk_shapes),
        "filter_pipelines": dict(filter_pipelines),
        "aggregate_sha256": aggregate.hexdigest(),
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "dropped"}, indent=2, sort_keys=True))
    return 0


def _swapped(ints: array.array) -> bytes:
    copy = array.array("h", ints)
    copy.byteswap()
    return copy.tobytes()


if __name__ == "__main__":
    raise SystemExit(main())
