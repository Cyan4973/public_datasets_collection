#!/usr/bin/env python3
"""Independent verification of the Arni impulse-response samples.

Re-derives every sample from the downloaded WAV members with a separate
minimal RIFF walker (not the build's parser), checks the member CRC-32
against the archive's own central directory (parsed from the downloaded
directory bytes, not the pinned table), recomputes statistics from the stored
float32 sample bytes, and checks the index, the panel table and the manifest
totals.  Rejects NaN/Inf, all-zero, constant and duplicate samples, any
selected combination from the special block numComb 2..31, any selected
member below 200,000 compressed bytes, any sample with >= 1% of values on
the int16 (2^-15) lattice or < 50,000 distinct float32 bit patterns, and any
configuration whose five receivers are not distinct (max zero-lag |r| over
samples [1500, 17884) must be < 0.5; computed here from raw sums on the
stored sample bytes, independently of arni_tool.py distinctness).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arni_zip as az  # noqa: E402  (ZIP central-directory parsing only)

DATASET_ID = "aalto_arni_room_impulse_response_f32"
SERIES_ID = "arni_room_impulse_response_f32"
EXPECTED_SAMPLES = 265
EXPECTED_VALUES = 105840
EXPECTED_FMT = (3, 1, 44100, 176400, 4, 32)
WINDOW_START, WINDOW_END = 1500, 17884
MAX_RECEIVER_ABS_R = 0.5
# int16-quantized members written as float32 DEFLATE to ~13 KB; genuine
# members are >= 342,676 B.  Every selected member must reach this size.
MIN_COMPRESSED_BYTES = 200_000
# Float-lattice / degeneracy limits (independent of arni_zip.float32_stats).
MAX_LATTICE_FRACTION = 0.01
MIN_DISTINCT_PATTERNS = 50_000
NOISE_TAIL_START = 88200  # 2.0 s
# Levels whose upstream receiver files repeat responses across mic labels.
EXCLUDED_LEVELS = (11, 27, 35)
EXPECTED_LEVELS = [k for k in range(56) if k not in EXCLUDED_LEVELS]


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


class WindowStats:
    """Raw sums for a zero-lag Pearson correlation over the check window."""

    def __init__(self, values: tuple[float, ...]):
        self.values = values
        self.n = len(values)
        self.sx = math.fsum(values)
        self.sxx = math.sumprod(values, values)

    def r(self, other: "WindowStats") -> float:
        sxy = math.sumprod(self.values, other.values)
        cov = self.n * sxy - self.sx * other.sx
        var_a = self.n * self.sxx - self.sx * self.sx
        var_b = other.n * other.sxx - other.sx * other.sx
        if var_a <= 0.0 or var_b <= 0.0:
            fail("zero-variance receiver-distinctness window")
        return cov / math.sqrt(var_a * var_b)


def riff_data_chunk(wav: bytes, label: str) -> bytes:
    """Minimal independent RIFF walk returning the data chunk of a float32 WAV."""
    if wav[0:4] != b"RIFF" or wav[8:12] != b"WAVE" or int.from_bytes(wav[4:8], "little") + 8 != len(wav):
        fail(f"{label}: bad RIFF header")
    fmt = None
    data = None
    offset = 12
    while offset + 8 <= len(wav):
        cid = wav[offset : offset + 4]
        size = int.from_bytes(wav[offset + 4 : offset + 8], "little")
        body = wav[offset + 8 : offset + 8 + size]
        if len(body) != size:
            fail(f"{label}: chunk {cid!r} truncated")
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            data = body
        offset += 8 + size + (size % 2)
    if offset != len(wav):
        fail(f"{label}: trailing bytes after last chunk")
    if fmt != EXPECTED_FMT:
        fail(f"{label}: fmt {fmt} is not mono 44.1 kHz IEEE float32")
    if data is None or len(data) != EXPECTED_VALUES * 4:
        fail(f"{label}: data chunk missing or not {EXPECTED_VALUES} float32 values")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-dir", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    recipe_dir = Path(args.recipe_dir)
    data_root = Path(args.data_root)
    download_dir = data_root / "downloads" / DATASET_ID
    wav_dir = download_dir / "wav"
    meta_dir = download_dir / "zip_directory"
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"

    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary":
        fail("manifest must declare exactly one primary series")
    series = series[0]

    with (recipe_dir / "selection.tsv").open(encoding="utf-8", newline="") as handle:
        selection = list(csv.DictReader(handle, delimiter="\t"))
    with (recipe_dir / "zip_archives.tsv").open(encoding="utf-8", newline="") as handle:
        archives = list(csv.DictReader(handle, delimiter="\t"))

    # Selection scope: numClosed 0..55 except 11/27/35, one combination each, mics 1..5, sweep 1.
    if len(selection) != EXPECTED_SAMPLES:
        fail(f"selection has {len(selection)} rows")
    combos: dict[int, set[int]] = {}
    mics: dict[int, list[int]] = {}
    for row in selection:
        k = int(row["num_closed"])
        combos.setdefault(k, set()).add(int(row["num_comb"]))
        mics.setdefault(k, []).append(int(row["mic"]))
        if row["sweep"] != "1":
            fail(f"{row['member']}: sweep {row['sweep']} selected")
        if 2 <= int(row["num_comb"]) <= 31:
            fail(f"{row['member']}: numComb {row['num_comb']} is in the excluded special block 2..31")
    if sorted(combos) != EXPECTED_LEVELS or any(len(v) != 1 for v in combos.values()):
        fail("selection must hold one combination for every numClosed 0..55 except 11, 27, 35")
    if any(sorted(v) != [1, 2, 3, 4, 5] for v in mics.values()):
        fail("selection must hold receivers 1..5 for every numClosed")

    # CRC-32 reference from each archive's own central directory.
    cd_crc: dict[str, int] = {}
    cd_compressed: dict[str, int] = {}
    for archive in archives:
        name = archive["archive"]
        size = int(archive["size_bytes"])
        cd = (meta_dir / f"{name}.cd.bin").read_bytes()
        if hashlib.sha256(cd).hexdigest() != archive["cd_sha256"]:
            fail(f"{name}: central directory SHA-256 differs from pin")
        tail = (meta_dir / f"{name}.tail.bin").read_bytes()
        loc = az.locate_central_directory(tail, size - len(tail), size)
        for member in az.parse_central_directory(cd, loc.entries):
            cd_crc[member.name] = member.crc32
            cd_compressed[member.name] = member.compressed_size
    small = [row["member"] for row in selection if cd_compressed.get(row["member"], 0) < MIN_COMPRESSED_BYTES]
    if small:
        fail(f"selected members below {MIN_COMPRESSED_BYTES} compressed bytes: {small}")
    print(
        f"compressed_size_ok min_selected={min(cd_compressed[row['member']] for row in selection)} "
        f">= {MIN_COMPRESSED_BYTES}"
    )

    # Panel table.
    rows = list(csv.reader(io.StringIO((download_dir / "combinations_setup.csv").read_text(encoding="utf-8-sig")), delimiter=";"))
    panel = {int(r[0]): "".join("1" if v == "1.0" else "0" for v in r[1:]) for r in rows[1:] if r}

    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != EXPECTED_SAMPLES:
        fail(f"index has {len(index)} rows")
    by_member = {row["source_member"]: row for row in index}
    if set(by_member) != {row["member"] for row in selection}:
        fail("index members differ from the pinned selection")

    seen_hashes: set[str] = set()
    expected_paths: set[str] = set()
    total_bytes = 0
    total_values = 0
    windows: dict[tuple[int, int], dict[int, WindowStats]] = {}
    peaks: list[float] = []
    tails: list[float] = []
    lattice_worst = (0.0, "")
    distinct_worst = (None, "")
    for row in selection:
        member = row["member"]
        entry = by_member[member]
        wav = (wav_dir / member).read_bytes()
        crc = zlib.crc32(wav) & 0xFFFFFFFF
        if crc != cd_crc.get(member) or f"{crc:08x}" != row["crc32"]:
            fail(f"{member}: CRC-32 {crc:08x} disagrees with the central directory")
        data = riff_data_chunk(wav, member)
        stem = f"IR_numClosed_{row['num_closed']}_numComb_{row['num_comb']}_mic_{row['mic']}_sweep_{row['sweep']}"
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{stem}.bin"
        expected_paths.add(rel)
        if entry["sample_path"] != rel:
            fail(f"{member}: index sample_path {entry['sample_path']!r} != {rel!r}")
        stored = (data_root / rel).read_bytes()
        if stored != data:
            fail(f"{member}: stored sample differs from the WAV data chunk")
        values = struct.unpack(f"<{len(stored) // 4}f", stored)
        if not all(math.isfinite(v) for v in values):
            fail(f"{member}: non-finite value")
        if all(v == 0.0 for v in values):
            fail(f"{member}: all-zero sample")
        lo, hi = min(values), max(values)
        if lo == hi:
            fail(f"{member}: constant sample")
        # Hollow-width check: values on the 2^-15 grid are int16 codes stored
        # as float32; genuine float samples have ~0% there and ~10^5 patterns.
        lattice = sum(1 for v in values if (v * 32768.0).is_integer()) / len(values)
        patterns = len({stored[i : i + 4] for i in range(0, len(stored), 4)})
        if lattice >= MAX_LATTICE_FRACTION:
            fail(f"{member}: {lattice:.2%} of values on the int16 lattice (widened integer data)")
        if patterns < MIN_DISTINCT_PATTERNS:
            fail(f"{member}: only {patterns} distinct float32 bit patterns")
        if not lattice_worst[1] or lattice > lattice_worst[0]:
            lattice_worst = (lattice, member)
        if distinct_worst[0] is None or patterns < distinct_worst[0]:
            distinct_worst = (patterns, member)
        digest = hashlib.sha256(stored).hexdigest()
        if digest in seen_hashes:
            fail(f"{member}: duplicate sample content")
        seen_hashes.add(digest)
        expected_entry = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(stored),
            "value_count": len(values),
            "role": "primary",
            "num_closed": int(row["num_closed"]),
            "num_comb": int(row["num_comb"]),
            "mic": int(row["mic"]),
            "sweep": int(row["sweep"]),
            "source_archive": row["archive"],
            "sample_sha256": digest,
            "min": lo,
            "max": hi,
            "panel_state_reflective0_absorptive1": panel[int(row["num_comb"])],
        }
        for key, value in expected_entry.items():
            if entry.get(key) != value:
                fail(f"{member}: index field {key}={entry.get(key)!r}, expected {value!r}")
        if panel[int(row["num_comb"])].count("0") != int(row["num_closed"]):
            fail(f"{member}: panel table reflective count disagrees with numClosed")
        total_bytes += len(stored)
        total_values += len(values)
        config = (int(row["num_closed"]), int(row["num_comb"]))
        windows.setdefault(config, {})[int(row["mic"])] = WindowStats(values[WINDOW_START:WINDOW_END])
        peaks.append(max(abs(lo), abs(hi)))
        tail = values[NOISE_TAIL_START:]
        tails.append(math.sqrt(math.sumprod(tail, tail) / len(tail)))

    # Receiver distinctness (fatal) and cross-configuration similarity (logged).
    distinct_failures = []
    per_config = []
    for config in sorted(windows):
        receivers = windows[config]
        best = max(
            ((abs(receivers[a].r(receivers[b])), a, b) for a in range(1, 6) for b in range(a + 1, 6)),
        )
        per_config.append(best[0])
        print(f"receiver_max_abs_r numClosed={config[0]} numComb={config[1]} r={best[0]:.4f} mic{best[1]}/mic{best[2]}")
        if not best[0] < MAX_RECEIVER_ABS_R:
            distinct_failures.append(f"{config} mic{best[1]}/mic{best[2]} |r|={best[0]:.4f}")
    if distinct_failures:
        fail(f"receivers not distinct (|r| >= {MAX_RECEIVER_ABS_R}): {distinct_failures}")
    configs = sorted(windows)
    cross_best = (0.0, None)
    for mic in range(1, 6):
        for i, first in enumerate(configs):
            for second in configs[i + 1 :]:
                r = abs(windows[first][mic].r(windows[second][mic]))
                if r > cross_best[0]:
                    cross_best = (r, (mic, first, second))
    ordered = sorted(per_config)
    print(
        f"receiver_distinctness_ok configs={len(configs)} max_abs_r={ordered[-1]:.4f} "
        f"median={ordered[len(ordered) // 2]:.4f} threshold<{MAX_RECEIVER_ABS_R}"
    )
    print(f"cross_configuration_same_mic_max_abs_r={cross_best[0]:.4f} (mic, configA, configB)={cross_best[1]} (informational)")
    print(
        f"float_lattice_ok max_int16_lattice_fraction={lattice_worst[0]:.6f} ({lattice_worst[1]}) "
        f"min_distinct_bit_patterns={distinct_worst[0]} ({distinct_worst[1]}) "
        f"limits: fraction<{MAX_LATTICE_FRACTION} patterns>={MIN_DISTINCT_PATTERNS}"
    )
    peaks.sort()
    tails.sort()
    print(
        f"peak_abs min={peaks[0]:.3e} median={peaks[len(peaks) // 2]:.3e} max={peaks[-1]:.3e}; "
        f"noise_tail_rms_2.0-2.4s min={tails[0]:.3e} median={tails[len(tails) // 2]:.3e} max={tails[-1]:.3e} (informational)"
    )

    actual_paths = {p.relative_to(data_root).as_posix() for p in series_dir.iterdir()}
    if actual_paths != expected_paths:
        fail(f"sample directory holds unexpected files: {sorted(actual_paths ^ expected_paths)[:5]}")
    if series["sample_count"] != EXPECTED_SAMPLES or series["total_size_bytes"] != total_bytes:
        fail(
            f"manifest claims {series['sample_count']} samples / {series['total_size_bytes']} bytes; "
            f"realized {EXPECTED_SAMPLES} / {total_bytes}"
        )
    print(
        f"verify_ok samples={EXPECTED_SAMPLES} values={total_values} bytes={total_bytes} "
        f"levels={len(EXPECTED_LEVELS)} (numClosed 0..55 except 11, 27, 35) receivers=1..5 sweep=1"
    )


if __name__ == "__main__":
    main()
