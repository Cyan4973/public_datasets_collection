#!/usr/bin/env python3
"""Build or verify DANDI:001076 Suite2p ROI fluorescence (F) float32 samples.

One sample per pinned NWB asset: the complete
``/processing/ophys/Fluorescence/RoiResponseSeries/data`` matrix
(frames x ROIs, row-major, little-endian IEEE float32), with HDF5 edge-chunk
padding removed and nothing else changed.
"""

from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import mmap
import re
import statistics
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402

DATASET_ID = "dandi_001076_zebrafish_calcium_fluorescence_f32"
SERIES_ID = "suite2p_roi_fluorescence_f32"
DATA_PATH = "processing/ophys/Fluorescence/RoiResponseSeries/data"
EXPECTED_SAMPLES = 48
EXPECTED_SESSIONS = 12
EXPECTED_VALUES = 62_819_025
EXPECTED_BYTES = EXPECTED_VALUES * 4
# SHA-256 over all 48 decoded samples concatenated in asset-path order, pinned
# from the first successful build of the pinned sources (2026-10-05).
EXPECTED_AGGREGATE_SHA256 = "7b3e1782536df105533b7c7f25f53a0e98fc2e28f11dd2bd22f83d3f7e18e950"
PATH_RE = re.compile(r"^sub-nan/sub-nan_(ses-(\d{8})T(\d{6}))_(obj-[0-9a-z]+)_ophys\.nwb$")


def load_assets(recipe_dir: Path) -> list[dict[str, str]]:
    with (recipe_dir / "assets.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    rows.sort(key=lambda row: row["asset_path"])
    if len(rows) != EXPECTED_SAMPLES or len({row["asset_path"] for row in rows}) != EXPECTED_SAMPLES:
        raise ValueError(f"assets.tsv must pin {EXPECTED_SAMPLES} distinct assets, has {len(rows)}")
    if sum(int(row["frames"]) * int(row["rois"]) for row in rows) != EXPECTED_VALUES:
        raise ValueError("assets.tsv frame x ROI totals disagree with EXPECTED_VALUES")
    return rows


def local_source(data_root: Path, asset: dict[str, str]) -> Path:
    return data_root / "downloads" / DATASET_ID / "nwb" / Path(asset["asset_path"]).name


def sample_name(asset: dict[str, str]) -> tuple[str, str, str]:
    match = PATH_RE.match(asset["asset_path"])
    if not match:
        raise ValueError(f"unexpected asset path {asset['asset_path']}")
    session, day, clock, obj = match.groups()
    start = asset["session_start_time"]
    if start[:19].replace("-", "").replace(":", "") != f"{day}T{clock}":
        raise ValueError(f"session token {session} disagrees with session_start_time {start}")
    return f"{session}_{obj}.bin", session, obj


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def decode_asset(data_root: Path, asset: dict[str, str]) -> tuple[bytes, dict[str, object]]:
    """Validate one pinned NWB source and return (logical F bytes, metadata)."""
    path = local_source(data_root, asset)
    size = int(asset["size_bytes"])
    require(path.is_file() and path.stat().st_size == size, f"missing or wrong-sized source {path}")
    digest = file_sha256(path)
    require(digest == asset["sha256"], f"dandi:sha2-256 mismatch for {path.name}: {digest}")
    frames, rois = int(asset["frames"]), int(asset["rois"])
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        h5 = H.H5File(raw, size)
        root = h5.attributes(h5.messages(h5.root_header))
        require(root.get("neurodata_type") == "NWBFile" and root.get("nwb_version") == "2.6.0",
                f"unexpected NWB root attributes {root}")
        require(h5.scalar_string(h5.resolve("identifier")) == asset["nwb_identifier"], "NWB identifier changed")
        require(h5.scalar_string(h5.resolve("session_start_time")) == asset["session_start_time"],
                "NWB session_start_time changed")
        require(h5.scalar_string(h5.resolve("general/subject/species")) == "Danio rerio", "species changed")
        require(h5.scalar_string(h5.resolve("general/subject/description")) == "H2B-gcamp6s",
                "subject description (indicator line) changed")
        fluo = h5.attributes(h5.messages(h5.resolve("processing/ophys/Fluorescence")))
        require(fluo.get("neurodata_type") == "Fluorescence", f"unexpected Fluorescence attrs {fluo}")
        rrs = h5.attributes(h5.messages(h5.resolve("processing/ophys/Fluorescence/RoiResponseSeries")))
        require(rrs.get("neurodata_type") == "RoiResponseSeries"
                and rrs.get("description") == "Array of raw fluorescence traces.",
                f"unexpected RoiResponseSeries attrs {rrs}")
        info = h5.dataset(h5.resolve(DATA_PATH))
        attrs = info["attributes"]
        require(attrs.get("unit") == "n.a." and attrs.get("conversion") == 1.0
                and attrs.get("offset") == 0.0 and attrs.get("resolution") == -1.0,
                f"unexpected data unit/conversion/offset/resolution {attrs}")
        require(tuple(info["shape"]) == (frames, rois), f"shape {info['shape']} != pinned {(frames, rois)}")
        rois_info = h5.dataset(h5.resolve("processing/ophys/Fluorescence/RoiResponseSeries/rois"))
        require(tuple(rois_info["shape"]) == (rois,), "rois region length differs from ROI axis")
        masks = h5.dataset(h5.resolve("processing/ophys/ImageSegmentation/PlaneSegmentation/image_mask"))
        require(tuple(masks["shape"])[0] == rois, "PlaneSegmentation ROI count differs from ROI axis")
        starting = h5.dataset(h5.resolve("processing/ophys/Fluorescence/RoiResponseSeries/starting_time"))
        rate = starting["attributes"].get("rate")
        require(isinstance(rate, float) and 0.5 < rate < 2.0 and starting["attributes"].get("unit") == "seconds",
                f"unexpected imaging rate attributes {starting['attributes']}")
        data, chunks = H.read_f32_deflate_2d(h5, info)
        require(len(chunks) == int(asset["chunk_count"]), f"chunk count {len(chunks)} != pinned")
        require(len(data) == frames * rois * 4, "decoded byte length != frames*ROIs*4")
        deflate_level = H.validate_f32_deflate_2d(info)[2]
    meta = {
        "frames": frames,
        "rois": rois,
        "imaging_rate_hz": rate,
        "source_chunk_count": len(chunks),
        "source_chunk_shape": list(info["chunk_shape"]),
        "source_deflate_level": deflate_level,
        "image_mask_shape": list(masks["shape"]),
    }
    return data, meta


def payload_stats(payload: bytes, rois: int) -> dict[str, object]:
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    total = math.fsum(values)
    # A float64 sum of <= 2.3M finite float32 values cannot overflow, so a
    # non-finite sum proves at least one NaN/Inf element.
    require(math.isfinite(total), "non-finite fluorescence value present (policy: fatal)")
    minimum, maximum = min(values), max(values)
    require(minimum < maximum, "constant fluorescence matrix")
    constant_rois = sum(1 for column in range(rois) if len(set(values[column::rois])) == 1)
    return {
        "min": minimum,
        "max": maximum,
        "mean": total / len(values),
        "distinct_values": len(set(values)),
        "zero_values": values.count(0.0),
        "negative_values": sum(1 for value in values if value < 0.0),
        "constant_roi_columns": constant_rois,
    }


def index_row(data_root: Path, sample_path: Path, asset: dict[str, str], session: str, obj: str,
              meta: dict[str, object], stats: dict[str, object], digest: str) -> dict[str, object]:
    frames, rois = int(meta["frames"]), int(meta["rois"])
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": frames * rois * 4,
        "value_count": frames * rois,
        "sample_shape": [frames, rois],
        "sample_axes": ["imaging_frame", "roi"],
        "sample_sha256": digest,
        "source_asset_path": asset["asset_path"],
        "source_asset_id": asset["asset_id"],
        "source_blob_url": asset["blob_url"],
        "source_sha256": asset["sha256"],
        "source_field": DATA_PATH,
        "session_id": session,
        "dandi_object_token": obj,
        "nwb_identifier": asset["nwb_identifier"],
        "session_start_time": asset["session_start_time"],
        **{key: meta[key] for key in ("imaging_rate_hz", "source_chunk_count", "source_chunk_shape",
                                      "source_deflate_level", "image_mask_shape")},
        **stats,
    }


