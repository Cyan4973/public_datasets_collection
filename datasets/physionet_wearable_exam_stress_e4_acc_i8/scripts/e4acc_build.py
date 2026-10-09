#!/usr/bin/env python3
"""Build physionet_wearable_exam_stress_e4_acc_i8 samples from local files.

One sample per exam session: the whole ACC.csv of that session with its two
header rows (start time, sample rate) removed, emitted as interleaved
x,y,z signed int8 in source row order. Values are the E4's native 1/64 g
counts, written unchanged. Any malformed row is fatal; nothing is trimmed.
"""
from __future__ import annotations

import argparse
import array
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the recipe directory free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e4acc_pins as pins  # noqa: E402
import e4acc_synth as synth  # noqa: E402

ROW = rb"-?[0-9]{1,3},-?[0-9]{1,3},-?[0-9]{1,3}"
BODY_RE = re.compile(ROW + rb"(?:\n" + ROW + rb")*")
START_RE = re.compile(rb"[0-9]+\.[0-9]+")
MIN_FRAMES = 30 * 60 * pins.SAMPLE_RATE_HZ  # 30 minutes
MIN_DISTINCT_PER_AXIS = 16
MAX_MOST_COMMON_FRACTION = 0.9


class ParseError(ValueError):
    pass


def parse_acc(data: bytes) -> tuple[str, bytes]:
    """Return (start_time_text, interleaved int8 bytes) or raise ParseError."""
    if b"\r" in data:
        raise ParseError("carriage return in file")
    first = data.find(b"\n")
    second = data.find(b"\n", first + 1) if first >= 0 else -1
    if first < 0 or second < 0:
        raise ParseError("fewer than two header rows")
    start = [field.strip() for field in data[:first].split(b",")]
    rate = [field.strip() for field in data[first + 1:second].split(b",")]
    if len(start) != 3 or len(set(start)) != 1 or not START_RE.fullmatch(start[0]):
        raise ParseError(f"bad start-time row {data[:first]!r}")
    if len(rate) != 3:
        raise ParseError(f"bad rate row {data[first + 1:second]!r}")
    try:
        rates = [float(value) for value in rate]
    except ValueError as exc:
        raise ParseError(f"bad rate row {data[first + 1:second]!r}") from exc
    if any(value != float(pins.SAMPLE_RATE_HZ) for value in rates):
        raise ParseError(f"rate row {rates} != {pins.SAMPLE_RATE_HZ} Hz")
    body = data[second + 1:]
    if body.endswith(b"\n"):
        body = body[:-1]
    if not body or not BODY_RE.fullmatch(body):
        bad_line = next((i for i, line in enumerate(body.split(b"\n")) if not re.fullmatch(ROW, line)), None)
        raise ParseError(f"malformed data row at body line {bad_line}")
    values = list(map(int, body.replace(b"\n", b",").split(b",")))
    if len(values) % pins.AXES:
        raise ParseError("value count not a multiple of 3")
    low, high = min(values), max(values)
    if low < pins.VALUE_MIN or high > pins.VALUE_MAX:
        raise ParseError(f"value range {low}..{high} outside int8")
    return start[0].decode("ascii"), array.array("b", values).tobytes()


def describe(raw: bytes) -> dict:
    """Per-sample descriptive statistics, computed from the stored int8 bytes."""
    signed = array.array("b", raw)
    frames = len(signed) // pins.AXES
    axes = {}
    for axis, name in enumerate("xyz"):
        column = signed[axis::pins.AXES]
        axes[name] = {"min": min(column), "max": max(column), "distinct": len(set(column))}
    counts = collections.Counter(signed)
    most_common_value, most_common_count = counts.most_common(1)[0]
    static = sum(1 for i in range(pins.AXES, len(raw), pins.AXES) if raw[i:i + 3] == raw[i - 3:i])
    rails = counts.get(pins.VALUE_MIN, 0) + counts.get(pins.VALUE_MAX, 0)
    return {
        "frame_count": frames,
        "axis_stats": axes,
        "most_common_value": most_common_value,
        "most_common_value_fraction": round(most_common_count / len(signed), 6),
        "static_frame_fraction": round(static / max(1, frames - 1), 6),
        "rail_value_count": rails,
    }


