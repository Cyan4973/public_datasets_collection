#!/usr/bin/env python3
"""Validate and build OpenNeuro ds004584 resting-state EEG float32 samples.

Subcommands:
  check-download  semantic validation of downloaded sidecars and .fdt matrices
  build           emit one little-endian float32 sample per selected recording
  selftest        exercise the float32 finiteness scanner on synthetic input

EEGLAB stores EEG.data as a MATLAB [nbchan x pnts] single matrix written in
column-major order, so the headerless .fdt holds little-endian IEEE float32
values with the channel index varying fastest: value(t, c) sits at element
t * nbchan + c. nbchan is taken from the BIDS *_channels.tsv rows and
cross-checked against *_eeg.json EEGChannelCount and the .fdt byte size.
Pure standard library; no .set (MATLAB) parsing is needed or performed.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import os
import statistics
import struct
import sys
from pathlib import Path

DATASET_ID = "openneuro_ds004584_pd_rest_eeg_f32"
SERIES_ID = "ds004584_rest_eeg_63ch_f32"
SAMPLING_HZ = 500
EXPECTED_SELECTION = 30
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
SIDE_FIELDS = {
    "SamplingFrequency": 500,
    "EEGReference": "Pz",
    "EEGGround": "AFz",
    "TaskName": "Rest",
    "RecordingType": "continuous",
    "ManufacturersModelName": "Brain Vision",
}

if sys.byteorder != "little":
    raise SystemExit("this builder assumes a little-endian host for array('f')")


def load_selection(recipe_dir: Path) -> list[dict]:
    with (recipe_dir / "selection.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        for key in ("fdt_bytes", "channels_bytes", "eeg_json_bytes", "time_points"):
            row[key] = int(row[key])
    subjects = [row["subject"] for row in rows]
    if len(rows) != EXPECTED_SELECTION or len(set(subjects)) != len(subjects) or subjects != sorted(subjects):
        raise SystemExit(f"selection.tsv must list {EXPECTED_SELECTION} unique sorted subjects")
    return rows


def load_canonical(recipe_dir: Path) -> list[str]:
    names = (recipe_dir / "canonical_channels.txt").read_text(encoding="utf-8").split()
    if len(names) != 63 or len(set(names)) != 63:
        raise SystemExit("canonical_channels.txt must list 63 unique channel names")
    return names


def paths_for(download_dir: Path, subject: str) -> dict[str, Path]:
    base = download_dir / subject
    return {
        "fdt": base / f"{subject}_task-Rest_eeg.fdt",
        "channels": base / f"{subject}_task-Rest_channels.tsv",
        "eeg_json": base / f"{subject}_task-Rest_eeg.json",
    }


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while block := handle.read(8 << 20):
            digest.update(block)
    return digest.hexdigest()


def nonfinite_positions(data: bytes, limit: int = 8) -> list[int]:
    """Element indices whose float32 exponent field is all ones (NaN or +/-Inf).

    In little-endian float32 the high byte holds the sign and the top seven
    exponent bits, and bit 7 of the next byte holds the lowest exponent bit.
    Only elements whose high byte is 0x7f or 0xff can be non-finite, so scan
    those candidates and test the remaining exponent bit.
    """
    if len(data) % 4:
        raise ValueError("float32 buffer length is not a multiple of 4")
    high = data[3::4]
    found: list[int] = []
    for marker in (0x7F, 0xFF):
        start = high.find(marker)
        while start != -1:
            if data[4 * start + 2] & 0x80:
                found.append(start)
                if len(found) >= limit:
                    return sorted(found)
            start = high.find(marker, start + 1)
    return sorted(found)


def validate_sidecars(paths: dict[str, Path], row: dict, canonical: list[str]) -> dict:
    subject = row["subject"]
    with paths["channels"].open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or reader.fieldnames[0] != "name":
            raise SystemExit(f"{subject}: channels.tsv lacks a leading 'name' column")
        names = [entry["name"] for entry in reader]
    if names != canonical:
        raise SystemExit(f"{subject}: channels.tsv does not match the pinned 63-channel montage")
    meta = json.loads(paths["eeg_json"].read_text(encoding="utf-8"))
    nbchan = len(names)
    if meta.get("EEGChannelCount") != nbchan:
        raise SystemExit(f"{subject}: EEGChannelCount {meta.get('EEGChannelCount')!r} != channels.tsv rows {nbchan}")
    for key, expected in SIDE_FIELDS.items():
        if meta.get(key) != expected:
            raise SystemExit(f"{subject}: eeg.json {key}={meta.get(key)!r}, expected {expected!r}")
    for key in ("EOGChannelCount", "ECGChannelCount", "EMGChannelCount"):
        if meta.get(key) != 0:
            raise SystemExit(f"{subject}: eeg.json {key}={meta.get(key)!r}, expected 0")
    size = paths["fdt"].stat().st_size
    if size != row["fdt_bytes"] or size % (4 * nbchan):
        raise SystemExit(f"{subject}: fdt size {size} is not the pinned size or not divisible by 4*{nbchan}")
    points = size // (4 * nbchan)
    if points != row["time_points"]:
        raise SystemExit(f"{subject}: fdt holds {points} time points, selection pins {row['time_points']}")
    duration = float(meta.get("RecordingDuration", -1))
    if abs(duration * SAMPLING_HZ - points) > 1.0:
        raise SystemExit(f"{subject}: RecordingDuration {duration} s disagrees with {points} points at {SAMPLING_HZ} Hz")
    return {"nbchan": nbchan, "points": points, "duration_s": duration}


def command_check_download(args: argparse.Namespace) -> None:
    recipe_dir = Path(args.recipe_dir)
    download_dir = Path(args.download_dir)
    rows = load_selection(recipe_dir)
    canonical = load_canonical(recipe_dir)
    total = 0
    for row in rows:
        paths = paths_for(download_dir, row["subject"])
        geometry = validate_sidecars(paths, row, canonical)
        data = paths["fdt"].read_bytes()
        bad = nonfinite_positions(data)
        if bad:
            raise SystemExit(f"{row['subject']}: non-finite float32 at element(s) {bad}")
        if data == data[:4] * (len(data) // 4):
            raise SystemExit(f"{row['subject']}: constant signal matrix")
        total += len(data)
        print(f"check_ok {row['subject']} nbchan={geometry['nbchan']} points={geometry['points']} bytes={len(data)}")
    print(f"check_download=ok recordings={len(rows)} fdt_bytes={total}")


def channel_stats(values: array.array, nbchan: int) -> tuple[list[dict], int]:
    stats = []
    flat = 0
    for channel in range(nbchan):
        column = values[channel::nbchan]
        low, high = min(column), max(column)
        if low == high:
            flat += 1
        stats.append({"min": low, "max": high})
    return stats, flat


def command_build(args: argparse.Namespace) -> None:
    recipe_dir = Path(args.recipe_dir)
    data_dir = Path(args.data_dir)
    download_dir = data_dir / "downloads" / DATASET_ID
    sample_dir = data_dir / "samples" / DATASET_ID / SERIES_ID
    index_path = data_dir / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_dir / "filtered" / DATASET_ID / "ingest_stats.json"
    rows = load_selection(recipe_dir)
    canonical = load_canonical(recipe_dir)

    sample_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{row['subject']}_task-Rest_eeg_63ch_f32le.bin" for row in rows}
    for stale in sample_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()

    index_rows = []
    per_recording = []
    for row in rows:
        subject = row["subject"]
        paths = paths_for(download_dir, subject)
        for kind, size_key, md5_key in (
            ("channels", "channels_bytes", "channels_md5"),
            ("eeg_json", "eeg_json_bytes", "eeg_json_md5"),
            ("fdt", "fdt_bytes", "fdt_md5"),
        ):
            if not paths[kind].is_file():
                raise SystemExit(f"{subject}: missing local {kind} file {paths[kind]}; run download.sh")
            if paths[kind].stat().st_size != row[size_key] or md5_file(paths[kind]) != row[md5_key]:
                raise SystemExit(f"{subject}: {kind} size/MD5 does not match selection.tsv")
        geometry = validate_sidecars(paths, row, canonical)
        nbchan, points = geometry["nbchan"], geometry["points"]
        data = paths["fdt"].read_bytes()
        bad = nonfinite_positions(data)
        if bad:
            raise SystemExit(f"{subject}: non-finite float32 at element(s) {bad}")
        if data == data[:4] * (len(data) // 4):
            raise SystemExit(f"{subject}: constant signal matrix")
        values = array.array("f")
        values.frombytes(data)
        if len(values) != nbchan * points:
            raise SystemExit(f"{subject}: decoded {len(values)} values, expected {nbchan * points}")
        low, high = min(values), max(values)
        per_channel, flat = channel_stats(values, nbchan)
        if flat == nbchan:
            raise SystemExit(f"{subject}: every channel is flat")
        head = values[: min(len(values), 200_000)]
        distinct_ratio = len(set(head)) / len(head)

        name = f"{subject}_task-Rest_eeg_63ch_f32le.bin"
        target = sample_dir / name
        temp = target.with_suffix(".bin.part")
        temp.write_bytes(data)
        os.replace(temp, target)
        sha256 = hashlib.sha256(data).hexdigest()
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(target.relative_to(data_dir)),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(data),
                "value_count": len(values),
                "subject": subject,
                "source_key": f"ds004584/{subject}/eeg/{subject}_task-Rest_eeg.fdt",
                "source_md5": row["fdt_md5"],
                "sha256": sha256,
                "shape": [points, nbchan],
                "layout": "time-major, channel index fastest (EEGLAB [nbchan x pnts] column-major)",
                "channel_count": nbchan,
                "time_points": points,
                "sampling_frequency_hz": SAMPLING_HZ,
                "duration_s": points / SAMPLING_HZ,
                "unit": "microvolt (EEGLAB convention; channels.tsv units n/a)",
                "min": low,
                "max": high,
                "flat_channels": flat,
            }
        )
        per_recording.append(
            {
                "subject": subject,
                "values": len(values),
                "min": low,
                "max": high,
                "flat_channels": flat,
                "distinct_ratio_first_200k": round(distinct_ratio, 6),
                "channel_ranges": per_channel,
            }
        )
        print(
            f"sample {subject} points={points} values={len(values)} min={low:.3f} max={high:.3f} "
            f"flat_channels={flat} distinct_ratio={distinct_ratio:.4f}"
        )

    total_values = sum(r["value_count"] for r in index_rows)
    total_bytes = sum(r["sample_size_bytes"] for r in index_rows)
    median_values = statistics.median(r["value_count"] for r in index_rows)
    if total_values < MIN_VALUES or median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"below floor: values={total_values} median={median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes {total_bytes} exceed cap {MAX_PRIMARY_BYTES}")

    temp_index = index_path.with_suffix(".jsonl.part")
    with temp_index.open("w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    os.replace(temp_index, index_path)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "total_values": total_values,
        "total_bytes": total_bytes,
        "median_values": median_values,
        "channel_names": canonical,
        "recordings": per_recording,
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(f"build_summary samples={len(index_rows)} values={total_values} bytes={total_bytes} median_values={median_values}")


def command_selftest(_: argparse.Namespace) -> None:
    specials = [0.0, -0.0, 1.5, -200.25, 3.0e38, -3.0e38, 1e-45, float("nan"), float("inf"), float("-inf"), 12.0]
    data = struct.pack("<" + "f" * len(specials), *specials)
    found = nonfinite_positions(data)
    expected = [i for i, v in enumerate(specials) if not math.isfinite(v)]
    if found != expected:
        raise SystemExit(f"selftest failed: found {found}, expected {expected}")
    clean = struct.pack("<4f", 3.4e38, -3.4e38, 1.0, -1.0)
    if nonfinite_positions(clean):
        raise SystemExit("selftest failed: finite extremes flagged")
    # quiet NaN with payload and a signalling NaN pattern
    raw = bytes.fromhex("0100c07f" "010080ff" "0000803f")
    if nonfinite_positions(raw) != [0, 1]:
        raise SystemExit("selftest failed: NaN payload patterns")
    # layout check: element t*nbchan + c is (time t, channel c)
    nbchan, points = 3, 4
    matrix = [[float(10 * c + t) for t in range(points)] for c in range(nbchan)]
    flat = array.array("f", [matrix[c][t] for t in range(points) for c in range(nbchan)])
    if list(flat[1::nbchan]) != matrix[1]:
        raise SystemExit("selftest failed: channel slice")
    print("selftest=ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-download")
    check.add_argument("--recipe-dir", required=True)
    check.add_argument("--download-dir", required=True)
    check.set_defaults(func=command_check_download)
    build = sub.add_parser("build")
    build.add_argument("--recipe-dir", required=True)
    build.add_argument("--data-dir", required=True)
    build.set_defaults(func=command_build)
    selftest = sub.add_parser("selftest")
    selftest.set_defaults(func=command_selftest)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