def aggregate_stats(rows: list[dict[str, object]], aggregate: str) -> dict[str, object]:
    counts = [int(row["value_count"]) for row in rows]
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "session_count": len({row["session_id"] for row in rows}),
        "total_values": sum(counts),
        "total_size_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "median_sample_values": statistics.median(counts),
        "min_sample_values": min(counts),
        "max_sample_values": max(counts),
        "minimum": min(float(row["min"]) for row in rows),
        "maximum": max(float(row["max"]) for row in rows),
        "zero_values": sum(int(row["zero_values"]) for row in rows),
        "negative_values": sum(int(row["negative_values"]) for row in rows),
        "constant_roi_columns": sum(int(row["constant_roi_columns"]) for row in rows),
        "non_finite_values": 0,
        "aggregate_sample_sha256": aggregate,
    }


def check_population(rows: list[dict[str, object]]) -> None:
    require(len(rows) == EXPECTED_SAMPLES, f"sample count {len(rows)} != {EXPECTED_SAMPLES}")
    require(len({row["sample_sha256"] for row in rows}) == len(rows), "duplicate decoded samples")
    require(len({row["nwb_identifier"] for row in rows}) == len(rows), "duplicate NWB identifiers")
    require(len({row["session_id"] for row in rows}) == EXPECTED_SESSIONS, "unexpected session count")
    total_values = sum(int(row["value_count"]) for row in rows)
    require(total_values == EXPECTED_VALUES, f"total values {total_values} != {EXPECTED_VALUES}")
    require(EXPECTED_BYTES <= 1_000_000_000, "primary output exceeds the 1 GB cap")
    require(statistics.median(int(row["value_count"]) for row in rows) >= 1_000, "median below floor")


