#!/usr/bin/env python3
"""Build: emit the complete ICP channel of each CHARIS record as raw LE int16.

One pass per record over the interleaved WFDB format-16 .dat (frame = ABP,
ECG, ICP as little-endian int16): hash the source bytes, verify the WFDB
checksum of all three signals, de-interleave stride 3 keeping index 2 (ICP),
and accumulate descriptive diagnostics. No value is clipped, scaled, dropped
or imputed. Header comment lines (age, sex, diagnoses, outcome) are discarded
on parse and never written anywhere.
"""
from __future__ import annotations

import argparse
from array import array
import collections
import hashlib
import json
import operator
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charis_pins as pins  # noqa: E402
import charis_synth  # noqa: E402

GAIN_RE = re.compile(r"^(\d+(?:\.\d+)?)\((-?\d+)\)/(\S+)$")
CHUNK_FRAMES = pins.WINDOW_SAMPLES * 200


def parse_header(text: str, record_id: str, nsamp: int) -> dict:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    if len(lines) != 4:
        raise ValueError(f"{record_id}: expected 1 record line + 3 signal lines, got {len(lines)}")
    head = lines[0].split()
    if len(head) != 4 or head[0] != record_id or head[1] != "3" or head[2] != str(pins.SAMPLING_HZ):
        raise ValueError(f"{record_id}: unexpected record line {lines[0]!r}")
    if int(head[3]) != nsamp:
        raise ValueError(f"{record_id}: nsamp {head[3]} != {nsamp}")
    signals = []
    for index, line in enumerate(lines[1:]):
        fields = line.split()
        if len(fields) != 9:
            raise ValueError(f"{record_id}: signal line {index} has {len(fields)} fields")
        filename, fmt, gain_spec, adc_res, adc_zero, init_value, checksum, block_size, description = fields
        if filename != f"{record_id}.dat" or fmt != "16":
            raise ValueError(f"{record_id}: signal {index} is not in {record_id}.dat format 16")
        if adc_res != "0" or adc_zero != "0" or block_size != "0":
            raise ValueError(f"{record_id}: signal {index} has unexpected adc/block fields")
        if description != pins.SIGNALS[index]:
            raise ValueError(f"{record_id}: signal {index} is {description!r}, expected {pins.SIGNALS[index]}")
        match = GAIN_RE.match(gain_spec)
        if not match:
            raise ValueError(f"{record_id}: unparseable gain {gain_spec!r}")
        signals.append({
            "name": description,
            "gain_text": match.group(1),
            "gain": float(match.group(1)),
            "baseline": int(match.group(2)),
            "units": match.group(3),
            "header_initial_value": int(init_value),
            "checksum": int(checksum),
        })
    if signals[pins.ICP_INDEX]["units"] != "mmHg":
        raise ValueError(f"{record_id}: ICP units are not mmHg")
    return {"nsamp": nsamp, "signals": signals}


def has_waveform(segment) -> bool:
    """Lag-1 autocorrelation >= 0.5, exact in integers (algebraic form).

    With S = sum(x), y_i = n*x_i - S:
      sum_{i<n-1} y_i*y_{i+1} = n^2*P - n*S*(2S - x_0 - x_{n-1}) + (n-1)*S^2,  P = sum x_i*x_{i+1}
      sum_i y_i^2             = n^2*Q - n*S^2,                                  Q = sum x_i^2
    and the window has a waveform iff 2*lag1 >= energy.
    """
    n = len(segment)
    if n < 2:
        return True
    total = sum(segment)
    lag_products = sum(map(operator.mul, segment[:-1], segment[1:]))
    squares = sum(map(operator.mul, segment, segment))
    lag1 = n * n * lag_products - n * total * (2 * total - segment[0] - segment[-1]) + (n - 1) * total * total
    energy = n * n * squares - n * total * total
    return 2 * lag1 >= energy


