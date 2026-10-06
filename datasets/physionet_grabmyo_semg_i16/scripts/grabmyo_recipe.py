#!/usr/bin/env python3
"""GRABMyo 1.1.0 Session 1 / trial 1 surface-EMG recipe: download planning,
download validation, WFDB format-16 decoding, and sample build.

Pure standard library. Network I/O is done by download.sh with curl; this
script only plans curl batches and parses local files.

Subcommands:
  selftest          decode synthetic WFDB records (valid and invalid variants)
  plan              promote verified .part files, write a curl config for the rest
  check-downloads   checksum + semantic validation of every selected file
  build             emit one frame-interleaved int16 sample per gesture trial
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
from pathlib import Path

DATASET_ID = "physionet_grabmyo_semg_i16"
SERIES_ID = "grabmyo_semg_trial_i16"
VERSION = "1.1.0"

NSIG = 32
FS = 2048
NSAMP = 10240
DAT_BYTES = NSAMP * NSIG * 2  # 655,360
SIGNAL_NAMES = (
    [f"F{i}" for i in range(1, 17)]
    + ["U1"]
    + [f"W{i}" for i in range(1, 7)]
    + ["U2", "U3"]
    + [f"W{i}" for i in range(7, 13)]
    + ["U4"]
)
# 0-based source columns of the 28 electrode channels (source columns 1-16,
# 18-23, 26-31 in the project's 1-based numbering); U1-U4 are unused inputs.
KEPT = [index for index, name in enumerate(SIGNAL_NAMES) if name[0] in "FW"]
KEPT_NAMES = [SIGNAL_NAMES[index] for index in KEPT]
NKEPT = len(KEPT)

PARTICIPANTS = 43
GESTURES = 17
EXPECTED_TRIALS = PARTICIPANTS * GESTURES  # 731
EXPECTED_DAT_TOTAL = EXPECTED_TRIALS * DAT_BYTES  # 479,068,160
EXPECTED_HEA_TOTAL = 2_273_949
# sha256 of the canonical "<sha256>  <path>\n" lines of the 1,462 selected
# files (sorted by participant, gesture, extension) from SHA256SUMS.txt.
SELECTION_SHA256 = "ad6d952e14967043c9927534e834cf62f9b63676f3c0930a80ebbed99a0423dc"
GESTURE_NAMES = [
    "Lateral Prehension",
    "Thumb Adduction",
    "Thumb and Little Finger Opposition",
    "Thumb and Index Finger Opposition",
    "Thumb and Index Finger Extension",
    "Thumb and Little Finger Extension",
    "Index and Middle Finger Extension",
    "Little Finger Extension",
    "Index Finger Extension",
    "Thumb Finger Extension",
    "Wrist Extension",
    "Wrist Flexion",
    "Forearm Supination",
    "Forearm Pronation",
    "Hand Open",
    "Hand Close",
    "Rest",
]

INVALID_SAMPLE = -32768  # WFDB format-16 invalid/missing sample marker
MIN_DISTINCT_PER_CHANNEL = 256
MAX_EXCLUDED_FRACTION = 0.01

SELECT_RE = re.compile(
    r"^Session1/session1_participant(\d+)/session1_participant(\d+)_gesture(\d+)_trial1\.(dat|hea)$"
)
GAIN_RE = re.compile(r"^(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\((-?\d+)\)/mV$")


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checksums(download_dir: Path) -> dict[str, str]:
    sums: dict[str, str] = {}
    for number, line in enumerate((download_dir / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise SystemExit(f"SHA256SUMS.txt line {number} is malformed")
        if parts[1] in sums:
            raise SystemExit(f"SHA256SUMS.txt lists {parts[1]} twice")
        sums[parts[1]] = parts[0]
    return sums


def select_trials(sums: dict[str, str]) -> list[dict]:
    """Every Session1 trial-1 .dat/.hea pair listed in the pinned checksum file."""
    picked = []
    for path, digest in sums.items():
        match = SELECT_RE.match(path)
        if not match:
            continue
        if match.group(1) != match.group(2):
            raise SystemExit(f"participant folder/name mismatch: {path}")
        picked.append((int(match.group(1)), int(match.group(3)), match.group(4), digest, path))
    picked.sort()
    canonical = "".join(f"{digest}  {path}\n" for _, _, _, digest, path in picked)
    if sha256_bytes(canonical.encode("ascii")) != SELECTION_SHA256:
        raise SystemExit("selected Session1/trial1 file list differs from the pinned selection")
    trials: dict[tuple[int, int], dict] = {}
    for participant, gesture, ext, digest, path in picked:
        trial = trials.setdefault(
            (participant, gesture),
            {
                "participant": participant,
                "gesture": gesture,
                "stem": f"session1_participant{participant}_gesture{gesture}_trial1",
            },
        )
        trial[ext] = path
        trial[f"{ext}_sha256"] = digest
    expected_grid = {(p, g) for p in range(1, PARTICIPANTS + 1) for g in range(1, GESTURES + 1)}
    if set(trials) != expected_grid or len(trials) != EXPECTED_TRIALS:
        raise SystemExit(f"trial grid is not the complete {PARTICIPANTS} x {GESTURES} grid")
    for trial in trials.values():
        if "dat" not in trial or "hea" not in trial:
            raise SystemExit(f"incomplete pair for {trial['stem']}")
    return [trials[key] for key in sorted(trials)]


# --------------------------------------------------------------------------
# WFDB header + format-16 decoding
# --------------------------------------------------------------------------

def parse_header(text: str, stem: str, nsamp: int = NSAMP) -> dict:
    lines = [line.rstrip("\r") for line in text.split("\n")]
    comments = [line for line in lines if line.startswith("#")]
    body = [line for line in lines if line.strip() and not line.startswith("#")]
    if not body:
        raise ValueError("empty header")
    record = body[0].split()
    if record != [stem, str(NSIG), str(FS), str(nsamp)]:
        raise ValueError(f"record line {body[0]!r} != '{stem} {NSIG} {FS} {nsamp}'")
    if len(body) != 1 + NSIG:
        raise ValueError(f"expected {NSIG} signal lines, found {len(body) - 1}")
    signals = []
    for index, line in enumerate(body[1:]):
        tokens = line.split()
        if len(tokens) != 9:
            raise ValueError(f"signal {index}: expected 9 fields, found {len(tokens)}")
        fname, fmt, gain_spec, adcres, adczero, init, checksum, blocksize, name = tokens
        if fname != f"{stem}.dat":
            raise ValueError(f"signal {index}: file {fname!r}")
        if fmt != "16":
            raise ValueError(f"signal {index}: format {fmt!r} is not 16")
        if (adcres, adczero, blocksize) != ("16", "0", "0"):
            raise ValueError(f"signal {index}: adcres/adczero/blocksize {adcres}/{adczero}/{blocksize}")
        if name != SIGNAL_NAMES[index]:
            raise ValueError(f"signal {index}: name {name!r} != {SIGNAL_NAMES[index]!r}")
        match = GAIN_RE.match(gain_spec)
        if not match:
            raise ValueError(f"signal {index}: gain spec {gain_spec!r}")
        gain = float(match.group(1))
        if not (math.isfinite(gain) and gain > 0):
            raise ValueError(f"signal {index}: gain {gain}")
        signals.append(
            {
                "name": name,
                "gain": gain,
                "baseline": int(match.group(2)),
                "init": int(init),
                "checksum": int(checksum),
            }
        )
    return {"signals": signals, "comment_lines": len(comments)}


def decode_trial(blob: bytes, header: dict, nsamp: int = NSAMP) -> tuple[array.array, list[dict]]:
    """Validate a format-16 .dat against its header; return the kept channels
    frame-interleaved (nsamp x 28) and per-kept-channel statistics."""
    if len(blob) != nsamp * NSIG * 2:
        raise ValueError(f"dat size {len(blob)} != {nsamp * NSIG * 2}")
    full = array.array("h")
    if full.itemsize != 2:
        raise RuntimeError("array('h') is not 16-bit on this platform")
    full.frombytes(blob)
    if sys.byteorder != "little":
        full.byteswap()
    channels = []
    for index, signal in enumerate(header["signals"]):
        column = full[index::NSIG]
        if len(column) != nsamp:
            raise ValueError(f"signal {index}: {len(column)} samples")
        if column[0] != signal["init"]:
            raise ValueError(f"signal {signal['name']}: initial value {column[0]} != header {signal['init']}")
        if sum(column) % 65536 != signal["checksum"] % 65536:
            raise ValueError(f"signal {signal['name']}: checksum mismatch")
        channels.append(column)
    out = array.array("h", bytes(2 * nsamp * NKEPT))
    stats = []
    for slot, index in enumerate(KEPT):
        column = channels[index]
        out[slot::NKEPT] = column
        stats.append(
            {
                "name": SIGNAL_NAMES[index],
                "min": min(column),
                "max": max(column),
                "distinct": len(set(column)),
                "invalid": column.count(INVALID_SAMPLE),
                "gain": header["signals"][index]["gain"],
                "baseline": header["signals"][index]["baseline"],
            }
        )
    return out, stats


def exclusion_reason(stats: list[dict]) -> str | None:
    for channel in stats:
        if channel["invalid"]:
            return f"channel {channel['name']} has {channel['invalid']} WFDB invalid samples (-32768)"
        if channel["distinct"] < MIN_DISTINCT_PER_CHANNEL:
            return f"channel {channel['name']} has {channel['distinct']} < {MIN_DISTINCT_PER_CHANNEL} distinct codes"
    return None


def le_bytes(values: array.array) -> bytes:
    if sys.byteorder == "little":
        return values.tobytes()
    copy = array.array("h", values)
    copy.byteswap()
    return copy.tobytes()


# --------------------------------------------------------------------------
# selftest on synthetic records
# --------------------------------------------------------------------------

def synth_record(stem: str, nsamp: int, rng: random.Random, *, constant_channel: int | None = None,
                 invalid_channel: int | None = None) -> tuple[bytes, str, list[list[int]]]:
    columns = []
    for index in range(NSIG):
        if index == constant_channel:
            column = [123] * nsamp
        else:
            column = [rng.randint(-32767, 32767) for _ in range(nsamp)]
        if index == invalid_channel:
            column[nsamp // 2] = INVALID_SAMPLE
        columns.append(column)
    frames = array.array("h", [columns[c][t] for t in range(nsamp) for c in range(NSIG)])
    blob = le_bytes(frames)
    lines = [f"{stem} {NSIG} {FS} {nsamp}"]
    for index, name in enumerate(SIGNAL_NAMES):
        gain = 50000 + 1234.5678 * index
        lines.append(
            f"{stem}.dat 16 {gain!r}({index * 37 - 500})/mV 16 0 {columns[index][0]} {sum(columns[index]) % 65536} 0 {name}"
        )
    return blob, "\n".join(lines) + "\n", columns


def selftest() -> None:
    rng = random.Random(20261005)
    nsamp = 600
    stem = "session1_participant7_gesture3_trial1"
    blob, hea, columns = synth_record(stem, nsamp, rng)
    header = parse_header(hea, stem, nsamp)
    out, stats = decode_trial(blob, header, nsamp)
    expected = [columns[c][t] for t in range(nsamp) for c in KEPT]
    assert list(out) == expected, "interleave mismatch"
    assert le_bytes(out) == b"".join(blob[(t * NSIG + c) * 2:(t * NSIG + c) * 2 + 2] for t in range(nsamp) for c in KEPT)
    assert [s["name"] for s in stats] == KEPT_NAMES and len(KEPT) == 28
    assert exclusion_reason(stats) is None
    assert header["signals"][3]["baseline"] == 3 * 37 - 500

    def must_fail(blob_x: bytes, hea_x: str, label: str) -> None:
        try:
            decode_trial(blob_x, parse_header(hea_x, stem, nsamp), nsamp)
        except ValueError:
            return
        raise AssertionError(f"selftest: invalid variant accepted: {label}")

    must_fail(blob[:-2], hea, "short dat")
    must_fail(blob + b"\0\0", hea, "long dat")
    flipped = bytearray(blob)
    flipped[200] ^= 0x01
    must_fail(bytes(flipped), hea, "bit flip (checksum)")
    must_fail(blob, hea.replace(".dat 16 ", ".dat 212 ", 1), "format 212")
    must_fail(blob, hea.replace("/mV 16 0 ", "/mV 12 0 ", 1), "adc resolution")
    must_fail(blob, hea.replace(" F2\n", " F3\n", 1), "channel name order")
    must_fail(blob, hea.replace(f"{stem} {NSIG} ", f"{stem} 31 ", 1), "nsig")
    must_fail(blob, hea.replace(f"{stem} {NSIG} {FS} ", f"{stem} {NSIG} 1000 ", 1), "sampling rate")
    must_fail(blob, hea.replace(")/mV", ")/uV", 1), "units")
    lines = hea.split("\n")
    first = lines[1].split()
    first[5] = str(int(first[5]) + 1)
    lines[1] = " ".join(first)
    must_fail(blob, "\n".join(lines), "initial value")

    blob_c, hea_c, _ = synth_record(stem, nsamp, rng, constant_channel=KEPT[5])
    _, stats_c = decode_trial(blob_c, parse_header(hea_c, stem, nsamp), nsamp)
    assert "distinct codes" in (exclusion_reason(stats_c) or ""), "constant channel not flagged"
    blob_i, hea_i, _ = synth_record(stem, nsamp, rng, invalid_channel=KEPT[20])
    _, stats_i = decode_trial(blob_i, parse_header(hea_i, stem, nsamp), nsamp)
    assert "invalid" in (exclusion_reason(stats_i) or ""), "invalid sample not flagged"
    blob_u, hea_u, _ = synth_record(stem, nsamp, rng, constant_channel=SIGNAL_NAMES.index("U2"))
    _, stats_u = decode_trial(blob_u, parse_header(hea_u, stem, nsamp), nsamp)
    assert exclusion_reason(stats_u) is None, "unused channel must not affect exclusion"
    print("selftest=ok decoder=array_stride cases=1_valid,10_invalid,3_exclusion_rules")


# --------------------------------------------------------------------------
# download helpers
# --------------------------------------------------------------------------

def cfg_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cmd_plan(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    trials = select_trials(load_checksums(download_dir))
    pending = []
    verified = promoted = removed = 0
    for trial in trials:
        for ext in ("hea", "dat"):
            relative = trial[ext]
            expected = trial[f"{ext}_sha256"]
            final = download_dir / relative
            final.parent.mkdir(parents=True, exist_ok=True)
            part = final.with_name(final.name + ".part")
            if final.is_file():
                if sha256_file(final) == expected:
                    verified += 1
                    part.unlink(missing_ok=True)
                    continue
                print(f"checksum_mismatch_removed file={relative}")
                final.unlink()
                removed += 1
            if part.is_file():
                if sha256_file(part) == expected:
                    part.rename(final)
                    promoted += 1
                    continue
                part.unlink()
                removed += 1
            pending.append((relative, part))
    with open(args.config, "w", encoding="utf-8") as handle:
        for relative, part in pending:
            handle.write(f"url = {cfg_quote(args.base_url + '/' + relative)}\n")
            handle.write(f"output = {cfg_quote(str(part))}\n")
    with open(args.pending_out, "w", encoding="utf-8") as handle:
        handle.write(f"{len(pending)}\n")
    print(f"plan verified={verified} promoted={promoted} removed={removed} pending={len(pending)}")


def cmd_check_downloads(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    trials = select_trials(load_checksums(download_dir))
    dat_total = hea_total = 0
    inventory = []
    for trial in trials:
        blob = (download_dir / trial["dat"]).read_bytes()
        hea_raw = (download_dir / trial["hea"]).read_bytes()
        if sha256_bytes(blob) != trial["dat_sha256"]:
            raise SystemExit(f"checksum mismatch {trial['dat']}")
        if sha256_bytes(hea_raw) != trial["hea_sha256"]:
            raise SystemExit(f"checksum mismatch {trial['hea']}")
        try:
            header = parse_header(hea_raw.decode("ascii"), trial["stem"])
            decode_trial(blob, header)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SystemExit(f"semantic check failed for {trial['stem']}: {exc}")
        dat_total += len(blob)
        hea_total += len(hea_raw)
        inventory.append({"stem": trial["stem"], "dat_sha256": trial["dat_sha256"], "hea_bytes": len(hea_raw)})
    if dat_total != EXPECTED_DAT_TOTAL or hea_total != EXPECTED_HEA_TOTAL:
        raise SystemExit(f"aggregate size changed: dat={dat_total} hea={hea_total}")
    payload = {
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "trials": len(inventory),
        "dat_bytes": dat_total,
        "hea_bytes": hea_total,
        "selection_sha256": SELECTION_SHA256,
        "inventory": inventory,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"download_check=ok trials={len(inventory)} dat_bytes={dat_total} hea_bytes={hea_total}")


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def check_gesture_names(download_dir: Path) -> None:
    text = (download_dir / "MotionSequence.txt").read_text(encoding="utf-8", errors="replace")
    found = re.findall(r"\{'([^']+)'\}", text)
    if found != GESTURE_NAMES:
        raise SystemExit(f"MotionSequence.txt gesture list differs: {found}")


def cmd_build(args: argparse.Namespace) -> None:
    selftest()
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    series_dir = Path(args.samples_root) / SERIES_ID
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    check_gesture_names(download_dir)
    trials = select_trials(load_checksums(download_dir))
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    excluded = []
    seen: dict[str, str] = {}
    aggregate = hashlib.sha256()
    total_values = 0
    comment_lines = 0
    channel_min_at_floor = channel_max_near_ceiling = channel_count = 0
    p2p_uv = {"active": [], "rest": []}
    gains = []
    for number, trial in enumerate(trials, 1):
        blob = (download_dir / trial["dat"]).read_bytes()
        hea_raw = (download_dir / trial["hea"]).read_bytes()
        if sha256_bytes(blob) != trial["dat_sha256"] or sha256_bytes(hea_raw) != trial["hea_sha256"]:
            raise SystemExit(f"checksum mismatch for {trial['stem']}")
        try:
            header = parse_header(hea_raw.decode("ascii"), trial["stem"])
            values, stats = decode_trial(blob, header)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SystemExit(f"decode failed for {trial['stem']}: {exc}")
        comment_lines += header["comment_lines"]
        reason = exclusion_reason(stats)
        out = le_bytes(values)
        digest = sha256_bytes(out)
        if reason is None and digest in seen:
            reason = f"output identical to {seen[digest]}"
        if reason is not None:
            excluded.append({"stem": trial["stem"], "reason": reason})
            continue
        seen[digest] = trial["stem"]
        sample_path = series_dir / f"{trial['stem']}.bin"
        tmp_path = sample_path.with_name(sample_path.name + ".tmp")
        tmp_path.write_bytes(out)
        tmp_path.rename(sample_path)
        aggregate.update(out)
        total_values += len(values)
        for channel in stats:
            channel_count += 1
            channel_min_at_floor += channel["min"] == -32767
            channel_max_near_ceiling += channel["max"] >= 32764
            p2p_uv["rest" if trial["gesture"] == 17 else "active"].append(
                (channel["max"] - channel["min"]) / channel["gain"] * 1000.0
            )
            gains.append(channel["gain"])
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": os.path.relpath(sample_path, data_root),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(out),
                "value_count": len(values),
                "record_name": trial["stem"],
                "session": 1,
                "participant": trial["participant"],
                "gesture": trial["gesture"],
                "gesture_name": GESTURE_NAMES[trial["gesture"] - 1],
                "trial": 1,
                "sample_shape": [NSAMP, NKEPT],
                "sample_rate_hz": FS,
                "channel_names": KEPT_NAMES,
                "adc_gain_per_mv": [channel["gain"] for channel in stats],
                "baseline": [channel["baseline"] for channel in stats],
                "min": min(channel["min"] for channel in stats),
                "max": max(channel["max"] for channel in stats),
                "distinct_values": len(set(values)),
                "min_channel_distinct": min(channel["distinct"] for channel in stats),
                "sample_sha256": digest,
                "source_dat_sha256": trial["dat_sha256"],
                "source_hea_sha256": trial["hea_sha256"],
            }
        )
        if number % 100 == 0:
            print(f"progress trials={number}/{len(trials)} emitted={len(rows)}")
    if len(excluded) > MAX_EXCLUDED_FRACTION * len(trials):
        raise SystemExit(f"too many excluded trials: {len(excluded)}: {excluded[:5]}")
    tmp_index = index_path.with_name(index_path.name + ".tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.rename(index_path)

    def summary(values: list[float]) -> dict:
        if not values:
            return {}
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "min": round(ordered[0], 3),
            "p05": round(ordered[len(ordered) // 20], 3),
            "median": round(statistics.median(ordered), 3),
            "p95": round(ordered[(len(ordered) * 19) // 20], 3),
            "max": round(ordered[-1], 3),
        }

    stats_out = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "version": VERSION,
        "source_trials": len(trials),
        "sample_count": len(rows),
        "excluded": excluded,
        "total_values": total_values,
        "total_size_bytes": 2 * total_values,
        "values_per_sample": NSAMP * NKEPT,
        "channel_names": KEPT_NAMES,
        "dropped_unused_channels": [name for name in SIGNAL_NAMES if name[0] == "U"],
        "participants": len({row["participant"] for row in rows}),
        "gestures": len({row["gesture"] for row in rows}),
        "header_comment_lines": comment_lines,
        "kept_channels": channel_count,
        "kept_channels_min_at_-32767": channel_min_at_floor,
        "kept_channels_max_at_least_32764": channel_max_near_ceiling,
        "adc_gain_per_mv": summary(gains),
        "channel_peak_to_peak_uv_active_gestures": summary(p2p_uv["active"]),
        "channel_peak_to_peak_uv_rest_gesture": summary(p2p_uv["rest"]),
        "min_channel_distinct": min(row["min_channel_distinct"] for row in rows),
        "global_min": min(row["min"] for row in rows),
        "global_max": max(row["max"] for row in rows),
        "aggregate_sha256": aggregate.hexdigest(),
    }
    stats_path.write_text(json.dumps(stats_out, indent=1) + "\n", encoding="utf-8")
    print(
        f"build=ok samples={len(rows)} excluded={len(excluded)} values={total_values} bytes={2 * total_values} "
        f"min_channel_distinct={stats_out['min_channel_distinct']} "
        f"channels_min_at_floor={channel_min_at_floor}/{channel_count} aggregate_sha256={stats_out['aggregate_sha256']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    plan = sub.add_parser("plan")
    plan.add_argument("--download-dir", required=True)
    plan.add_argument("--base-url", required=True)
    plan.add_argument("--config", required=True)
    plan.add_argument("--pending-out", required=True)
    check = sub.add_parser("check-downloads")
    check.add_argument("--download-dir", required=True)
    build = sub.add_parser("build")
    for flag in ("--download-dir", "--samples-root", "--index", "--stats", "--data-root"):
        build.add_argument(flag, required=True)
    args = parser.parse_args()
    if args.command == "selftest":
        selftest()
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "check-downloads":
        cmd_check_downloads(args)
    else:
        cmd_build(args)


if __name__ == "__main__":
    main()