def build(args: argparse.Namespace) -> None:
    data_root, recipe_dir = args.data_root.resolve(), args.recipe_dir.resolve()
    assets = load_assets(recipe_dir)
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*"):
        stale.unlink()
    rows = []
    aggregate = hashlib.sha256()
    for number, asset in enumerate(assets, 1):
        name, session, obj = sample_name(asset)
        payload, meta = decode_asset(data_root, asset)
        stats = payload_stats(payload, int(meta["rois"]))
        digest = hashlib.sha256(payload).hexdigest()
        sample_path = out_dir / name
        tmp = sample_path.with_suffix(".part")
        tmp.write_bytes(payload)
        tmp.replace(sample_path)
        aggregate.update(payload)
        rows.append(index_row(data_root, sample_path, asset, session, obj, meta, stats, digest))
        print(f"built {number}/{len(assets)} {name} shape={meta['frames']}x{meta['rois']} "
              f"chunks={meta['source_chunk_count']} range={stats['min']}..{stats['max']} "
              f"distinct={stats['distinct_values']} constant_rois={stats['constant_roi_columns']}", flush=True)
    check_population(rows)
    tmp_index = index_path.with_suffix(".part")
    tmp_index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp_index.replace(index_path)
    summary = aggregate_stats(rows, aggregate.hexdigest())
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if EXPECTED_AGGREGATE_SHA256 and summary["aggregate_sample_sha256"] != EXPECTED_AGGREGATE_SHA256:
        raise ValueError(f"aggregate sample SHA-256 changed: {summary['aggregate_sample_sha256']}")
    print(json.dumps(summary, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    data_root, recipe_dir = args.data_root.resolve(), args.recipe_dir.resolve()
    assets = load_assets(recipe_dir)
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    require(out_dir.is_dir() and index_path.is_file() and stats_path.is_file(),
            "missing samples directory, index, or ingest statistics")
    indexed = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in indexed}
    require(len(by_path) == len(indexed) == EXPECTED_SAMPLES, f"index has {len(indexed)} rows")
    rows = []
    expected_files = set()
    aggregate = hashlib.sha256()
    for number, asset in enumerate(assets, 1):
        name, session, obj = sample_name(asset)
        sample_path = out_dir / name
        expected_files.add(sample_path)
        require(sample_path.is_file(), f"missing sample {sample_path}")
        written = sample_path.read_bytes()
        stats = payload_stats(written, int(asset["rois"]))
        fresh, meta = decode_asset(data_root, asset)
        require(written == fresh, f"sample differs from a fresh decode of the source: {name}")
        digest = hashlib.sha256(written).hexdigest()
        expected_row = index_row(data_root, sample_path, asset, session, obj, meta, stats, digest)
        actual_row = by_path.get(expected_row["sample_path"])
        require(actual_row == json.loads(json.dumps(expected_row)), f"index row mismatch for {name}")
        aggregate.update(written)
        rows.append(expected_row)
        if number % 8 == 0:
            print(f"verified {number}/{len(assets)}", flush=True)
    require(set(out_dir.iterdir()) == expected_files, "sample directory has unexpected or missing files")
    require([row["sample_path"] for row in indexed] == [row["sample_path"] for row in rows],
            "index order differs from pinned asset order")
    check_population(rows)
    summary = aggregate_stats(rows, aggregate.hexdigest())
    recorded = json.loads(stats_path.read_text(encoding="utf-8"))
    require(recorded == json.loads(json.dumps(summary)), "ingest_stats.json differs from recomputed statistics")
    if EXPECTED_AGGREGATE_SHA256:
        require(summary["aggregate_sample_sha256"] == EXPECTED_AGGREGATE_SHA256, "aggregate sample SHA-256 changed")
    else:
        print("note: EXPECTED_AGGREGATE_SHA256 not pinned yet", flush=True)
    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    require(manifest.get("dataset_id") == DATASET_ID, "manifest dataset_id mismatch")
    series = [entry for entry in manifest.get("series", []) if entry.get("id") == SERIES_ID]
    require(len(series) == 1, "manifest must declare the primary series once")
    require(series[0].get("sample_count") == summary["sample_count"]
            and series[0].get("total_size_bytes") == summary["total_size_bytes"],
            "manifest sample_count/total_size_bytes differ from realized output")
    print(f"verified samples={summary['sample_count']} sessions={summary['session_count']} "
          f"values={summary['total_values']} bytes={summary['total_size_bytes']} "
          f"range={summary['minimum']}..{summary['maximum']} median_values={summary['median_sample_values']} "
          f"aggregate_sha256={summary['aggregate_sample_sha256']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{DATASET_ID}: {exc}") from exc
