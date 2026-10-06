#!/usr/bin/env python3
"""Build per-file float32 voltage-magnitude matrices from Cyprus PMU CSVs.

One sample per pinned one-hour steady-state CSV member: a frame-major
`frames x channels` little-endian float32 matrix holding that file's
`Mag_V{A,B,C}_<pmu>_<line>` columns in header order (one row per 20 ms
frame, exactly as the CSV rows are laid out). Angles, currents, Frequency and
Dfrequency are read only for validation and dropout detection; they are not
emitted.

Foreign phasor groups: a CSV may carry a group whose `<pmu>` id differs from
the file's own PMU (GridGnosis PMU_6 carries `_4_6`). Such groups are parsed
and validated but not emitted; the build fails closed unless each such voltage
column is byte-identical (float32 column SHA-256, same frames) to the owner
PMU's same-named column in the same window. Dropped names are recorded per
index row (`excluded_foreign_channels`).

Missing-value policy (re-derived independently by verify_pmu.py):
- Zero-filled dropout frames: rows whose every numeric field (all magnitudes,
  angles, Frequency, Dfrequency) is exactly 0. They are kept in place with
  their 0.0 voltage values (the source's own sentinel) and counted per sample.
- Zero-filled terminals: inside an otherwise measured frame, one line
  terminal's whole 12-field phasor group (V/I magnitudes and angles) is
  exactly 0. Its three 0.0 voltage values are kept and counted per sample. A
  zero voltage outside a zero-filled frame or terminal group is fatal.
- Absent frames: rows missing from the export (a timestamp step that is a
  whole multiple of 20 ms larger than 20 ms). They are not padded or
  interpolated; each gap is recorded in the index (after which emitted frame,
  how many frames are absent).
- A file whose dropout plus absent frames exceed half of its 20 ms lattice
  (first to last timestamp) is excluded (no sample): that hour was mostly not
  measured.
- Blank, non-numeric, non-finite or negative voltage tokens, ragged rows,
  timestamps that repeat, go backwards or leave the 20 ms grid, malformed
  headers, or tokens that do not re-print identically from their nearest
  float32 are fatal.
"""
from __future__ import annotations

import argparse
import array
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import sys
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

DATASET_ID = "zenodo_gridgnosis_pmu_voltage_magnitude_f32"
SERIES_ID = "cyprus_pmu_phase_voltage_magnitude_f32"
ARCHIVE_FILES = {
    "gridgnosis_20308780": "gridgnosis_20308780_steady_state_data.zip",
    "grideye_17648863": "grideye_17648863_steady_state_data.zip",
}
RECORD_IDS = {"gridgnosis_20308780": 20308780, "grideye_17648863": 17648863}
GROUP = [
    "Mag_VA", "Angle_VA", "Mag_VB", "Angle_VB", "Mag_VC", "Angle_VC",
    "Mag_IA", "Angle_IA", "Mag_IB", "Angle_IB", "Mag_IC", "Angle_IC",
]
VOLTAGE_OFFSETS = (0, 2, 4)
FRAME_STEP = dt.timedelta(milliseconds=20)
MAX_UNMEASURED_FRACTION = 0.5
# 132 kV line-to-line / sqrt(3) = 76.2 kV phase-to-ground; anything whose
# measured mean leaves this band would be a different nominal level.
NOMINAL_MEAN_RANGE = (55_000.0, 95_000.0)
TOKEN_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")


class BuildError(RuntimeError):
    pass


def reprints(token: str, value: float) -> tuple[bool, bool]:
    """Does `token` re-print from float32 `value`? Returns (ok, used_fallback).

    The source prints 8 significant digits, rounding exact decimal ties half
    away from zero, stripping trailing zeros and keeping '.0' on integers.
    """
    fast = format(value, ".8g")
    if fast == (token[:-2] if token.endswith(".0") else token):
        # Python rounds exact ties half-to-even; send those to the exact path.
        digits = format(value, ".12g").split("e")[0].replace("-", "").replace(".", "").lstrip("0")
        if not (len(digits) == 9 and digits.endswith("5")):
            return True, False
    exact = Decimal(value)
    if exact == 0:
        return Decimal(token) == 0, True
    rounded = exact.quantize(Decimal(1).scaleb(exact.adjusted() - 7), rounding=ROUND_HALF_UP)
    return rounded == Decimal(token), True


