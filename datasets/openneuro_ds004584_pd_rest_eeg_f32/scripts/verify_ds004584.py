#!/usr/bin/env python3
"""Independently verify the ds004584 resting-state EEG float32 output.

Re-derives every sample from the local downloads without importing the
builder: re-hashes the pinned .fdt/.tsv/.json objects, re-reads channel
counts from channels.tsv and eeg.json, recomputes the geometry, checks that
each emitted sample is byte-identical to its source matrix, re-checks
finiteness with a different method than the builder (a float64 sum, which
propagates any NaN or Inf), recomputes stored-float32 min/max and flat-channel
counts, and reconciles the sample index and manifest totals.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import statistics
import sys
import tomllib
from pathlib import Path

DATASET_ID = "openneuro_ds004584_pd_rest_eeg_f32"
SERIES_ID = "ds004584_rest_eeg_63ch_f32"
REQUIRED_INDEX_KEYS = (
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
)


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def digest(path: Path, name: str) -> str:
    h = hashlib.new(name)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    recipe_dir = Path(args.recipe_dir)
    data_dir = Path(args.data_dir)
    download_dir = data_dir / "downloads" / DATASET_ID
    sample_dir = data_dir / "samples" / DATASET_ID / SERIES_ID
    index_path = data_dir / "index" / DATASET_ID / "samples.jsonl"
    if sys.byteorder != "little":
        fail("verification assumes a little-endian host")

    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    primaries = [s for s in manifest.get("series", []) if s.get("role") == "primary"]
    if len(primaries) != 1 or primaries[0].get("id") != SERIES_ID:
        fail("manifest must declare exactly one primary series with the expected id")
    series = primaries[0]
    if (series.get("numeric_kind"), series.get("bit_width"), series.get("endianness")) != ("float", 32, "little"):
        fail("manifest series must be little-endian float32")

    canonical = [line.strip() for line in (recipe_dir / "canonical_channels.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    with (recipe_dir / "selection.tsv").open(encoding="utf-8", newline="") as handle:
        selection = list(csv.DictReader(handle, delimiter="\t"))
    if len(selection) != 30:
        fail(f"selection lists {len(selection)} recordings, expected 30")

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_subject = {}
    for row in index_rows:
        missing = [key for key in REQUIRED_INDEX_KEYS if key not in row]
        if missing:
            fail(f"index row missing {missing}")
        if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
            fail(f"index row has unexpected ids: {row['dataset_id']}/{row['series_id']}")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            fail(f"index row dtype mismatch for {row.get('subject')}")
        if row["subject"] in by_subject:
            fail(f"duplicate subject {row['subject']} in index")
        by_subject[row["subject"]] = row
    if sorted(by_subject) != sorted(r["subject"] for r in selection):
        fail("index subjects differ from selection.tsv")

    # Safety: the recipe never stores demographic tables or EEGLAB .set metadata.
    forbidden = [p for p in download_dir.rglob("*") if p.name == "participants.tsv" or p.suffix == ".set"]
    if forbidden:
        fail(f"forbidden metadata present under downloads: {forbidden[:3]}")

    emitted = sorted(p.name for p in sample_dir.iterdir() if p.is_file())
    expected_files = sorted(Path(r["sample_path"]).name for r in index_rows)
    if emitted != expected_files:
        fail("sample directory contents differ from the index")

    total_values = 0
    total_bytes = 0
    for sel in selection:
        subject = sel["subject"]
        row = by_subject[subject]
        base = download_dir / subject
        fdt = base / f"{subject}_task-Rest_eeg.fdt"
        channels = base / f"{subject}_task-Rest_channels.tsv"
        sidecar = base / f"{subject}_task-Rest_eeg.json"
        for path, size_key, md5_key in ((fdt, "fdt_bytes", "fdt_md5"), (channels, "channels_bytes", "channels_md5"), (sidecar, "eeg_json_bytes", "eeg_json_md5")):
            if path.stat().st_size != int(sel[size_key]) or digest(path, "md5") != sel[md5_key]:
                fail(f"{subject}: {path.name} differs from pinned size/MD5")

        lines = channels.read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        name_col = header.index("name")
        names = [line.split("\t")[name_col] for line in lines[1:] if line.strip()]
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        nbchan = len(names)
        if names != canonical or nbchan != 63 or meta.get("EEGChannelCount") != nbchan:
            fail(f"{subject}: channel list/count disagrees (rows={nbchan}, json={meta.get('EEGChannelCount')})")
        if meta.get("SamplingFrequency") != 500 or meta.get("EEGReference") != "Pz":
            fail(f"{subject}: sidecar sampling/reference changed")
        size = fdt.stat().st_size
        if size % (4 * nbchan):
            fail(f"{subject}: fdt size {size} not divisible by 4*{nbchan}")
        points = size // (4 * nbchan)
        if points != int(sel["time_points"]) or abs(float(meta["RecordingDuration"]) * 500 - points) > 1.0:
            fail(f"{subject}: geometry mismatch points={points}")

        sample = data_dir / row["sample_path"]
        if not sample.is_file():
            fail(f"{subject}: missing sample {row['sample_path']}")
        raw = sample.read_bytes()
        if len(raw) != size or raw != fdt.read_bytes():
            fail(f"{subject}: sample is not byte-identical to the source float32 matrix")
        if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
            fail(f"{subject}: index sha256 mismatch")
        values = array.array("f")
        values.frombytes(raw)
        if len(values) != nbchan * points or row["value_count"] != len(values) or row["sample_size_bytes"] != len(raw):
            fail(f"{subject}: value/byte counts disagree with index")
        if row.get("shape") != [points, nbchan] or row.get("channel_count") != nbchan or row.get("time_points") != points:
            fail(f"{subject}: index geometry disagrees")
        if not math.isfinite(sum(values)):
            fail(f"{subject}: NaN or Inf present")
        low, high = min(values), max(values)
        if low == high:
            fail(f"{subject}: constant recording")
        if row.get("min") != low or row.get("max") != high:
            fail(f"{subject}: index min/max {row.get('min')}/{row.get('max')} != stored {low}/{high}")
        flat = 0
        for channel in range(nbchan):
            column = values[channel::nbchan]
            if min(column) == max(column):
                flat += 1
        if flat != row.get("flat_channels") or flat == nbchan:
            fail(f"{subject}: flat channel count {flat} disagrees with index {row.get('flat_channels')}")
        total_values += len(values)
        total_bytes += len(raw)
        print(f"verified {subject} points={points} min={low:.3f} max={high:.3f} flat_channels={flat}")

    median_values = statistics.median(r["value_count"] for r in index_rows)
    if series.get("sample_count") != len(index_rows) or series.get("total_size_bytes") != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} != realized {len(index_rows)}/{total_bytes}")
    if total_values < 10_000 or median_values < 1_000:
        fail(f"below floor values={total_values} median={median_values}")
    if total_bytes > 1_000_000_000:
        fail(f"primary bytes {total_bytes} exceed 1 GB cap")
    print(f"verify_summary samples={len(index_rows)} values={total_values} bytes={total_bytes} median_values={median_values}")


if __name__ == "__main__":
    main()