def degenerate_reason(stats: dict) -> str | None:
    if stats["frame_count"] < MIN_FRAMES:
        return f"only {stats['frame_count']} frames (< {MIN_FRAMES})"
    for name, axis in stats["axis_stats"].items():
        if axis["distinct"] < MIN_DISTINCT_PER_AXIS:
            return f"axis {name} has {axis['distinct']} distinct values"
    if stats["most_common_value_fraction"] > MAX_MOST_COMMON_FRACTION:
        return f"most common value fraction {stats['most_common_value_fraction']}"
    return None


def self_test() -> None:
    for trailing in (True, False):
        data, expected, start = synth.good(trailing_newline=trailing)
        got_start, got = parse_acc(data)
        assert got == expected and got_start == start, "synthetic good input mis-decoded"
    for label, data in synth.bad():
        try:
            parse_acc(data)
        except ParseError:
            continue
        raise AssertionError(f"synthetic bad input accepted: {label}")
    print("self-test ok: build parser")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()

    self_test()
    inventory = json.loads((args.download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    by_session = {row["session_id"]: row for row in inventory["acc_files"]}

    series_dir = args.samples_root / pins.SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*.bin"):
        stale.unlink()
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for subject, exam, release_path, size, sha in pins.ACC_FILES:
        session = pins.session_id(subject, exam)
        source = args.download_dir / "acc" / pins.local_name(subject, exam)
        data = source.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha or by_session[session]["sha256"] != sha:
            raise SystemExit(f"{session}: source size/hash mismatch; rerun download.sh")
        try:
            start, raw = parse_acc(data)
        except ParseError as exc:
            raise SystemExit(f"{session}: {exc}")
        stats = describe(raw)
        reason = degenerate_reason(stats)
        if reason:
            raise SystemExit(f"{session}: degenerate sample: {reason}")
        out = series_dir / f"{session}.bin"
        out.write_bytes(raw)
        row = {
            "dataset_id": pins.DATASET_ID,
            "series_id": pins.SERIES_ID,
            "sample_path": out.relative_to(args.data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(raw),
            "value_count": len(raw),
            "session_id": session,
            "subject": f"S{subject}",
            "exam": exam,
            "source_path": release_path,
            "source_sha256": sha,
            "start_unix_time_date_shifted": start,
            "sample_rate_hz": pins.SAMPLE_RATE_HZ,
            "layout": "interleaved_xyz_frames",
            "duration_s": round(stats["frame_count"] / pins.SAMPLE_RATE_HZ, 3),
            "unit": "1/64 g",
            "sample_sha256": hashlib.sha256(raw).hexdigest(),
            **stats,
        }
        rows.append(row)
        print(f"{session}: frames={stats['frame_count']} values={len(raw)} "
              f"static={stats['static_frame_fraction']} top={stats['most_common_value_fraction']}")

    with args.index.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    sizes = sorted(row["value_count"] for row in rows)
    middle = len(sizes) // 2
    median = sizes[middle] if len(sizes) % 2 else (sizes[middle - 1] + sizes[middle]) / 2
    aggregate = hashlib.sha256()
    for row in rows:
        aggregate.update(row["sample_sha256"].encode("ascii"))
    summary = {
        "dataset_id": pins.DATASET_ID,
        "series_id": pins.SERIES_ID,
        "sample_count": len(rows),
        "total_values": sum(sizes),
        "total_bytes": sum(sizes),
        "total_frames": sum(row["frame_count"] for row in rows),
        "median_sample_values": median,
        "min_sample_values": sizes[0],
        "max_sample_values": sizes[-1],
        "total_duration_h": round(sum(row["duration_s"] for row in rows) / 3600, 3),
        "rail_value_count": sum(row["rail_value_count"] for row in rows),
        "aggregate_sample_sha256": aggregate.hexdigest(),
    }
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