def parse_header(line: str) -> tuple[int, list[int], list[str]]:
    columns = line.split(",")
    if columns[0] != "Date_Time" or columns[-2:] != ["Frequency", "Dfrequency"]:
        raise BuildError(f"unexpected header ends: {columns[:2]} ... {columns[-2:]}")
    body = columns[1:-2]
    if not body or len(body) % len(GROUP):
        raise BuildError(f"header body has {len(body)} columns, not a multiple of {len(GROUP)}")
    indices: list[int] = []
    names: list[str] = []
    for group in range(len(body) // len(GROUP)):
        chunk = body[group * len(GROUP) : (group + 1) * len(GROUP)]
        match = re.fullmatch(r"Mag_VA_(\d+_\d+)", chunk[0])
        if not match:
            raise BuildError(f"group {group} does not start with Mag_VA_<pmu>_<line>: {chunk[0]!r}")
        suffix = match.group(1)
        if chunk != [f"{prefix}_{suffix}" for prefix in GROUP]:
            raise BuildError(f"group {group} columns out of the phasor pattern: {chunk}")
        for offset in VOLTAGE_OFFSETS:
            indices.append(1 + group * len(GROUP) + offset)
            names.append(chunk[offset])
    if len(set(names)) != len(names):
        raise BuildError("duplicate voltage channel names")
    return len(columns), indices, names


def channel_pmu(name: str) -> int:
    """PMU id of a `Mag_V<phase>_<pmu>_<line>` channel name."""
    return int(name.split("_")[2])


def load_members(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sample_name(member: dict) -> str:
    project = member["archive"].split("_")[0]
    return f"{project}_pmu{member['pmu']}_{member['window']}.bin"


def process_member(zf: zipfile.ZipFile, member: dict) -> dict:
    info = zf.getinfo(member["member"])
    if f"{info.CRC:08x}" != member["crc32"] or info.file_size != int(member["uncompressed_size"]):
        raise BuildError("member metadata differs from members.tsv")
    with zf.open(info) as raw:  # zipfile verifies CRC32 when the stream reaches EOF
        text = io.TextIOWrapper(raw, encoding="ascii", newline="")
        header = text.readline()
        if not header.endswith("\r\n"):
            raise BuildError("header line is not CRLF-terminated")
        ncols, vidx, names = parse_header(header[:-2])
        nch = len(vidx)
        own = [c for c, name in enumerate(names) if channel_pmu(name) == int(member["pmu"])]
        own_set = set(own)
        if not own:
            raise BuildError(f"no voltage channel carries the file's own PMU id {member['pmu']}")
        out = array.array("f")
        dropout_frames: list[int] = []
        zero_values = 0
        fallback = 0
        frames = 0
        first_ts = last_ts = None
        previous = None
        gaps: list[dict] = []
        for line in text:
            if not line.endswith("\r\n"):
                raise BuildError(f"frame {frames}: unterminated (truncated) line")
            fields = line[:-2].split(",")
            if len(fields) != ncols:
                raise BuildError(f"frame {frames}: {len(fields)} fields, header has {ncols}")
            ts = dt.datetime.fromisoformat(fields[0])
            if previous is None:
                first_ts = fields[0]
            else:
                step = ts - previous
                if step <= dt.timedelta(0) or step % FRAME_STEP:
                    raise BuildError(f"frame {frames}: timestamp {fields[0]} is not a forward 20 ms-multiple step from {previous}")
                if step != FRAME_STEP:
                    gaps.append(
                        {
                            "after_frame": frames - 1,
                            "resume_timestamp": fields[0],
                            "absent_frames": step // FRAME_STEP - 1,
                        }
                    )
            previous = ts
            last_ts = fields[0]
            tokens = [fields[i] for i in vidx]
            for token in tokens:
                if not TOKEN_RE.fullmatch(token):
                    raise BuildError(f"frame {frames}: non-numeric voltage token {token!r}")
            values = array.array("f", [float(token) for token in tokens])
            for token, value in zip(tokens, values):
                if not math.isfinite(value) or value < 0.0:
                    raise BuildError(f"frame {frames}: invalid voltage magnitude {token!r}")
                ok, used = reprints(token, value)
                if not ok:
                    raise BuildError(f"frame {frames}: token {token!r} does not re-print from float32 {value!r}")
                fallback += used
            if max(values) == 0.0 and all(float(field) == 0.0 for field in fields[1:]):
                dropout_frames.append(frames)
            elif 0.0 in values:
                for channel, value in enumerate(values):
                    if value != 0.0:
                        continue
                    start = 1 + (channel // len(VOLTAGE_OFFSETS)) * len(GROUP)
                    if any(float(fields[j]) != 0.0 for j in range(start, start + len(GROUP))):
                        raise BuildError(f"frame {frames}: zero {names[channel]} outside a zero-filled terminal group")
                    zero_values += channel in own_set
            out.extend(values)
            frames += 1
    if frames < 2:
        raise BuildError(f"only {frames} frames")
    dropouts = len(dropout_frames)
    measured = frames - dropouts
    absent = sum(gap["absent_frames"] for gap in gaps)
    lattice_frames = frames + absent
    column_sha256 = {names[c]: hashlib.sha256(out[c::nch].tobytes()).hexdigest() for c in range(nch)}
    channel_stats = []
    dropout_set = set(dropout_frames)
    for channel in own:
        column = out[channel::nch]
        if dropouts:
            column = array.array("f", (v for k, v in enumerate(column) if k not in dropout_set))
        if not column:
            channel_stats.append({"name": names[channel], "measured_frames": 0})
            continue
        channel_stats.append(
            {
                "name": names[channel],
                "measured_frames": len(column),
                "min": min(column),
                "max": max(column),
                "mean": math.fsum(column) / len(column),
            }
        )
    excluded = dropouts + absent > MAX_UNMEASURED_FRACTION * lattice_frames
    if not excluded:
        for stats in channel_stats:
            if not (NOMINAL_MEAN_RANGE[0] <= stats["mean"] <= NOMINAL_MEAN_RANGE[1]):
                raise BuildError(f"channel {stats['name']} mean {stats['mean']:.1f} V is outside the 132 kV phase-to-ground band")
            if stats["max"] <= stats["min"]:
                raise BuildError(f"channel {stats['name']} is constant over measured frames")
    emitted = array.array("f", bytes(4 * frames * len(own)))
    for k, channel in enumerate(own):
        emitted[k :: len(own)] = out[channel::nch]
    return {
        "out": emitted,
        "names": [names[c] for c in own],
        "foreign_names": [names[c] for c in range(nch) if c not in own_set],
        "column_sha256": column_sha256,
        "frames": frames,
        "channels": len(own),
        "dropout_frames": dropouts,
        "absent_frames": absent,
        "lattice_frames": lattice_frames,
        "gaps": gaps,
        "unmeasured_fraction": (dropouts + absent) / lattice_frames,
        "measured_frames": measured,
        "terminal_zero_fill_voltage_values": zero_values,
        "reprint_tie_fallbacks": fallback,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "excluded": excluded,
        "channel_stats": channel_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if sys.byteorder != "little":
        raise SystemExit("this builder writes array('f') buffers and expects a little-endian host")
    data_root = args.data_root.resolve()
    samples_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    samples_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*.bin"):
        stale.unlink()

    members = load_members(args.members)
    owner_columns: dict[tuple, dict] = {}  # (archive, window, channel) -> owner column identity
    foreign_checks: list[tuple] = []
    rows: list[dict] = []
    per_member: list[dict] = []
    archives: dict[str, zipfile.ZipFile] = {}
    try:
        for member in members:
            key = member["archive"]
            if key not in archives:
                archives[key] = zipfile.ZipFile(args.downloads / ARCHIVE_FILES[key])
            try:
                result = process_member(archives[key], member)
            except (BuildError, ValueError, zipfile.BadZipFile) as exc:
                raise SystemExit(f"FATAL {member['member']}: {exc}") from None
            out = result.pop("out")
            identity = {
                "frames": result["frames"],
                "first": result["first_timestamp"],
                "last": result["last_timestamp"],
                "sample": sample_name(member),
            }
            for name in result["names"]:
                owner_columns[(key, member["window"], name)] = {**identity, "sha256": result["column_sha256"][name]}
            for name in result["foreign_names"]:
                foreign_checks.append(
                    (member["member"], (key, member["window"], name), {**identity, "sha256": result["column_sha256"][name]})
                )
            record = {
                "archive": key,
                "member": member["member"],
                "pmu": int(member["pmu"]),
                "window": member["window"],
                **{k: v for k, v in result.items() if k not in ("names", "column_sha256")},
                "channel_names": result["names"],
            }
            if result["excluded"]:
                record["exclusion_reason"] = (
                    f"{result['dropout_frames']} zero-filled + {result['absent_frames']} absent of "
                    f"{result['lattice_frames']} lattice frames unmeasured (> {MAX_UNMEASURED_FRACTION:.0%})"
                )
                per_member.append(record)
                print(f"excluded member={member['member']} reason={record['exclusion_reason']}", flush=True)
                continue
            payload = out.tobytes()
            name = sample_name(member)
            path = samples_dir / name
            path.write_bytes(payload)
            row = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(path.relative_to(data_root)),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": len(out),
                "sample_shape": [result["frames"], result["channels"]],
                "sample_axes": ["frame_20ms", "voltage_magnitude_channel"],
                "layout": "row-major frame-by-channel (CSV row order)",
                "frame_count": result["frames"],
                "channel_count": result["channels"],
                "channel_names": result["names"],
                "unit": "volt (phase-to-ground RMS phasor magnitude)",
                "frame_interval_ms": 20,
                "first_timestamp": result["first_timestamp"],
                "last_timestamp": result["last_timestamp"],
                "dropout_frame_count": result["dropout_frames"],
                "absent_frame_count": result["absent_frames"],
                "lattice_frame_count": result["lattice_frames"],
                "gaps": result["gaps"],
                "terminal_zero_fill_voltage_values": result["terminal_zero_fill_voltage_values"],
                "excluded_foreign_channels": result["foreign_names"],
                "excluded_foreign_channels_reason": (
                    "phasor group labelled with another PMU's id; each column is a byte-identical copy "
                    "(float32 column SHA-256, same frames) of the owner PMU's same-named column in this window"
                    if result["foreign_names"]
                    else ""
                ),
                "min": min(out),
                "max": max(out),
                "sample_sha256": hashlib.sha256(payload).hexdigest(),
                "pmu": int(member["pmu"]),
                "window": member["window"],
                "source_record": RECORD_IDS[key],
                "source_archive": ARCHIVE_FILES[key],
                "source_member": member["member"],
                "source_member_crc32": member["crc32"],
            }
            rows.append(row)
            record["sample_path"] = row["sample_path"]
            per_member.append(record)
            print(
                f"sample {name} frames={result['frames']} channels={result['channels']} "
                f"foreign_dropped={len(result['foreign_names'])} "
                f"dropout_frames={result['dropout_frames']} absent_frames={result['absent_frames']} "
                f"ties={result['reprint_tie_fallbacks']} "
                f"min={row['min']} max={row['max']}",
                flush=True,
            )
    finally:
        for zf in archives.values():
            zf.close()

    # Fail closed: a dropped foreign channel must duplicate its owner's column exactly.
    for member_name, owner_key, copy in foreign_checks:
        owner = owner_columns.get(owner_key)
        if owner is None:
            raise SystemExit(f"FATAL {member_name}: foreign channel {owner_key[2]} has no owner column in window {owner_key[1]}")
        if any(owner[field] != copy[field] for field in ("frames", "first", "last", "sha256")):
            raise SystemExit(
                f"FATAL {member_name}: foreign channel {owner_key[2]} differs from owner {owner['sample']}; "
                "refusing to drop possibly distinct data"
            )
        print(f"foreign_duplicate_ok {copy['sample']} {owner_key[2]} == {owner['sample']} sha256={owner['sha256'][:16]}")

    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    values = sum(r["value_count"] for r in rows)
    size = sum(r["sample_size_bytes"] for r in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "members_read": len(per_member),
        "samples": len(rows),
        "excluded_members": [m["member"] for m in per_member if m["excluded"]],
        "primary_values": values,
        "primary_bytes": size,
        "max_unmeasured_fraction": MAX_UNMEASURED_FRACTION,
        "nominal_mean_range_v": list(NOMINAL_MEAN_RANGE),
        "members": per_member,
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build_summary samples={len(rows)} excluded={len(stats['excluded_members'])} values={values} bytes={size}")
    if not rows:
        raise SystemExit("no samples built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
