#!/usr/bin/env python3
"""Decode Draeger PulmoVista 500 EIT .bin exports (PhysioNet
respiratory-heartrate-dataset 1.0.0) into raw little-endian float32 image
sequences.

Frame layout (4358 bytes, little-endian), as documented by the authors'
reader Code/read_binData.m:

    offset    0  8 B  time stamp (read_binData.m: "2 float32"; the bytes are
                      one float64 time-of-day in days, stepping 0.02 s)
    offset    8  4 B  float32 dummy
    offset   12  4096 B  1024 float32 pixel values (the primary payload)
    offset 4108  8 B  2 int32: MinMax, event marker
    offset 4116  30 B event text (int8)
    offset 4146  4 B  int32 timing error
    offset 4150  208 B 52 float32 Medibus values

Only the 1024 pixel values per frame are emitted; one sample per recording
holds all frames in stored order (frames x 32 x 32, row-major in the
caudal-cranial display orientation produced by read_binData.m's
reshape + rot90 + flipud, which is a transpose of MATLAB's column-major fill).

Recordings with dropped frames (any time-stamp step > 30 ms) are excluded by
rule; see MAX_FRAME_STEP_MS below.

Subcommands: resources, selftest, check-downloads, build, verify.
`build` copies the pixel bytes of every frame verbatim; `verify` re-derives
every value (and the exclusion decision) through an independent struct
decode, re-packs it as little-endian float32 and byte-compares the emitted
samples. Pure standard library.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import tomllib
from pathlib import Path

DATASET_ID = "physionet_eit_thorax_images_f32"
SERIES_ID = "pulmovista_eit_fem_image_f32"
SOURCE_SUBDIR = "EIT_rawData"

FRAME_BYTES = 4358
PIXELS = 1024
GRID = 32
OFF_TIME = 0
OFF_DUMMY = 8
OFF_PIXELS = 12
PIXEL_BYTES = PIXELS * 4
OFF_MINMAX = OFF_PIXELS + PIXEL_BYTES  # 4108
OFF_EVENT_TEXT = OFF_MINMAX + 8  # 4116
OFF_TIMING = OFF_EVENT_TEXT + 30  # 4146
OFF_MEDIBUS = OFF_TIMING + 4  # 4150
assert OFF_MEDIBUS + 52 * 4 == FRAME_BYTES

SECONDS_PER_DAY = 86400.0
CADENCE_MIN_MS = 19.0
CADENCE_MAX_MS = 21.0
MAX_IDENTICAL_CONSECUTIVE_FRACTION = 0.01
MIN_DISTINCT_VALUES_PER_FRAME = 256
# Exclusion rule: a recording with any frame step above 30 ms (dropped frames,
# i.e. not one continuous 50 Hz acquisition) is excluded. In this release the
# three such recordings (S02, S08, S09 FEM) also have their single all-zero
# reference frame 1-4 frames before a gap, and nearly all of their frames sit
# on a large static baseline (median per-frame max 7,329-8,690 AU vs 23-67 AU
# in the 17 continuous recordings); the same subjects' PEEP trials are on the
# normal scale. The cause is undocumented upstream.
MAX_FRAME_STEP_MS = 30.0
MAX_EXCLUSIONS = 5
EXPECTED_EXCLUSIONS = ("S02_FEM.bin", "S08_FEM.bin", "S09_FEM.bin")
# Homogeneity guard for retained recordings: the median over frames of the
# per-frame maximum pixel must stay on the relative-impedance scale (observed
# 23-67 AU for retained recordings vs 7,329-8,690 AU for the excluded ones).
MAX_RETAINED_MEDIAN_FRAME_MAX = 1000.0

# Pinned scope: every forced-expiratory-manoeuvre (FEM) recording of the
# release, one per subject. (name, bytes, sha256 from SHA256SUMS.txt)
RECORDINGS: list[tuple[str, int, str]] = [
    ("S01_FEM.bin", 13291900, "202478b26ad339e9d7fb7c9dfcde19ceb77a88d8a6d2ecab8e89500241b07e47"),
    ("S02_FEM.bin", 19828900, "4aeecc9e11b0a9946959423e3e960fa3e3fb0591ef4064d83aa80331b124c7ab"),
    ("S03_FEM.bin", 16124600, "a631ae317581778d452ea99facabdd0f249908c3cfc9f91ecac0541e265f5a9f"),
    ("S04_FEM.bin", 22007900, "c4eb284413ce3a14b9cac73e5ca5f598a8f18d9810c480d9a83ad62dc71a0fec"),
    ("S05_FEM.bin", 14163500, "f45a6740162ab050b027de55eafc479fc063190c09b2c2f6647938c062ed0014"),
    ("S06_FEM.bin", 13291900, "07e07d020e39231fa0765cb50d1d41ffbe15e4ec5cf7d4239fce05b4593d9e3d"),
    ("S07_FEM.bin", 15035100, "c2095aeae0df8aa4ddef93d9315db52714b0f30cf279f525a2bbac34a558409a"),
    ("S08_FEM.bin", 15906700, "6ad52dff8cb3b57be50276396cb9feba0bb31d48eb90f110c34d7f6ceadd4c22"),
    ("S09_FEM.bin", 14599300, "f05dee813698a191ef481bd1df2d9848aca3d1df098bb6601696752efd44978e"),
    ("S10_FEM.bin", 16124600, "95e955924e54e241f3cb8bea3f3515035423f2588a36262c3534a87d419c3e70"),
    ("S11_FEM.bin", 13291900, "09a2bc9e29a8a49273b9688e2cad0bc7f22c0aa05aaeb63fcd9a9f3956108a20"),
    ("S12_FEM.bin", 14381400, "b1d112f0f0deb2939efb4f1bac97fd3d2d83dcb6092c2392afbdf539c78993d4"),
    ("S13_FEM.bin", 20264700, "0742c2fcf71111531f75a193c7d89af512f21f94a19a7521a48b05ca8c30cc09"),
    ("S14_FEM.bin", 13291900, "75568dd64430a93578263eb44f662e2ff22898e045dc3777f483e1cccdbf4ae8"),
    ("S15_FEM.bin", 13074000, "7254bf15dd84d57af74c2e319badbca0f48e906935e545455aead48547c3caf3"),
    ("S16_FEM.bin", 36607200, "3b87994afef8cdceeb00340fc6e35111b0f0d12b84e706ec6ed3e63aebe6fbcf"),
    ("S17_FEM.bin", 20700500, "cc3071f5b3d58a6995ebeab09926a64cfe098236ae7738379aae36ef9823050c"),
    ("S18_FEM.bin", 13291900, "2d55eec30b8147ec2261702d1e7b28a86860775d7d49f1f5b626d8aa9c5c2d3c"),
    ("S19_FEM.bin", 13509800, "a505f68d849b223079358ecbbddd654a0a60fdfd33387714b8bff749567a56eb"),
    ("S20_FEM.bin", 13291900, "054656063d68cd7374b37df7fe6d82fbe7bbec1bb6582f01bbac7fc0721962cc"),
]


class RecipeError(Exception):
    pass


def fail(message: str) -> None:
    raise RecipeError(message)


def sample_name(source_name: str) -> str:
    return source_name  # S01_FEM.bin -> samples/<id>/<series>/S01_FEM.bin


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return float("nan")
    mid = n // 2
    return ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])


def cadence_stats(times_days: list[float], label: str) -> dict:
    """Shared semantic check on the per-frame float64 time-of-day stamps.

    A misaligned frame grid would produce garbage here, so the stamps must be
    finite day fractions in [0, 1) with a median step of 20 ms (50 Hz)."""
    for index, value in enumerate(times_days):
        if not math.isfinite(value) or not 0.0 <= value < 1.0:
            fail(f"{label}: frame {index} time stamp {value!r} is not a day fraction in [0, 1)")
    deltas_ms = [(b - a) * SECONDS_PER_DAY * 1000.0 for a, b in zip(times_days, times_days[1:])]
    med = median(deltas_ms) if deltas_ms else float("nan")
    if not CADENCE_MIN_MS <= med <= CADENCE_MAX_MS:
        fail(f"{label}: median frame step {med!r} ms is not 50 Hz")
    gaps = [[k + 1, round(d, 1)] for k, d in enumerate(deltas_ms) if d > MAX_FRAME_STEP_MS]
    return {
        "median_frame_step_ms": round(med, 4),
        "nonpositive_frame_steps": sum(1 for d in deltas_ms if d <= 0.0),
        "frame_steps_over_30ms": len(gaps),
        "frame_gaps_index_ms": gaps,
        "duration_s": round((times_days[-1] - times_days[0]) * SECONDS_PER_DAY + 0.02, 3),
    }


def exclusion_reason(stats: dict) -> str | None:
    """Shared rule, applied to statistics each path derives independently."""
    if stats["frame_steps_over_30ms"]:
        return (
            f"dropped frames: {stats['frame_steps_over_30ms']} frame steps > {MAX_FRAME_STEP_MS:g} ms "
            f"at (frame, ms) {stats['frame_gaps_index_ms']}; not one continuous 50 Hz acquisition "
            f"(median per-frame max {stats['median_frame_max']:.6g} AU)"
        )
    return None


def check_retained(stats: dict, label: str) -> None:
    """Degeneracy and homogeneity rules for an emitted recording."""
    if not stats["min"] < stats["max"]:
        fail(f"{label}: constant recording (min == max == {stats['min']!r})")
    if stats["identical_consecutive_frames"] > MAX_IDENTICAL_CONSECUTIVE_FRACTION * stats["frames"]:
        fail(f"{label}: {stats['identical_consecutive_frames']} of {stats['frames']} frames repeat their predecessor")
    if min(stats["distinct_values_first_mid_last_frame"]) < MIN_DISTINCT_VALUES_PER_FRAME:
        fail(f"{label}: degenerate frame with only {min(stats['distinct_values_first_mid_last_frame'])} distinct values")
    if not stats["median_frame_max"] <= MAX_RETAINED_MEDIAN_FRAME_MAX:
        fail(f"{label}: median per-frame max {stats['median_frame_max']!r} AU is off the relative-impedance scale")


def check_exclusions(excluded: list[str]) -> None:
    if len(excluded) > MAX_EXCLUSIONS:
        fail(f"{len(excluded)} recordings excluded (limit {MAX_EXCLUSIONS}): {excluded}")
    if tuple(excluded) != EXPECTED_EXCLUSIONS:
        fail(f"derived exclusions {excluded} differ from the documented set {list(EXPECTED_EXCLUSIONS)}")


# ----------------------------------------------------------------------------
# Build path: verbatim pixel-byte slicing, array-based statistics.
# ----------------------------------------------------------------------------

def build_recording(data: bytes, label: str) -> tuple[bytes, dict]:
    if len(data) == 0 or len(data) % FRAME_BYTES:
        fail(f"{label}: size {len(data)} is not a positive multiple of {FRAME_BYTES}")
    frames = len(data) // FRAME_BYTES
    out = bytearray()
    times: list[float] = []
    minimum = math.inf
    maximum = -math.inf
    total = 0.0
    zero_values = 0
    zero_hist: dict[int, int] = {}
    identical_consecutive = 0
    previous = b""
    distinct_checks: list[int] = []
    frame_maxima: list[float] = []
    all_zero_frames: list[int] = []
    for k in range(frames):
        base = k * FRAME_BYTES
        times.append(struct.unpack_from("<d", data, base + OFF_TIME)[0])
        pix = data[base + OFF_PIXELS: base + OFF_PIXELS + PIXEL_BYTES]
        values = array.array("f")
        values.frombytes(pix)
        if sys.byteorder != "little":
            values.byteswap()
        frame_sum = sum(values)
        if not math.isfinite(frame_sum):
            bad = next(i for i, v in enumerate(values) if not math.isfinite(v))
            fail(f"{label}: frame {k} pixel {bad} is non-finite ({values[bad]!r})")
        total += frame_sum
        frame_max = max(values)
        frame_maxima.append(frame_max)
        minimum = min(minimum, min(values))
        maximum = max(maximum, frame_max)
        zeros = values.count(0.0)
        zero_values += zeros
        zero_hist[zeros] = zero_hist.get(zeros, 0) + 1
        if zeros == PIXELS:
            all_zero_frames.append(k)
        if pix == previous:
            identical_consecutive += 1
        previous = pix
        if k in (0, frames // 2, frames - 1):
            distinct_checks.append(len(set(values)))
        out += pix
    stats = {
        "frames": frames,
        "values": frames * PIXELS,
        "bytes": frames * PIXEL_BYTES,
        "min": minimum,
        "max": maximum,
        "mean": total / (frames * PIXELS),
        "zero_values": zero_values,
        "zero_fraction": round(zero_values / (frames * PIXELS), 6),
        "zeros_per_frame_histogram": {str(key): zero_hist[key] for key in sorted(zero_hist)},
        "all_zero_reference_frames": all_zero_frames,
        "median_frame_max": median(frame_maxima),
        "identical_consecutive_frames": identical_consecutive,
        "distinct_values_first_mid_last_frame": distinct_checks,
    }
    stats.update(cadence_stats(times, label))
    return bytes(out), stats


# ----------------------------------------------------------------------------
# Verify path: independent struct decode -> re-pack -> byte compare.
# ----------------------------------------------------------------------------

UNPACK_PIXELS = struct.Struct("<1024f")
UNPACK_TIME = struct.Struct("<d")


def verify_recording(data: bytes, sample: bytes | None, label: str) -> dict:
    """Re-derive statistics; when `sample` is given, byte-compare every frame."""
    if len(data) % FRAME_BYTES or not data:
        fail(f"{label}: source size {len(data)} is not a positive multiple of {FRAME_BYTES}")
    frames = len(data) // FRAME_BYTES
    if sample is not None and len(sample) != frames * PIXEL_BYTES:
        fail(f"{label}: sample has {len(sample)} bytes, expected {frames * PIXEL_BYTES}")
    times = []
    minimum = math.inf
    maximum = -math.inf
    zero_values = 0
    identical_consecutive = 0
    previous: tuple | None = None
    distinct_checks: list[int] = []
    frame_maxima: list[float] = []
    all_zero_frames: list[int] = []
    for k in range(frames):
        base = k * FRAME_BYTES
        times.append(UNPACK_TIME.unpack_from(data, base + OFF_TIME)[0])
        values = UNPACK_PIXELS.unpack_from(data, base + OFF_PIXELS)
        if not all(map(math.isfinite, values)):
            fail(f"{label}: frame {k} contains a non-finite pixel")
        if sample is not None:
            repacked = UNPACK_PIXELS.pack(*values)
            if repacked != sample[k * PIXEL_BYTES:(k + 1) * PIXEL_BYTES]:
                fail(f"{label}: frame {k} sample bytes differ from the re-decoded pixels")
        frame_max = max(values)
        frame_maxima.append(frame_max)
        minimum = min(minimum, *values)
        maximum = max(maximum, frame_max)
        zeros = sum(1 for v in values if v == 0.0)
        zero_values += zeros
        if zeros == PIXELS:
            all_zero_frames.append(k)
        if previous is not None and values == previous:
            identical_consecutive += 1
        previous = values
        if k in (0, frames // 2, frames - 1):
            distinct_checks.append(len(set(values)))
    result = {
        "frames": frames,
        "min": minimum,
        "max": maximum,
        "zero_values": zero_values,
        "all_zero_reference_frames": all_zero_frames,
        "median_frame_max": median(frame_maxima),
        "identical_consecutive_frames": identical_consecutive,
        "distinct_values_first_mid_last_frame": distinct_checks,
    }
    result.update(cadence_stats(times, label))
    return result


# ----------------------------------------------------------------------------
# Synthetic self-test of both decoders.
# ----------------------------------------------------------------------------

def synth_frame(k: int, pixels: list[float], t0: float = 0.4788) -> bytes:
    frame = bytearray(FRAME_BYTES)
    struct.pack_into("<d", frame, OFF_TIME, t0 + k * 0.02 / SECONDS_PER_DAY)
    struct.pack_into("<f", frame, OFF_DUMMY, 0.0123 * (k + 1))
    struct.pack_into("<1024f", frame, OFF_PIXELS, *pixels)
    struct.pack_into("<2i", frame, OFF_MINMAX, -1 if k == 0 else 0, 7 if k == 1 else 0)
    frame[OFF_EVENT_TEXT:OFF_EVENT_TEXT + 30] = b"FEM start".ljust(30) if k == 1 else b" " * 30
    struct.pack_into("<i", frame, OFF_TIMING, 0)
    struct.pack_into("<52f", frame, OFF_MEDIBUS, *([-3.4e38] * 6 + [-1000.0] * 46))
    return bytes(frame)


def synth_pixels(k: int) -> list[float]:
    out = []
    for r in range(GRID):
        for c in range(GRID):
            if (r - 15.5) ** 2 + (c - 15.5) ** 2 > 16.5 ** 2:
                out.append(0.0)
            else:
                out.append(struct.unpack("<f", struct.pack("<f", math.sin(0.3 * r + 0.17 * c + 0.05 * k) * 40.0 + 0.001 * r * c - 2.5))[0])
    out[100] = -0.0 if k == 2 else out[100]
    return out


def build_checked(data: bytes, label: str) -> tuple[bytes, dict]:
    sample, stats = build_recording(data, label)
    if exclusion_reason(stats) is None:
        check_retained(stats, label)
    return sample, stats


def verify_checked(data: bytes, sample: bytes | None, label: str) -> dict:
    stats = verify_recording(data, sample, label)
    if exclusion_reason(stats) is None:
        check_retained(stats, label)
    return stats


def selftest() -> None:
    frames = 5
    pix = [synth_pixels(k) for k in range(frames)]
    data = b"".join(synth_frame(k, pix[k]) for k in range(frames))
    expected = b"".join(struct.pack("<1024f", *p) for p in pix)
    sample, stats = build_checked(data, "synthetic")
    if exclusion_reason(stats) is not None or stats["all_zero_reference_frames"]:
        fail("selftest: clean synthetic recording flagged")
    # Exclusion rule: a 100 ms time-stamp jump must be detected by both paths.
    gapped = bytearray(data)
    for k in range(3, frames):
        struct.pack_into("<d", gapped, k * FRAME_BYTES + OFF_TIME, 0.4788 + (k * 0.02 + 0.08) / SECONDS_PER_DAY)
    gapped = bytes(gapped)
    _, gstats = build_recording(gapped, "gapped")
    vgstats = verify_recording(gapped, None, "gapped")
    if exclusion_reason(gstats) is None or exclusion_reason(vgstats) is None or gstats["frame_gaps_index_ms"] != [[3, 100.0]] or vgstats["frame_gaps_index_ms"] != [[3, 100.0]]:
        fail(f"selftest: dropped-frame gap not detected {gstats['frame_gaps_index_ms']} {vgstats['frame_gaps_index_ms']}")
    # Reference (all-zero) frame detection agrees between paths.
    ref_pix = [list(p) for p in pix]
    ref_pix[3] = [0.0] * PIXELS
    ref_data = b"".join(synth_frame(k, ref_pix[k]) for k in range(frames))
    ref_sample, rstats = build_checked(ref_data, "reference")
    vrstats = verify_checked(ref_data, ref_sample, "reference")
    if rstats["all_zero_reference_frames"] != [3] or vrstats["all_zero_reference_frames"] != [3]:
        fail("selftest: all-zero reference frame not detected")
    if rstats["median_frame_max"] != vrstats["median_frame_max"]:
        fail("selftest: median frame max disagrees between paths")
    if sample != expected:
        fail("selftest: build decode mismatch")
    if stats["frames"] != frames or abs(stats["median_frame_step_ms"] - 20.0) > 1e-3:
        fail(f"selftest: build stats wrong {stats}")
    if stats["min"] != min(min(p) for p in pix) or stats["max"] != max(max(p) for p in pix):
        fail("selftest: build min/max wrong")
    vstats = verify_recording(data, sample, "synthetic")
    if vstats["min"] != stats["min"] or vstats["max"] != stats["max"] or vstats["zero_values"] != stats["zero_values"]:
        fail("selftest: verify stats disagree with build stats")
    # -0.0 bit pattern survives both paths
    if sample[2 * PIXEL_BYTES + 400: 2 * PIXEL_BYTES + 404] != b"\x00\x00\x00\x80":
        fail("selftest: -0.0 bit pattern lost")
    # Negative cases
    for label, bad_data, bad_sample in [
        ("truncated", data[:-1], None),
        ("misaligned", data[6:] + data[:6], None),
        ("misaligned_time_stamp", data[-4:] + data[:-4], None),
        ("nan_pixel", data[:FRAME_BYTES + OFF_PIXELS + 40] + struct.pack("<f", float("nan")) + data[FRAME_BYTES + OFF_PIXELS + 44:], None),
        ("inf_pixel", data[:OFF_PIXELS] + struct.pack("<f", float("inf")) + data[OFF_PIXELS + 4:], None),
        ("constant", b"".join(synth_frame(k, [1.5] * PIXELS) for k in range(frames)), None),
        ("off_scale", b"".join(synth_frame(k, [v * 1000.0 for v in pix[k]]) for k in range(frames)), None),
        ("tampered_sample", data, sample[:-4] + b"\x00\x00\x80\x3f"),
    ]:
        try:
            if bad_sample is None:
                build_checked(bad_data, label)
            else:
                verify_checked(bad_data, bad_sample, label)
        except RecipeError:
            pass
        else:
            fail(f"selftest: {label} input was not rejected")
        if bad_sample is None:
            # verify must reject the corrupted source even against the
            # correctly built sample of the good source
            try:
                verify_checked(bad_data, sample[: len(bad_data) // FRAME_BYTES * PIXEL_BYTES], label)
            except RecipeError:
                pass
            else:
                fail(f"selftest: verify accepted {label} input")
    print("selftest=ok decoders=build,verify cases=3 positive (clean, gap-exclusion, reference-frame), 8 negative")


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def check_downloads(download_dir: Path) -> None:
    src_dir = download_dir / SOURCE_SUBDIR
    total = 0
    for name, size, sha in RECORDINGS:
        path = src_dir / name
        if not path.is_file() or path.stat().st_size != size:
            fail(f"missing or wrong-sized download {path}")
        if size % FRAME_BYTES:
            fail(f"{name}: pinned size is not a multiple of {FRAME_BYTES}")
        if sha256_file(path) != sha:
            fail(f"{name}: sha256 mismatch")
        with path.open("rb") as handle:
            first = handle.read(FRAME_BYTES)
            handle.seek(size - FRAME_BYTES)
            last = handle.read(FRAME_BYTES)
        for which, frame in (("first", first), ("last", last)):
            t = UNPACK_TIME.unpack_from(frame, OFF_TIME)[0]
            values = UNPACK_PIXELS.unpack_from(frame, OFF_PIXELS)
            if not (math.isfinite(t) and 0.0 <= t < 1.0):
                fail(f"{name}: {which} frame time stamp {t!r} is not a day fraction")
            if not all(map(math.isfinite, values)) or min(values) == max(values):
                fail(f"{name}: {which} frame pixels are non-finite or constant")
        total += size
        print(f"download_ok file={name} bytes={size} frames={size // FRAME_BYTES}")
    print(f"downloads_validated files={len(RECORDINGS)} bytes={total}")


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    os.replace(tmp, path)


def build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    download_dir = Path(args.download_dir)
    series_dir = Path(args.samples_dir) / SERIES_ID
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    series_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    per_recording = []
    exclusions = []
    aggregate = hashlib.sha256()
    for name, size, sha in RECORDINGS:
        path = download_dir / SOURCE_SUBDIR / name
        if not path.is_file() or path.stat().st_size != size:
            fail(f"missing or wrong-sized local source {path}; run download.sh")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            fail(f"{name}: local source sha256 mismatch")
        sample, stats = build_recording(data, name)
        reason = exclusion_reason(stats)
        if reason is not None:
            exclusions.append({"recording": name, "reason": reason, **stats})
            print(f"excluded={name} frames={stats['frames']} reason={reason}")
            continue
        check_retained(stats, name)
        out_path = series_dir / sample_name(name)
        write_atomic(out_path, sample)
        sample_sha = hashlib.sha256(sample).hexdigest()
        aggregate.update(sample)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": out_path.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(sample),
            "value_count": len(sample) // 4,
            "shape": [stats["frames"], GRID, GRID],
            "axes": ["frame_50hz", "image_row", "image_column"],
            "source_file": f"{SOURCE_SUBDIR}/{name}",
            "source_sha256": sha,
            "sha256": sample_sha,
            "min": stats["min"],
            "max": stats["max"],
            "zero_value_count": stats["zero_values"],
        })
        per_recording.append({"recording": name, "sample_sha256": sample_sha, **stats})
        print(
            f"sample={name} frames={stats['frames']} values={stats['values']} min={stats['min']:.6g} "
            f"max={stats['max']:.6g} median_frame_max={stats['median_frame_max']:.6g} "
            f"zero_fraction={stats['zero_fraction']} reference_frames={stats['all_zero_reference_frames']} "
            f"step_ms={stats['median_frame_step_ms']} gaps={stats['frame_steps_over_30ms']} "
            f"nonpos={stats['nonpositive_frame_steps']} repeats={stats['identical_consecutive_frames']}"
        )
    check_exclusions([item["recording"] for item in exclusions])
    kept = {sample_name(row["source_file"].split("/")[-1]) for row in rows}
    for stale in series_dir.iterdir():
        if stale.name not in kept:
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(index_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode())
    values = [row["value_count"] for row in rows]
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(rows),
        "frames": sum(r["frames"] for r in per_recording),
        "values": sum(values),
        "bytes": sum(row["sample_size_bytes"] for row in rows),
        "median_sample_values": median([float(v) for v in values]),
        "min_sample_values": min(values),
        "max_sample_values": max(values),
        "global_min": min(row["min"] for row in rows),
        "global_max": max(row["max"] for row in rows),
        "zero_fraction": round(sum(row["zero_value_count"] for row in rows) / sum(values), 6),
        "non_finite_values": 0,
        "exclusion_rule": f"exclude a recording with any frame step > {MAX_FRAME_STEP_MS:g} ms (dropped frames)",
        "exclusions": exclusions,
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "recordings": per_recording,
    }
    write_atomic(stats_path, (json.dumps(summary, indent=1) + "\n").encode())
    print(
        f"build_summary samples={summary['samples']} excluded={len(exclusions)} frames={summary['frames']} "
        f"values={summary['values']} bytes={summary['bytes']} median_values={summary['median_sample_values']} "
        f"range=[{summary['global_min']:.6g},{summary['global_max']:.6g}] zero_fraction={summary['zero_fraction']} "
        f"aggregate_sha256={summary['aggregate_sample_sha256']}"
    )


def verify(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    download_dir = Path(args.download_dir)
    series_dir = Path(args.samples_dir) / SERIES_ID
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest.get("series", [])) != 1:
        fail("manifest must declare exactly the one primary series")
    series = series[0]
    if (series.get("role"), series.get("numeric_kind"), series.get("bit_width"), series.get("endianness")) != ("primary", "float", 32, "little"):
        fail("manifest series role/kind/width/endianness mismatch")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows_by_source = {}
    for row in rows:
        key = row.get("source_file")
        if key in rows_by_source:
            fail(f"duplicate index row for {key}")
        rows_by_source[key] = row
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    aggregate = hashlib.sha256()
    total_bytes = 0
    total_values = 0
    retained: list[str] = []
    excluded: list[str] = []
    for name, size, sha in RECORDINGS:
        source = download_dir / SOURCE_SUBDIR / name
        if not source.is_file() or source.stat().st_size != size:
            fail(f"{name}: local source missing or wrong size")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            fail(f"{name}: local source sha256 mismatch")
        # First pass without a sample: derive the exclusion decision independently.
        probe = verify_recording(data, None, name)
        reason = exclusion_reason(probe)
        row = rows_by_source.get(f"{SOURCE_SUBDIR}/{name}")
        sample_path = series_dir / sample_name(name)
        if reason is not None:
            if row is not None or sample_path.exists():
                fail(f"{name}: excluded by rule ({reason}) but present in index or samples")
            excluded.append(name)
            print(f"verified_exclusion={name} reason={reason}")
            continue
        check_retained(probe, name)
        if row is None or not sample_path.is_file():
            fail(f"{name}: retained by rule but missing from index or samples")
        expected_row_keys = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "source_sha256": sha,
        }
        for key, value in expected_row_keys.items():
            if row.get(key) != value:
                fail(f"{name}: index {key}={row.get(key)!r}, expected {value!r}")
        sample = sample_path.read_bytes()
        result = verify_recording(data, sample, name)
        frames = size // FRAME_BYTES
        checks = {
            "sample_size_bytes": frames * PIXEL_BYTES,
            "value_count": frames * PIXELS,
            "shape": [frames, GRID, GRID],
            "sha256": hashlib.sha256(sample).hexdigest(),
            "min": result["min"],
            "max": result["max"],
            "zero_value_count": result["zero_values"],
        }
        for key, value in checks.items():
            if row.get(key) != value:
                fail(f"{name}: index {key}={row.get(key)!r} but re-derived {value!r}")
        retained.append(name)
        aggregate.update(sample)
        total_bytes += len(sample)
        total_values += len(sample) // 4
        print(
            f"verified={name} frames={frames} min={result['min']:.6g} max={result['max']:.6g} "
            f"median_frame_max={result['median_frame_max']:.6g} zeros={result['zero_values']} "
            f"reference_frames={result['all_zero_reference_frames']} step_ms={result['median_frame_step_ms']} "
            f"repeats={result['identical_consecutive_frames']}"
        )
    check_exclusions(excluded)
    if len(rows) != len(retained) or [r["source_file"] for r in rows] != [f"{SOURCE_SUBDIR}/{n}" for n in retained]:
        fail("index rows do not match the retained recordings in canonical order")
    on_disk = sorted(p.name for p in series_dir.iterdir())
    if on_disk != sorted(sample_name(n) for n in retained):
        fail(f"unexpected sample files: {on_disk}")
    if [item.get("recording") for item in stats.get("exclusions", [])] != excluded:
        fail("ingest_stats.json exclusions disagree with the re-derived exclusions")
    if series.get("sample_count") != len(rows):
        fail(f"manifest sample_count {series.get('sample_count')} != {len(rows)}")
    if series.get("total_size_bytes") != total_bytes:
        fail(f"manifest total_size_bytes {series.get('total_size_bytes')} != {total_bytes}")
    if total_bytes > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    values = sorted(row["value_count"] for row in rows)
    med = median([float(v) for v in values])
    if total_values < 10_000 or med < 1_000:
        fail("acceptance floor not met")
    if stats.get("aggregate_sample_sha256") != aggregate.hexdigest() or stats.get("bytes") != total_bytes:
        fail("ingest_stats.json disagrees with re-derived samples")
    print(
        f"verify_summary samples={len(rows)} excluded={len(excluded)} values={total_values} bytes={total_bytes} "
        f"median_values={med} aggregate_sha256={aggregate.hexdigest()}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resources")
    sub.add_parser("selftest")
    p = sub.add_parser("check-downloads")
    p.add_argument("--download-dir", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--samples-dir", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--stats", required=True)
        p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        if args.command == "resources":
            for name, size, sha in RECORDINGS:
                print(f"{name} {size} {sha}")
        elif args.command == "selftest":
            selftest()
        elif args.command == "check-downloads":
            check_downloads(Path(args.download_dir))
        elif args.command == "build":
            build(args)
        else:
            verify(args)
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
