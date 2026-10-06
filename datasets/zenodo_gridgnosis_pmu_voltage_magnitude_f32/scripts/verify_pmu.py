#!/usr/bin/env python3
"""Independent verification of the Cyprus PMU voltage-magnitude samples.

Re-derives every sample from the local archives with a separate code path
(csv.reader, strptime-based integer-microsecond lattice check, struct packing,
exact-Decimal half-unit re-print test), re-applies the same missing-value and
exclusion policy as build_pmu.py, and byte-compares the result against the
emitted sample files, the sample index, and the manifest totals.
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
import statistics
import struct
import sys
import tomllib
import zipfile
from decimal import Decimal
from pathlib import Path

DATASET_ID = "zenodo_gridgnosis_pmu_voltage_magnitude_f32"
SERIES_ID = "cyprus_pmu_phase_voltage_magnitude_f32"
ARCHIVE_FILES = {
    "gridgnosis_20308780": "gridgnosis_20308780_steady_state_data.zip",
    "grideye_17648863": "grideye_17648863_steady_state_data.zip",
}
FRAME_US = 20_000
MAX_UNMEASURED_FRACTION = 0.5
NOMINAL_MEAN_RANGE = (55_000.0, 95_000.0)
VOLTAGE_RE = re.compile(r"Mag_V[ABC]_\d+_\d+")
CHANNEL_PMU_RE = re.compile(r"Mag_V[ABC]_(\d+)_\d+")
TOKEN_CHARS = set("0123456789.-eE+")
INDEX_KEYS = [
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
]
EPOCH = dt.datetime(1970, 1, 1)


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def micros(stamp: str) -> int:
    parsed = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f")
    delta = parsed - EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def token_matches_float32(token: str, value: float) -> bool:
    """True when rounding float32 `value` to 8 significant digits (exact
    decimal ties away from zero) gives the decimal number `token`."""
    if not token or not set(token) <= TOKEN_CHARS:
        return False
    printed = Decimal(token)
    if not printed.is_finite():
        return False
    exact = Decimal(value)
    if exact == 0:
        return printed == 0
    if printed == 0 or printed.normalize().as_tuple().exponent < exact.adjusted() - 7:
        return False  # token carries digits finer than the 8th significant digit
    half = Decimal(5).scaleb(exact.adjusted() - 8)
    return printed - half <= exact < printed + half


def owner_pmu(name: str) -> int:
    match = CHANNEL_PMU_RE.fullmatch(name)
    if not match:
        fail(f"unexpected voltage channel name {name!r}")
    return int(match.group(1))


def columns_sha256(payload: bytes, width: int) -> list[str]:
    values = array.array("f")
    values.frombytes(payload)
    return [hashlib.sha256(values[k::width].tobytes()).hexdigest() for k in range(width)]


def rederive(zf: zipfile.ZipFile, member: str, pmu: int) -> dict:
    with zf.open(member) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="ascii", newline=""))
        header = next(reader)
        if header[0] != "Date_Time" or header[-2:] != ["Frequency", "Dfrequency"]:
            fail(f"{member}: header ends {header[:1]} {header[-2:]}")
        groups = sum(1 for name in header if name.startswith("Mag_IA_"))
        if len(header) != 3 + 12 * groups:
            fail(f"{member}: {len(header)} columns for {groups} phasor groups")
        vidx = [i for i, name in enumerate(header) if VOLTAGE_RE.fullmatch(name)]
        if len(vidx) != 3 * groups:
            fail(f"{member}: {len(vidx)} voltage-magnitude columns for {groups} groups")
        names = [header[i] for i in vidx]
        nch = len(vidx)
        # terminal group of each voltage channel, resolved by header-name suffix
        group_columns = []
        for name in names:
            suffix = name[len("Mag_VA"):]
            columns = [i for i, other in enumerate(header) if other.endswith(suffix) and other.count("_") == 3]
            if len(columns) != 12:
                fail(f"{member}: terminal {suffix} has {len(columns)} phasor columns, expected 12")
            group_columns.append(columns)
        pack = struct.Struct(f"<{nch}f")
        own = [c for c in range(nch) if owner_pmu(names[c]) == pmu]
        foreign = [c for c in range(nch) if owner_pmu(names[c]) != pmu]
        if not own:
            fail(f"{member}: no voltage channel carries PMU id {pmu}")
        own_pack = struct.Struct(f"<{len(own)}f")
        foreign_pack = struct.Struct(f"<{len(foreign)}f")
        is_own = [owner_pmu(name) == pmu for name in names]
        chunks: list[bytes] = []
        foreign_chunks: list[bytes] = []
        channel_values: list[list[float]] = [[] for _ in range(nch)]
        dropout = 0
        zero_values = 0
        frames = 0
        previous = None
        gaps: list[dict] = []
        first_stamp = last_stamp = ""
        for row in reader:
            if len(row) != len(header):
                fail(f"{member}: frame {frames} has {len(row)} fields")
            stamp = micros(row[0])
            if previous is None:
                first_stamp = row[0]
            else:
                step = stamp - previous
                if step <= 0 or step % FRAME_US:
                    fail(f"{member}: frame {frames} timestamp {row[0]} is not a forward 20 ms-multiple step")
                if step > FRAME_US:
                    gaps.append({"after_frame": frames - 1, "resume_timestamp": row[0], "absent_frames": step // FRAME_US - 1})
            previous = stamp
            last_stamp = row[0]
            tokens = [row[i] for i in vidx]
            try:
                packed = pack.pack(*[float(token) for token in tokens])
            except (ValueError, OverflowError):
                fail(f"{member}: frame {frames} has an unparseable voltage token in {tokens}")
            values = pack.unpack(packed)
            for token, value in zip(tokens, values):
                if not (math.isfinite(value) and value >= 0.0):
                    fail(f"{member}: frame {frames} invalid voltage {token!r}")
                if not token_matches_float32(token, value):
                    fail(f"{member}: frame {frames} token {token!r} does not re-print from float32 {value!r}")
            is_dropout = False
            if not any(values):
                is_dropout = all(Decimal(field) == 0 for field in row[1:])
            if is_dropout:
                dropout += 1
            else:
                for channel, value in enumerate(values):
                    if value == 0.0:
                        if any(Decimal(row[i]) != 0 for i in group_columns[channel]):
                            fail(f"{member}: frame {frames} zero {names[channel]} outside a zero-filled terminal group")
                        if is_own[channel]:
                            zero_values += 1
                    channel_values[channel].append(value)
            chunks.append(own_pack.pack(*[values[c] for c in own]))
            if foreign:
                foreign_chunks.append(foreign_pack.pack(*[values[c] for c in foreign]))
            frames += 1
    payload = b"".join(chunks)
    foreign_payload = b"".join(foreign_chunks)
    return {
        "payload": payload,
        "names": [names[c] for c in own],
        "own_sha256": columns_sha256(payload, len(own)),
        "foreign_names": [names[c] for c in foreign],
        "foreign_sha256": columns_sha256(foreign_payload, len(foreign)) if foreign else [],
        "frames": frames,
        "channels": len(own),
        "dropout": dropout,
        "gaps": gaps,
        "absent": sum(gap["absent_frames"] for gap in gaps),
        "zero_values": zero_values,
        "first": first_stamp,
        "last": last_stamp,
        "channel_values": [channel_values[c] for c in own],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--members", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    samples_dir = data_root / "samples" / DATASET_ID / SERIES_ID

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series with the expected id")
    series = series[0]
    if (series.get("numeric_kind"), series.get("bit_width"), series.get("endianness")) != ("float", 32, "little"):
        fail("manifest series must be little-endian float32")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_member: dict[str, dict] = {}
    for row in rows:
        missing = [key for key in INDEX_KEYS if key not in row]
        if missing:
            fail(f"index row missing {missing}")
        if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
            fail(f"index row has wrong ids: {row['dataset_id']}/{row['series_id']}")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            fail(f"index row {row['sample_path']} has wrong numeric type fields")
        if row["source_member"] in by_member:
            fail(f"duplicate index rows for {row['source_member']}")
        by_member[row["source_member"]] = row

    with args.members.open(newline="", encoding="utf-8") as handle:
        members = list(csv.DictReader(handle, delimiter="\t"))
    archives: dict[str, zipfile.ZipFile] = {}
    matched = set()
    excluded = []
    owner_columns: dict[tuple, tuple] = {}
    foreign_copies: list[tuple] = []
    for member in members:
        key = member["archive"]
        if key not in archives:
            archives[key] = zipfile.ZipFile(args.downloads / ARCHIVE_FILES[key])
        info = archives[key].getinfo(member["member"])
        if f"{info.CRC:08x}" != member["crc32"]:
            fail(f"{member['member']}: CRC32 differs from members.tsv")
        got = rederive(archives[key], member["member"], int(member["pmu"]))
        frames = got["frames"]
        if frames < 2:
            fail(f"{member['member']}: only {frames} frames")
        identity = (frames, got["first"], got["last"])
        for name, digest in zip(got["names"], got["own_sha256"]):
            owner_columns[(key, member["window"], name)] = identity + (digest,)
        for name, digest in zip(got["foreign_names"], got["foreign_sha256"]):
            foreign_copies.append((member["member"], (key, member["window"], name), identity + (digest,)))
        lattice = frames + got["absent"]
        if got["dropout"] + got["absent"] > MAX_UNMEASURED_FRACTION * lattice:
            excluded.append(member["member"])
            if member["member"] in by_member:
                fail(f"{member['member']}: mostly unmeasured but a sample was emitted")
            print(
                f"excluded_ok member={member['member']} dropout_frames={got['dropout']} "
                f"absent_frames={got['absent']} lattice_frames={lattice}",
                flush=True,
            )
            continue
        row = by_member.get(member["member"])
        if row is None:
            fail(f"{member['member']}: eligible member has no sample")
        matched.add(member["member"])
        for name, column in zip(got["names"], got["channel_values"]):
            mean = math.fsum(column) / len(column)
            if not (NOMINAL_MEAN_RANGE[0] <= mean <= NOMINAL_MEAN_RANGE[1]):
                fail(f"{member['member']}: channel {name} mean {mean:.1f} V outside the 132 kV phase-to-ground band")
            if max(column) == min(column):
                fail(f"{member['member']}: channel {name} constant over measured frames")
        payload = got["payload"]
        sample_path = data_root / row["sample_path"]
        if sample_path.parent != samples_dir:
            fail(f"{row['sample_path']} is outside the series output directory")
        stored = sample_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if hashlib.sha256(stored).hexdigest() != digest or row.get("sample_sha256") != digest:
            fail(f"{row['sample_path']}: bytes differ from the independent re-derivation")
        expected_fields = {
            "value_count": frames * got["channels"],
            "sample_size_bytes": len(payload),
            "frame_count": frames,
            "channel_count": got["channels"],
            "channel_names": got["names"],
            "sample_shape": [frames, got["channels"]],
            "dropout_frame_count": got["dropout"],
            "absent_frame_count": got["absent"],
            "lattice_frame_count": lattice,
            "gaps": got["gaps"],
            "terminal_zero_fill_voltage_values": got["zero_values"],
            "first_timestamp": got["first"],
            "last_timestamp": got["last"],
            "pmu": int(member["pmu"]),
            "window": member["window"],
            "excluded_foreign_channels": got["foreign_names"],
        }
        for field, value in expected_fields.items():
            if row.get(field) != value:
                fail(f"{row['sample_path']}: index {field}={row.get(field)!r} != re-derived {value!r}")
        values = array.array("f")
        values.frombytes(stored)
        if sys.byteorder != "little":
            values.byteswap()
        if not all(math.isfinite(v) for v in values):
            fail(f"{row['sample_path']}: non-finite stored value")
        if (min(values), max(values)) != (row.get("min"), row.get("max")):
            fail(f"{row['sample_path']}: index min/max {row.get('min')}/{row.get('max')} != stored {min(values)}/{max(values)}")
        if min(values) == max(values):
            fail(f"{row['sample_path']}: constant sample")
        foreign_named = [name for name in row["channel_names"] if owner_pmu(name) != row["pmu"]]
        if foreign_named:
            fail(f"{row['sample_path']}: emitted channels {foreign_named} carry another PMU's id")
        print(
            f"sample_ok {sample_path.name} frames={frames} channels={got['channels']} "
            f"dropout_frames={got['dropout']} absent_frames={got['absent']} gaps={len(got['gaps'])} sha256={digest[:16]}",
            flush=True,
        )
    for zf in archives.values():
        zf.close()

    # Every dropped foreign channel must be an exact copy of its owner's column.
    for member_name, owner_key, copy in foreign_copies:
        owner = owner_columns.get(owner_key)
        if owner is None or owner != copy:
            fail(f"{member_name}: dropped foreign channel {owner_key[2]} is not an exact copy of its owner's column")
        print(f"foreign_duplicate_ok {member_name.split('/')[-1]} {owner_key[2]} sha256={copy[3][:16]}", flush=True)

    # No channel column may appear twice anywhere in the emitted output.
    seen_columns: dict[str, str] = {}
    for row in rows:
        stored = (data_root / row["sample_path"]).read_bytes()
        for name, digest in zip(row["channel_names"], columns_sha256(stored, row["channel_count"])):
            label = f"{Path(row['sample_path']).name}:{name}"
            if digest in seen_columns:
                fail(f"duplicate emitted channel column: {label} == {seen_columns[digest]}")
            seen_columns[digest] = label
    print(f"column_uniqueness_ok columns={len(seen_columns)}", flush=True)

    if set(by_member) != matched:
        fail(f"index rows without an eligible member: {sorted(set(by_member) - matched)}")
    on_disk = {p.name for p in samples_dir.glob("*")}
    indexed = {Path(r["sample_path"]).name for r in rows}
    if on_disk != indexed:
        fail(f"sample directory and index disagree: extra={sorted(on_disk - indexed)} missing={sorted(indexed - on_disk)}")
    total_values = sum(r["value_count"] for r in rows)
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} "
            f"!= realized {len(rows)}/{total_bytes}"
        )
    median = statistics.median(r["value_count"] for r in rows)
    if not ((total_values >= 10_000 or total_bytes >= 100_000) and median >= 1_000):
        fail(f"primary floor not met: values={total_values} bytes={total_bytes} median={median}")
    if total_bytes > 1_000_000_000:
        fail(f"primary bytes {total_bytes} exceed the 1 GB cap")
    print(
        f"verify_summary samples={len(rows)} excluded={len(excluded)} values={total_values} "
        f"bytes={total_bytes} median_values={median}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