def decode_record(dat_path: Path, header: dict, out_path: Path, chunk_frames: int = CHUNK_FRAMES) -> dict:
    window = pins.WINDOW_SAMPLES
    if chunk_frames % window:
        raise ValueError("chunk size must be a whole number of diagnostic windows")
    nsamp = int(header["nsamp"])
    if dat_path.stat().st_size != nsamp * 6:
        raise ValueError(f"{dat_path.name}: size {dat_path.stat().st_size} != nsamp*6 {nsamp * 6}")
    icp_signal = header["signals"][pins.ICP_INDEX]
    gain = float(icp_signal["gain"])
    baseline = int(icp_signal["baseline"])
    low_code = baseline + pins.VALUE_LOW_MMHG * gain
    high_code = baseline + pins.VALUE_HIGH_MMHG * gain
    window_high = baseline + pins.WINDOW_HIGH_MEDIAN_MMHG * gain
    window_very_high = baseline + pins.WINDOW_VERY_HIGH_MEDIAN_MMHG * gain
    window_low = baseline + pins.VALUE_LOW_MMHG * gain
    flat_p2p = pins.WINDOW_FLAT_P2P_MMHG * gain
    pulsatile_spread = pins.WINDOW_PULSATILE_SPREAD_MMHG * gain
    pegged_spread = pins.WINDOW_PEGGED_SPREAD_MMHG * gain

    histogram: collections.Counter = collections.Counter()
    sums = [0, 0, 0]
    source_digest = hashlib.sha256()
    out_digest = hashlib.sha256()
    classes = dict.fromkeys(pins.WINDOW_CLASSES, 0)
    windows = 0
    wrap_jumps = 0
    previous = None
    frames = 0
    first_frame = None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_suffix(".bin.tmp")
    with dat_path.open("rb") as source, temporary.open("wb") as sink:
        while True:
            buffer = source.read(chunk_frames * 6)
            if not buffer:
                break
            if len(buffer) % 6:
                raise ValueError(f"{dat_path.name}: partial frame")
            source_digest.update(buffer)
            words = array("h")
            words.frombytes(buffer)
            if sys.byteorder != "little":
                words.byteswap()
            if first_frame is None:
                first_frame = list(words[:3])
            for channel in range(3):
                sums[channel] += sum(words[channel::3])
            icp = words[pins.ICP_INDEX::3]
            histogram.update(icp)
            for start in range(0, len(icp), window):
                segment = icp[start:start + window]
                ordered = sorted(segment)
                size = len(ordered)
                median = ordered[size // 2]
                spread = ordered[size * 19 // 20] - ordered[size // 20]
                windows += 1
                if median < window_low:
                    label = "negative"
                elif median <= window_high:
                    if ordered[-1] - ordered[0] < flat_p2p:
                        label = "flat_icp_range"
                    else:
                        label = "plausible_icp" if has_waveform(segment) else "icp_range_noise"
                elif median > window_very_high:
                    label = "very_high"
                elif spread >= pulsatile_spread:
                    label = "high_pulsatile"
                elif spread < pegged_spread:
                    label = "high_flat"
                else:
                    label = "high_other"
                classes[label] += 1
                edge = previous is not None and (
                    abs(previous - ordered[0]) > pins.WRAP_JUMP_CODES or abs(previous - ordered[-1]) > pins.WRAP_JUMP_CODES
                )
                if edge or ordered[-1] - ordered[0] > pins.WRAP_JUMP_CODES:
                    lane = ([previous] if previous is not None else []) + list(segment)
                    wrap_jumps += sum(1 for left, right in zip(lane, lane[1:]) if abs(left - right) > pins.WRAP_JUMP_CODES)
                previous = segment[-1]
            frames += len(icp)
            if sys.byteorder != "little":
                icp.byteswap()
            encoded = icp.tobytes()
            sink.write(encoded)
            out_digest.update(encoded)
    if frames != nsamp:
        temporary.unlink()
        raise ValueError(f"{dat_path.name}: decoded {frames} frames != nsamp {nsamp}")
    for channel, signal in enumerate(header["signals"]):
        if (sums[channel] & 0xFFFF) != (int(signal["checksum"]) & 0xFFFF):
            temporary.unlink()
            raise ValueError(f"{dat_path.name}: WFDB checksum mismatch for {signal['name']}")
    distinct = len(histogram)
    minimum = min(histogram)
    maximum = max(histogram)
    invalid = histogram.get(-32768, 0)
    if distinct < 16 or minimum >= maximum or invalid * 2 > nsamp:
        temporary.unlink()
        raise ValueError(f"{dat_path.name}: degenerate ICP channel (distinct={distinct}, invalid={invalid})")
    temporary.replace(out_path)
    band_low, band_high = pins.unused_code_bounds(gain, baseline)
    band_codes = band_high - band_low + 1
    band_unused = sum(1 for code in range(band_low, band_high + 1) if code not in histogram)
    below = sum(count for value, count in histogram.items() if value < low_code)
    above = sum(count for value, count in histogram.items() if value > high_code)
    return {
        "source_sha256": source_digest.hexdigest(),
        "sha256": out_digest.hexdigest(),
        "value_count": frames,
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "invalid_sample_count": invalid,
        "stretch_vs_native": round(gain / pins.NATIVE_GAIN_PER_MMHG, 4),
        "unused_code_fraction_0_40mmhg": round(band_unused / band_codes, 3),
        "positive_rail_count": histogram.get(32767, 0),
        "negative_rail_count": histogram.get(-32767, 0),
        "wrap_like_jumps": wrap_jumps,
        "values_below_minus10_mmhg": below,
        "values_above_100_mmhg": above,
        "fraction_outside_minus10_100_mmhg": round((below + above) / frames, 6),
        "windows_60s": windows,
        **{f"windows_{name}": count for name, count in classes.items()},
        "fraction_windows_plausible_icp": round(classes["plausible_icp"] / windows, 6),
        "wfdb_checksums": [((total + 32768) & 0xFFFF) - 32768 for total in sums],
        "first_frame": first_frame,
    }


def selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="charis_build_selftest_") as tmp:
        root = Path(tmp)
        synthetic = charis_synth.make_record()
        dat = root / "synth1.dat"
        dat.write_bytes(synthetic["data"])
        header = parse_header(synthetic["header"], "synth1", synthetic["frames"])
        out = root / "out" / "synth1.bin"
        stats = decode_record(dat, header, out, chunk_frames=pins.WINDOW_SAMPLES)
        if out.read_bytes() != synthetic["icp_bytes"]:
            raise SystemExit("selftest: de-interleaved ICP bytes differ from synthetic truth")
        for key, value in synthetic["expected"].items():
            if stats[key] != value:
                raise SystemExit(f"selftest: {key}={stats[key]} expected {value}")
        if "SYNTH" in json.dumps(header) or "age" in json.dumps(header):
            raise SystemExit("selftest: header comments leaked into parsed header")

        def must_fail(label: str, header_text: str, data: bytes) -> None:
            bad = root / "synth1.dat"
            bad.write_bytes(data)
            try:
                parsed = parse_header(header_text, "synth1", synthetic["frames"])
                decode_record(bad, parsed, root / "bad" / "synth1.bin", chunk_frames=pins.WINDOW_SAMPLES)
            except ValueError:
                return
            raise SystemExit(f"selftest: {label} was not rejected")

        text = synthetic["header"]
        lines = text.split("\n")
        icp_fields = lines[3].split()
        icp_fields[6] = str(int(icp_fields[6]) ^ 1)
        must_fail("ICP checksum mismatch", "\n".join(lines[:3] + [" ".join(icp_fields)] + lines[4:]), synthetic["data"])
        must_fail("truncated .dat", text, synthetic["data"][:-6])
        must_fail("format 212", text.replace(".dat 16 ", ".dat 212 "), synthetic["data"])
        must_fail("swapped signal order", "\n".join([lines[0], lines[1], lines[3], lines[2]] + lines[4:]), synthetic["data"])
        must_fail("nsamp mismatch", text.replace(f" 50 {synthetic['frames']}", f" 50 {synthetic['frames'] + 1}", 1), synthetic["data"])
        flipped = bytearray(synthetic["data"])
        flipped[4 + 6 * 10] ^= 0x01
        must_fail("corrupted ICP sample", text, bytes(flipped))
    print("selftest ok: build decoder")


def build(download_dir: Path, samples_root: Path, index_path: Path, stats_path: Path, data_root: Path) -> None:
    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    by_record = {item["record_id"]: item for item in inventory["records"]}
    if set(by_record) != set(pins.KEPT_RECORDS):
        raise SystemExit("download inventory record set differs from the 11 kept records")
    if sorted(item["record_id"] for item in inventory.get("excluded_records", [])) != sorted(pins.EXCLUDED_RECORDS):
        raise SystemExit("download inventory exclusion list differs from pins")
    series_dir = samples_root / pins.SERIES_ID
    if series_dir.exists():
        for stale in list(series_dir.glob("*.bin")) + list(series_dir.glob("*.tmp")):
            stale.unlink()
    rows = []
    record_stats = []
    for pin in pins.kept_record_rows():
        record = pin["record_id"]
        item = by_record[record]
        hea = download_dir / f"{record}.hea"
        dat = download_dir / f"{record}.dat"
        if item["data_sha256"] != pin["dat_sha256"] or item["header_sha256"] != pin["hea_sha256"]:
            raise SystemExit(f"{record}: inventory checksum differs from pin")
        if hashlib.sha256(hea.read_bytes()).hexdigest() != pin["hea_sha256"]:
            raise SystemExit(f"{record}: header SHA-256 mismatch")
        header = parse_header(hea.read_text(encoding="ascii"), record, pin["nsamp"])
        icp = header["signals"][pins.ICP_INDEX]
        if (icp["gain_text"], icp["baseline"], icp["checksum"]) != (
            pin["icp_gain_text"], pin["icp_baseline"], pin["icp_header_checksum"]
        ):
            raise SystemExit(f"{record}: ICP calibration/checksum differs from pin")
        out = series_dir / f"{record}.bin"
        stats = decode_record(dat, header, out)
        if stats["source_sha256"] != pin["dat_sha256"]:
            out.unlink()
            raise SystemExit(f"{record}: .dat SHA-256 mismatch")
        row = {
            "dataset_id": pins.DATASET_ID,
            "series_id": pins.SERIES_ID,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": out.stat().st_size,
            "value_count": stats["value_count"],
            "role": "primary",
            "natural_record_kind": pins.NATURAL_RECORD_KIND,
            "record_id": record,
            "source_sample": dat.relative_to(data_root).as_posix(),
            "source_signal": "ICP",
            "source_signal_index": pins.ICP_INDEX,
            "sampling_frequency_hz": pins.SAMPLING_HZ,
            "adc_gain_per_mmhg": icp["gain"],
            "adc_baseline": icp["baseline"],
            "units": icp["units"],
            "wfdb_checksum": icp["checksum"],
        }
        for key in (
            "minimum", "maximum", "distinct_values", "invalid_sample_count", "positive_rail_count",
            "negative_rail_count", "wrap_like_jumps",
            "values_below_minus10_mmhg", "values_above_100_mmhg", "fraction_outside_minus10_100_mmhg",
            "windows_60s", *[f"windows_{name}" for name in pins.WINDOW_CLASSES],
            "fraction_windows_plausible_icp", "stretch_vs_native", "unused_code_fraction_0_40mmhg", "sha256",
        ):
            row[key] = stats[key]
        rows.append(row)
        record_stats.append({
            "record_id": record,
            "source_sha256": stats["source_sha256"],
            "wfdb_checksums_abp_ecg_icp": stats["wfdb_checksums"],
            "header_initial_values_abp_ecg_icp": [s["header_initial_value"] for s in header["signals"]],
            "first_frame_abp_ecg_icp": stats["first_frame"],
            "abp_gain_baseline": [header["signals"][0]["gain"], header["signals"][0]["baseline"]],
        })
        print(
            f"{record}: values={stats['value_count']} range={stats['minimum']}..{stats['maximum']} "
            f"distinct={stats['distinct_values']} outside[-10,100]mmHg={stats['fraction_outside_minus10_100_mmhg']:.4f} "
            f"windows={stats['windows_60s']} plausible={stats['fraction_windows_plausible_icp']:.3f} "
            + " ".join(f"{name}={stats['windows_' + name]}" for name in pins.WINDOW_CLASSES)
            + f" wraps={stats['wrap_like_jumps']} stretch={stats['stretch_vs_native']}"
            + f" unused0_40={stats['unused_code_fraction_0_40mmhg']}",
            flush=True,
        )
    finalize(rows, record_stats, index_path, stats_path)


def summarize(rows: list[dict], record_stats: list[dict]) -> dict:
    hashes = [row["sha256"] for row in rows]
    if len(set(hashes)) != len(hashes):
        raise SystemExit("duplicate ICP sample payloads")
    values = sum(row["value_count"] for row in rows)
    size = sum(row["sample_size_bytes"] for row in rows)
    if values != pins.EXPECTED_PRIMARY_VALUES or size != pins.EXPECTED_PRIMARY_BYTES:
        raise SystemExit(f"aggregate values/bytes changed: {values}/{size}")
    counts = sorted(row["value_count"] for row in rows)
    if counts[len(counts) // 2] != pins.EXPECTED_MEDIAN_VALUES:
        raise SystemExit("median sample length changed")
    for row in rows:
        if row["fraction_windows_plausible_icp"] < pins.MIN_KEPT_PLAUSIBLE_FRACTION:
            raise SystemExit(f"{row['record_id']}: kept record is majority non-ICP")
    windows = sum(row["windows_60s"] for row in rows)
    outside = sum(row["values_below_minus10_mmhg"] + row["values_above_100_mmhg"] for row in rows)
    return {
        "dataset_id": pins.DATASET_ID,
        "series_id": pins.SERIES_ID,
        "samples": len(rows),
        "kept_records": [row["record_id"] for row in rows],
        "excluded_records": dict(sorted(pins.EXCLUDED_RECORDS.items())),
        "native_gain_per_mmhg": pins.NATIVE_GAIN_PER_MMHG,
        "primary_values": values,
        "primary_bytes": size,
        "median_sample_values": counts[len(counts) // 2],
        "sampling_frequency_hz": pins.SAMPLING_HZ,
        "diagnostic_window_samples": pins.WINDOW_SAMPLES,
        "fraction_outside_minus10_100_mmhg": round(outside / values, 6),
        "windows_60s": windows,
        "fraction_windows_plausible_icp": round(sum(row["windows_plausible_icp"] for row in rows) / windows, 6),
        "fraction_windows_by_class": {
            name: round(sum(row[f"windows_{name}"] for row in rows) / windows, 6) for name in pins.WINDOW_CLASSES
        },
        "invalid_sample_count": sum(row["invalid_sample_count"] for row in rows),
        "wrap_like_jumps": sum(row["wrap_like_jumps"] for row in rows),
        "aggregate_sample_sha256": hashlib.sha256("\n".join(f"{row['record_id']}:{row['sha256']}" for row in rows).encode()).hexdigest(),
        "records": record_stats,
    }


def finalize(rows: list[dict], record_stats: list[dict], index_path: Path, stats_path: Path) -> None:
    summary = summarize(rows, record_stats)
    for path, text in (
        (index_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)),
        (stats_path, json.dumps(summary, indent=2, sort_keys=True) + "\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    print(
        f"build ok: samples={summary['samples']} values={summary['primary_values']} bytes={summary['primary_bytes']} "
        f"median={summary['median_sample_values']} outside[-10,100]={summary['fraction_outside_minus10_100_mmhg']} "
        f"plausible_windows={summary['fraction_windows_plausible_icp']} aggregate_sha256={summary['aggregate_sample_sha256']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest-only", action="store_true")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--samples-root", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    selftest()
    if args.selftest_only:
        return
    build(args.download_dir, args.samples_root, args.index, args.stats, args.data_root)


if __name__ == "__main__":
    main()
