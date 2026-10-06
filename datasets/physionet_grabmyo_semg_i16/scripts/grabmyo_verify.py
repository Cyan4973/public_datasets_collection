#!/usr/bin/env python3
"""Independent verification of the GRABMyo surface-EMG int16 samples.

Shares no code with grabmyo_recipe.py. It re-derives the trial list from the
pinned SHA256SUMS.txt, re-parses every WFDB header with a whole-line regular
expression, rebuilds every expected sample by byte-slicing the kept 2-byte
cells out of each 64-byte source frame (no integer decoding), re-checks WFDB
checksums and initial values with struct, re-applies the exclusion rule, and
compares samples, index rows, stats, and manifest totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import struct
import tomllib
from pathlib import Path

DATASET_ID = "physionet_grabmyo_semg_i16"
SERIES_ID = "grabmyo_semg_trial_i16"
NSIG, FS, NSAMP = 32, 2048, 10240
FRAME_BYTES = NSIG * 2
# Project numbering: F1-F16 = columns 1-16, W1-W6 = 18-23, W7-W12 = 26-31
# (1-based); U1-U4 = columns 17, 24, 25, 32 are unused inputs.
KEPT_1BASED = list(range(1, 17)) + list(range(18, 24)) + list(range(26, 32))
KEPT = [column - 1 for column in KEPT_1BASED]
NAMES = {}
for column in range(1, 17):
    NAMES[column - 1] = f"F{column}"
for offset, column in enumerate(range(18, 24)):
    NAMES[column - 1] = f"W{offset + 1}"
for offset, column in enumerate(range(26, 32)):
    NAMES[column - 1] = f"W{offset + 7}"
for unused, column in zip(("U1", "U2", "U3", "U4"), (17, 24, 25, 32)):
    NAMES[column - 1] = unused
PARTICIPANTS, GESTURES = 43, 17
EXPECTED_TRIALS = PARTICIPANTS * GESTURES  # 731
EXPECTED_DAT_TOTAL = 479_068_160
EXPECTED_HEA_TOTAL = 2_273_949
SELECTION_SHA256 = "ad6d952e14967043c9927534e834cf62f9b63676f3c0930a80ebbed99a0423dc"
MIN_DISTINCT = 256
MAX_EXCLUDED_FRACTION = 0.01
GESTURE_17 = "Rest"

SIGNAL_LINE = re.compile(
    r"^(?P<file>\S+) 16 (?P<gain>[0-9.eE+-]+)\((?P<base>-?\d+)\)/mV 16 0 (?P<init>-?\d+) (?P<ck>-?\d+) 0 (?P<name>[FUW]\d+)$"
)


def read_sums(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="ascii").splitlines():
        digest, _, name = line.partition(" ")
        if name:
            out[name] = digest
    return out


def trial_list(sums: dict[str, str]) -> list[tuple[int, int, str]]:
    found = []
    for name, digest in sums.items():
        parts = name.split("/")
        if len(parts) != 3 or parts[0] != "Session1" or not parts[2].endswith(("_trial1.dat", "_trial1.hea")):
            continue
        stem, ext = parts[2].rsplit(".", 1)
        fields = stem.split("_")  # session1, participantP, gestureG, trial1
        if len(fields) != 4 or fields[0] != "session1" or fields[3] != "trial1" or parts[1] != f"session1_{fields[1]}":
            continue
        participant = int(fields[1].removeprefix("participant"))
        gesture = int(fields[2].removeprefix("gesture"))
        found.append(((participant, gesture, ext), f"{digest}  {name}\n"))
    found.sort()
    digest = hashlib.sha256("".join(line for _, line in found).encode("ascii")).hexdigest()
    assert digest == SELECTION_SHA256, "selected trial list differs from the pinned selection"
    pairs = sorted({(p, g) for (p, g, _), _ in found})
    assert pairs == [(p, g) for p in range(1, PARTICIPANTS + 1) for g in range(1, GESTURES + 1)], "trial grid is not complete"
    assert len(found) == 2 * EXPECTED_TRIALS
    return [(p, g, f"session1_participant{p}_gesture{g}_trial1") for p, g in pairs]


def read_header(text: str, stem: str, nsamp: int) -> list[dict]:
    rows = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert rows[0] == f"{stem} {NSIG} {FS} {nsamp}", f"{stem}: record line {rows[0]!r}"
    assert len(rows) == NSIG + 1, f"{stem}: {len(rows) - 1} signal lines"
    signals = []
    for column, line in enumerate(rows[1:]):
        match = SIGNAL_LINE.match(line)
        assert match, f"{stem}: signal line {column} not WFDB format 16 / 16-bit / mV: {line!r}"
        assert match["file"] == f"{stem}.dat" and match["name"] == NAMES[column], f"{stem}: signal {column} file/name"
        gain = float(match["gain"])
        assert gain > 0
        signals.append({"gain": gain, "base": int(match["base"]), "init": int(match["init"]), "ck": int(match["ck"])})
    return signals


def expected_sample(raw: bytes, nsamp: int) -> bytes:
    """Kept 2-byte cells of every frame, copied as bytes (source and output are both LE int16)."""
    assert len(raw) == nsamp * FRAME_BYTES
    out = bytearray(nsamp * len(KEPT) * 2)
    stride = len(KEPT) * 2
    for slot, column in enumerate(KEPT):
        out[2 * slot::stride] = raw[2 * column::FRAME_BYTES]
        out[2 * slot + 1::stride] = raw[2 * column + 1::FRAME_BYTES]
    return bytes(out)


def channel_checks(raw: bytes, signals: list[dict], stem: str, nsamp: int) -> tuple[str | None, list[tuple[int, int, int]]]:
    values = struct.unpack(f"<{nsamp * NSIG}h", raw)
    reason = None
    kept_stats = []
    for column in range(NSIG):
        series = values[column::NSIG]
        assert series[0] == signals[column]["init"], f"{stem}: signal {column} initial value"
        assert (sum(series) - signals[column]["ck"]) % 65536 == 0, f"{stem}: signal {column} checksum"
        if column in KEPT:
            distinct = len(set(series))
            kept_stats.append((min(series), max(series), distinct))
            if reason is None and -32768 in series:
                reason = f"channel {NAMES[column]} has {series.count(-32768)} WFDB invalid samples (-32768)"
            if reason is None and distinct < MIN_DISTINCT:
                reason = f"channel {NAMES[column]} has {distinct} < {MIN_DISTINCT} distinct codes"
    return reason, kept_stats


def selftest() -> None:
    rng = random.Random(77)
    nsamp = 512
    stem = "session1_participant3_gesture9_trial1"
    columns = [[rng.randint(-32767, 32767) for _ in range(nsamp)] for _ in range(NSIG)]
    raw = struct.pack(f"<{nsamp * NSIG}h", *[columns[c][t] for t in range(nsamp) for c in range(NSIG)])
    names_in_order = [NAMES[c] for c in range(NSIG)]
    header = [f"{stem} {NSIG} {FS} {nsamp}"] + [
        f"{stem}.dat 16 {60000.5 + c}({c - 9})/mV 16 0 {columns[c][0]} {sum(columns[c]) % 65536} 0 {names_in_order[c]}"
        for c in range(NSIG)
    ]
    signals = read_header("\n".join(header) + "\n", stem, nsamp)
    sample = expected_sample(raw, nsamp)
    assert struct.unpack(f"<{nsamp * len(KEPT)}h", sample) == tuple(columns[c][t] for t in range(nsamp) for c in KEPT)
    reason, _ = channel_checks(raw, signals, stem, nsamp)
    assert reason is None
    assert names_in_order[16] == "U1" and names_in_order[23:25] == ["U2", "U3"] and names_in_order[31] == "U4"
    assert len(KEPT) == 28 and names_in_order[17] == "W1" and names_in_order[25] == "W7" and names_in_order[30] == "W12"
    bad = bytearray(raw)
    bad[5] ^= 0x10
    try:
        channel_checks(bytes(bad), signals, stem, nsamp)
    except AssertionError:
        pass
    else:
        raise AssertionError("selftest: corrupted payload passed checksum")
    for broken in (header[1].replace(" 16 ", " 212 ", 1), header[1].replace("/mV", "/uV")):
        try:
            read_header("\n".join([header[0], broken] + header[2:]) + "\n", stem, nsamp)
        except AssertionError:
            continue
        raise AssertionError("selftest: malformed header accepted")
    columns[KEPT[3]] = [7] * nsamp
    raw_c = struct.pack(f"<{nsamp * NSIG}h", *[columns[c][t] for t in range(nsamp) for c in range(NSIG)])
    header_c = list(header)
    header_c[1 + KEPT[3]] = f"{stem}.dat 16 1.5(0)/mV 16 0 7 {(7 * nsamp) % 65536} 0 {names_in_order[KEPT[3]]}"
    reason, _ = channel_checks(raw_c, read_header("\n".join(header_c) + "\n", stem, nsamp), stem, nsamp)
    assert reason and "distinct" in reason
    print("verify_selftest=ok decoder=byte_slice+struct")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--download-dir", "--samples-root", "--index", "--stats", "--data-root", "--manifest"):
        parser.add_argument(flag, required=True)
    args = parser.parse_args()
    selftest()
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    series_dir = Path(args.samples_root) / SERIES_ID
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == DATASET_ID
    primaries = [s for s in manifest["series"] if s.get("role") == "primary"]
    assert [s["id"] for s in primaries] == [SERIES_ID], "manifest must declare exactly one primary series"
    series = primaries[0]
    assert (series["numeric_kind"], series["bit_width"], series["endianness"]) == ("int", 16, "little")
    assert series.get("sample_shape") == [NSAMP, len(KEPT)]

    sums = read_sums(download_dir / "SHA256SUMS.txt")
    trials = trial_list(sums)
    rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    by_name = {row["record_name"]: row for row in rows}
    assert len(by_name) == len(rows), "duplicate record names in index"

    emitted, excluded = [], []
    seen: dict[str, str] = {}
    aggregate = hashlib.sha256()
    dat_total = hea_total = 0
    channel_floor = 0
    for participant, gesture, stem in trials:
        folder = download_dir / "Session1" / f"session1_participant{participant}"
        raw = (folder / f"{stem}.dat").read_bytes()
        hea = (folder / f"{stem}.hea").read_bytes()
        dat_total += len(raw)
        hea_total += len(hea)
        assert hashlib.sha256(raw).hexdigest() == sums[f"Session1/session1_participant{participant}/{stem}.dat"], f"{stem}: dat sha256"
        assert hashlib.sha256(hea).hexdigest() == sums[f"Session1/session1_participant{participant}/{stem}.hea"], f"{stem}: hea sha256"
        signals = read_header(hea.decode("ascii"), stem, NSAMP)
        reason, kept_stats = channel_checks(raw, signals, stem, NSAMP)
        sample_expected = expected_sample(raw, NSAMP)
        digest = hashlib.sha256(sample_expected).hexdigest()
        if reason is None and digest in seen:
            reason = f"output identical to {seen[digest]}"
        if reason is not None:
            excluded.append(stem)
            assert stem not in by_name, f"{stem}: excluded trial was emitted ({reason})"
            continue
        seen[digest] = stem
        row = by_name.get(stem)
        assert row is not None, f"{stem}: valid trial missing from index"
        path = data_root / row["sample_path"]
        assert path.parent == series_dir and path.name == f"{stem}.bin", f"{stem}: unexpected sample path"
        sample = path.read_bytes()
        assert sample == sample_expected, f"{stem}: sample bytes differ from the byte-sliced source columns"
        lo = min(s[0] for s in kept_stats)
        hi = max(s[1] for s in kept_stats)
        min_distinct = min(s[2] for s in kept_stats)
        assert lo < hi and min_distinct >= MIN_DISTINCT, f"{stem}: constant or degenerate sample"
        channel_floor += sum(1 for s in kept_stats if s[0] == -32767)
        expected_row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int", "bit_width": 16,
            "endianness": "little", "element_size_bytes": 2, "sample_size_bytes": len(sample_expected),
            "value_count": len(sample_expected) // 2, "session": 1, "participant": participant, "gesture": gesture,
            "trial": 1, "sample_shape": [NSAMP, len(KEPT)], "sample_rate_hz": FS,
            "channel_names": [NAMES[c] for c in KEPT],
            "adc_gain_per_mv": [signals[c]["gain"] for c in KEPT],
            "baseline": [signals[c]["base"] for c in KEPT],
            "min": lo, "max": hi, "min_channel_distinct": min_distinct,
            "distinct_values": len(set(struct.unpack(f"<{len(sample_expected) // 2}h", sample_expected))),
            "sample_sha256": digest,
            "source_dat_sha256": sums[f"Session1/session1_participant{participant}/{stem}.dat"],
            "source_hea_sha256": sums[f"Session1/session1_participant{participant}/{stem}.hea"],
        }
        for key, value in expected_row.items():
            assert row[key] == value, f"{stem}: index field {key}={row[key]!r} != {value!r}"
        if gesture == 17:
            assert row["gesture_name"] == GESTURE_17
        emitted.append(stem)
        aggregate.update(sample)

    assert dat_total == EXPECTED_DAT_TOTAL and hea_total == EXPECTED_HEA_TOTAL, f"aggregate source sizes {dat_total}/{hea_total}"
    assert [row["record_name"] for row in rows] == emitted, "index order or membership differs from re-derivation"
    assert sorted(item["stem"] for item in stats["excluded"]) == sorted(excluded), "exclusion list differs"
    assert len(excluded) <= MAX_EXCLUDED_FRACTION * len(trials), "too many exclusions"
    on_disk = sorted(path.name for path in series_dir.iterdir())
    assert on_disk == sorted(f"{stem}.bin" for stem in emitted), "stray or missing files in the sample directory"
    total_values = sum(row["value_count"] for row in rows)
    assert series["sample_count"] == len(rows) == stats["sample_count"], (
        f"sample_count manifest={series['sample_count']} index={len(rows)} stats={stats['sample_count']}"
    )
    assert series["total_size_bytes"] == 2 * total_values == stats["total_size_bytes"], (
        f"total_size_bytes manifest={series['total_size_bytes']} derived={2 * total_values} stats={stats['total_size_bytes']}"
    )
    assert aggregate.hexdigest() == stats["aggregate_sha256"], "aggregate output hash differs from build stats"
    counts = sorted(row["value_count"] for row in rows)
    median = statistics.median(counts)
    assert median >= 1000 and total_values >= 10_000, "below acceptance floor"
    assert 2 * total_values <= 1_000_000_000, "primary output exceeds 1 GB cap"
    print(
        f"verify=ok samples={len(rows)} excluded={len(excluded)} values={total_values} bytes={2 * total_values} "
        f"median_values={median} participants={len({r['participant'] for r in rows})} gestures={len({r['gesture'] for r in rows})} "
        f"channels_min_at_-32767={channel_floor}/{len(rows) * len(KEPT)} aggregate_sha256={aggregate.hexdigest()}"
    )


if __name__ == "__main__":
    main()
