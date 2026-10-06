#!/usr/bin/env python3
"""Verify: independently re-derive every CHARIS ICP sample and its index row.

Independent of charis_build.py: headers are parsed with a regex tokenizer,
the ICP channel is de-interleaved at byte level (bytes 4 and 5 of every
6-byte frame), integers are decoded with struct '<h', and diagnostics are
recomputed with bisect counts on sorted windows. Checks source SHA-256
against SHA256SUMS.txt, the WFDB checksums of all three signals, sample
bytes, index rows, ingest stats, manifest totals, stray files, and that no
header comment text leaked into outputs. Same missing-value policy as build:
every value kept, nothing clipped or imputed; degenerate channels fail.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import tempfile
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charis_pins as pins  # noqa: E402
import charis_synth  # noqa: E402

RECORD_LINE = re.compile(r"^(?P<name>\S+) (?P<nsig>\d+) (?P<fs>\d+) (?P<nsamp>\d+)$")
SIGNAL_LINE = re.compile(
    r"^(?P<file>\S+) 16 (?P<gain>\d+(?:\.\d+)?)\((?P<base>-?\d+)\)/(?P<units>\S+) 0 0 (?P<init>-?\d+) (?P<checksum>-?\d+) 0 (?P<desc>\S+)$"
)
CHUNK_FRAMES = pins.WINDOW_SAMPLES * 100
# Majority non-ICP records; must match charis_pins.EXCLUDED_RECORDS.
EXCLUDED = ("charis8", "charis9", "charis10", "charis12")
KEPT = tuple(f"charis{n}" for n in range(1, 14) if f"charis{n}" not in EXCLUDED)
# Demographic and outcome header fields must never reach the outputs. (charis9's
# signal-quality note is quoted on purpose in the pinned exclusion reason.)
LEAK_MARKERS = ("<age>", "<sex>", "<diagnoses>", "<outcome>", "Rehab", "Expired", "SAH/", "TBI)")


def parse_header(text: str, record_id: str) -> dict:
    content = [raw.strip() for raw in text.replace("\r", "").split("\n")]
    content = [raw for raw in content if raw and raw[0] != "#"]
    record = RECORD_LINE.match(content[0]) if content else None
    if not record or record["name"] != record_id or record["nsig"] != "3" or record["fs"] != "50":
        raise ValueError(f"{record_id}: bad record line")
    if len(content) != 4:
        raise ValueError(f"{record_id}: bad signal count")
    signals = []
    for position, raw in enumerate(content[1:]):
        match = SIGNAL_LINE.match(raw)
        if not match or match["file"] != record_id + ".dat" or match["desc"] != ("ABP", "ECG", "ICP")[position]:
            raise ValueError(f"{record_id}: bad signal line {position}")
        signals.append(match.groupdict())
    if signals[2]["units"] != "mmHg":
        raise ValueError(f"{record_id}: ICP units")
    return {"nsamp": int(record["nsamp"]), "signals": signals}


def rederive(dat_path: Path, sample_path: Path, header: dict, chunk_frames: int = CHUNK_FRAMES) -> dict:
    window = pins.WINDOW_SAMPLES
    nsamp = header["nsamp"]
    if dat_path.stat().st_size != nsamp * 6:
        raise ValueError(f"{dat_path.name}: size is not nsamp*6")
    if sample_path.stat().st_size != nsamp * 2:
        raise ValueError(f"{sample_path.name}: size is not nsamp*2")
    icp_header = header["signals"][2]
    gain = float(icp_header["gain"])
    baseline = int(icp_header["base"])
    low_code = baseline + pins.VALUE_LOW_MMHG * gain
    high_code = baseline + pins.VALUE_HIGH_MMHG * gain
    thresholds = {
        "low": baseline + pins.VALUE_LOW_MMHG * gain,
        "high": baseline + pins.WINDOW_HIGH_MEDIAN_MMHG * gain,
        "very_high": baseline + pins.WINDOW_VERY_HIGH_MEDIAN_MMHG * gain,
        "flat": pins.WINDOW_FLAT_P2P_MMHG * gain,
        "pulsatile": pins.WINDOW_PULSATILE_SPREAD_MMHG * gain,
        "pegged": pins.WINDOW_PEGGED_SPREAD_MMHG * gain,
    }
    totals = [0, 0, 0]
    seen: set[int] = set()
    minimum, maximum = 32768, -32769
    below = above = invalid = rail = negative_rail = 0
    windows = 0
    tally = {name: 0 for name in pins.WINDOW_CLASSES}
    jumps = 0
    carry: tuple[int, ...] = ()
    frames = 0
    src_digest = hashlib.sha256()
    out_digest = hashlib.sha256()
    with dat_path.open("rb") as source, sample_path.open("rb") as sample:
        while True:
            chunk = source.read(chunk_frames * 6)
            if not chunk:
                break
            src_digest.update(chunk)
            count = len(chunk) // 6
            if count * 6 != len(chunk):
                raise ValueError("partial frame")
            icp_bytes = bytearray(count * 2)
            icp_bytes[0::2] = chunk[4::6]
            icp_bytes[1::2] = chunk[5::6]
            emitted = sample.read(count * 2)
            if emitted != icp_bytes:
                raise ValueError(f"{sample_path.name}: emitted bytes differ from source ICP channel near frame {frames}")
            out_digest.update(emitted)
            for channel in range(3):
                lane = bytearray(count * 2)
                lane[0::2] = chunk[2 * channel::6]
                lane[1::2] = chunk[2 * channel + 1::6]
                values = struct.unpack(f"<{count}h", lane)
                totals[channel] += sum(values)
                if channel != 2:
                    continue
                seen.update(values)
                for start in range(0, count, window):
                    piece = values[start:start + window]
                    ordered = sorted(piece)
                    size = len(ordered)
                    minimum = min(minimum, ordered[0])
                    maximum = max(maximum, ordered[-1])
                    below += bisect_left(ordered, low_code)
                    above += size - bisect_right(ordered, high_code)
                    invalid += bisect_right(ordered, -32768) - bisect_left(ordered, -32768)
                    rail += bisect_right(ordered, 32767) - bisect_left(ordered, 32767)
                    negative_rail += bisect_right(ordered, -32767) - bisect_left(ordered, -32767)
                    tally[classify(ordered, piece, thresholds)] += 1
                    windows += 1
                    span = carry + piece
                    if max(span) - min(span) > pins.WRAP_JUMP_CODES:
                        jumps += sum(1 for k in range(1, len(span)) if abs(span[k] - span[k - 1]) > pins.WRAP_JUMP_CODES)
                    carry = piece[-1:]
            frames += count
        if sample.read(1):
            raise ValueError(f"{sample_path.name}: trailing bytes")
    if frames != nsamp:
        raise ValueError("frame count mismatch")
    for channel in range(3):
        expected = int(header["signals"][channel]["checksum"])
        if ((totals[channel] + 32768) % 65536) - 32768 != expected:
            raise ValueError(f"{dat_path.name}: WFDB checksum mismatch on signal {channel}")
    if len(seen) < 16 or minimum >= maximum or invalid * 2 > nsamp:
        raise ValueError(f"{sample_path.name}: degenerate ICP channel")
    band_top = int(math.floor(baseline + pins.UNUSED_CODE_BAND_MMHG * gain))
    band_size = band_top - baseline + 1
    band_missing = band_size - len(seen.intersection(range(baseline, band_top + 1)))
    return {
        "source_sha256": src_digest.hexdigest(),
        "sha256": out_digest.hexdigest(),
        "value_count": frames,
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": len(seen),
        "invalid_sample_count": invalid,
        "positive_rail_count": rail,
        "negative_rail_count": negative_rail,
        "wrap_like_jumps": jumps,
        "stretch_vs_native": round(gain / pins.NATIVE_GAIN_PER_MMHG, 4),
        "unused_code_fraction_0_40mmhg": round(band_missing / band_size, 3),
        "values_below_minus10_mmhg": below,
        "values_above_100_mmhg": above,
        "fraction_outside_minus10_100_mmhg": round((below + above) / frames, 6),
        "windows_60s": windows,
        **{"windows_" + name: tally[name] for name in pins.WINDOW_CLASSES},
        "fraction_windows_plausible_icp": round(tally["plausible_icp"] / windows, 6),
    }


def waveform_present(piece: tuple[int, ...]) -> bool:
    """Lag-1 autocorrelation >= 0.5, exact: 2*sum(y_i*y_(i+1)) >= sum(y_i^2), y_i = n*x_i - sum(x)."""
    count = len(piece)
    level = sum(piece)
    deviations = [count * value - level for value in piece]
    neighbours = 0
    for k in range(count - 1):
        neighbours += deviations[k] * deviations[k + 1]
    power = sum(value * value for value in deviations)
    return 2 * neighbours >= power


def classify(ordered: list[int], piece: tuple[int, ...], limits: dict[str, float]) -> str:
    """Mutually exclusive 60 s window class (see charis_pins.py)."""
    size = len(ordered)
    middle = ordered[size // 2]
    if middle < limits["low"]:
        return "negative"
    if not middle > limits["high"]:
        if ordered[-1] - ordered[0] < limits["flat"]:
            return "flat_icp_range"
        return "plausible_icp" if waveform_present(piece) else "icp_range_noise"
    if middle > limits["very_high"]:
        return "very_high"
    spread = ordered[(size * 19) // 20] - ordered[size // 20]
    if spread >= limits["pulsatile"]:
        return "high_pulsatile"
    return "high_flat" if spread < limits["pegged"] else "high_other"


def selftest() -> None:
    synthetic = charis_synth.make_record()
    with tempfile.TemporaryDirectory(prefix="charis_verify_selftest_") as tmp:
        root = Path(tmp)
        dat, out = root / "synth1.dat", root / "synth1.bin"
        dat.write_bytes(synthetic["data"])
        out.write_bytes(synthetic["icp_bytes"])
        header = parse_header(synthetic["header"], "synth1")
        stats = rederive(dat, out, header, chunk_frames=pins.WINDOW_SAMPLES)
        for key, value in synthetic["expected"].items():
            if stats[key] != value:
                raise SystemExit(f"verify selftest: {key}={stats[key]} expected {value}")
        tampered = bytearray(synthetic["icp_bytes"])
        tampered[200] ^= 0x10
        out.write_bytes(bytes(tampered))
        try:
            rederive(dat, out, header, chunk_frames=pins.WINDOW_SAMPLES)
        except ValueError:
            pass
        else:
            raise SystemExit("verify selftest: tampered sample not rejected")
        out.write_bytes(synthetic["icp_bytes"])
        bad_header = synthetic["header"].replace(" 0 ICP", " 0 ABP")
        try:
            rederive(dat, out, parse_header(bad_header, "synth1"), chunk_frames=pins.WINDOW_SAMPLES)
        except ValueError:
            pass
        else:
            raise SystemExit("verify selftest: wrong signal label not rejected")
        lines = synthetic["header"].split("\n")
        fields = lines[1].split()
        fields[6] = str(int(fields[6]) + 1)
        try:
            rederive(dat, out, parse_header("\n".join([lines[0], " ".join(fields)] + lines[2:]), "synth1"),
                     chunk_frames=pins.WINDOW_SAMPLES)
        except ValueError:
            pass
        else:
            raise SystemExit("verify selftest: ABP checksum mismatch not rejected")
    print("selftest ok: verify decoder")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 << 20):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest-only", action="store_true")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--samples-root", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    selftest()
    if args.selftest_only:
        return

    official = {}
    for line in (args.download_dir / "SHA256SUMS.txt").read_text(encoding="ascii").split("\n"):
        parts = line.split()
        if len(parts) == 2:
            official[parts[1]] = parts[0]
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").split("\n") if line.strip()]
    stats_doc = json.loads(args.stats.read_text(encoding="utf-8"))
    if set(EXCLUDED) != set(pins.EXCLUDED_RECORDS) or KEPT != pins.KEPT_RECORDS:
        raise SystemExit("exclusion list differs between verify and pins")
    expected_ids = list(KEPT)
    if [row.get("record_id") for row in rows] != expected_ids:
        raise SystemExit("index rows are not the 11 kept records in canonical order")
    if [item.get("record_id") for item in stats_doc["records"]] != expected_ids:
        raise SystemExit("ingest stats records are not the 11 kept records in canonical order")
    if stats_doc.get("kept_records") != expected_ids or sorted(stats_doc.get("excluded_records", {})) != sorted(EXCLUDED):
        raise SystemExit("ingest stats kept/excluded lists differ")
    for text in (args.index.read_text(encoding="utf-8"), args.stats.read_text(encoding="utf-8")):
        for marker in LEAK_MARKERS:
            if marker in text:
                raise SystemExit(f"header comment text leaked into outputs: {marker!r}")

    series_dir = args.samples_root / pins.SERIES_ID
    total_values = total_bytes = 0
    outside = plausible_windows = all_windows = all_jumps = 0
    class_totals = {name: 0 for name in pins.WINDOW_CLASSES}
    for row, stat_item in zip(rows, stats_doc["records"]):
        record = row["record_id"]
        hea = args.download_dir / f"{record}.hea"
        dat = args.download_dir / f"{record}.dat"
        if sha256_file(hea) != official[hea.name]:
            raise SystemExit(f"{hea.name}: SHA-256 differs from SHA256SUMS.txt")
        header = parse_header(hea.read_text(encoding="ascii"), record)
        sample = args.data_root / row["sample_path"]
        if sample.parent.resolve() != series_dir.resolve() or sample.name != f"{record}.bin":
            raise SystemExit(f"{record}: unexpected sample path {row['sample_path']}")
        result = rederive(dat, sample, header)
        if result["source_sha256"] != official[dat.name]:
            raise SystemExit(f"{dat.name}: SHA-256 differs from SHA256SUMS.txt")
        if stat_item["source_sha256"] != result["source_sha256"]:
            raise SystemExit(f"{record}: ingest stats source hash differs")
        icp = header["signals"][2]
        expected_row = {
            "dataset_id": pins.DATASET_ID,
            "series_id": pins.SERIES_ID,
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": result["value_count"] * 2,
            "role": "primary",
            "natural_record_kind": pins.NATURAL_RECORD_KIND,
            "source_signal": "ICP",
            "source_signal_index": 2,
            "sampling_frequency_hz": 50,
            "adc_gain_per_mmhg": float(icp["gain"]),
            "adc_baseline": int(icp["base"]),
            "units": "mmHg",
            "wfdb_checksum": int(icp["checksum"]),
            "source_sample": dat.relative_to(args.data_root).as_posix(),
        }
        expected_row.update({key: value for key, value in result.items() if key != "source_sha256"})
        for key, value in expected_row.items():
            if row.get(key) != value:
                raise SystemExit(f"{record}: index field {key}={row.get(key)!r} but re-derived {value!r}")
        total_values += result["value_count"]
        total_bytes += result["value_count"] * 2
        outside += result["values_below_minus10_mmhg"] + result["values_above_100_mmhg"]
        plausible_windows += result["windows_plausible_icp"]
        all_windows += result["windows_60s"]
        all_jumps += result["wrap_like_jumps"]
        for name in pins.WINDOW_CLASSES:
            class_totals[name] += result["windows_" + name]
        if result["fraction_windows_plausible_icp"] < 0.5:
            raise SystemExit(f"{record}: kept record has fewer than half plausible-ICP windows")
        print(
            f"verified {record}: values={result['value_count']} distinct={result['distinct_values']} "
            f"outside[-10,100]={result['fraction_outside_minus10_100_mmhg']} plausible_windows={result['fraction_windows_plausible_icp']} "
            f"stretch={result['stretch_vs_native']} unused0_40={result['unused_code_fraction_0_40mmhg']}",
            flush=True,
        )

    for record in EXCLUDED:
        if (series_dir / f"{record}.bin").exists():
            raise SystemExit(f"excluded record {record} has a sample file")
    actual_files = sorted(path.name for path in series_dir.iterdir())
    if actual_files != sorted(f"{record}.bin" for record in expected_ids):
        raise SystemExit(f"stray or missing files in {series_dir}: {actual_files}")
    if total_values != pins.EXPECTED_PRIMARY_VALUES or total_bytes != pins.EXPECTED_PRIMARY_BYTES:
        raise SystemExit("aggregate primary values/bytes differ from pins")
    checks = {
        "samples": len(KEPT),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_sample_values": sorted(row["value_count"] for row in rows)[len(rows) // 2],
        "fraction_outside_minus10_100_mmhg": round(outside / total_values, 6),
        "fraction_windows_plausible_icp": round(plausible_windows / all_windows, 6),
        "windows_60s": all_windows,
        "wrap_like_jumps": all_jumps,
        "fraction_windows_by_class": {name: round(class_totals[name] / all_windows, 6) for name in pins.WINDOW_CLASSES},
        "aggregate_sample_sha256": hashlib.sha256(
            "\n".join(f"{row['record_id']}:{row['sha256']}" for row in rows).encode()
        ).hexdigest(),
    }
    for key, value in checks.items():
        if stats_doc.get(key) != value:
            raise SystemExit(f"ingest stats {key}={stats_doc.get(key)!r} but re-derived {value!r}")
    if len({row["sha256"] for row in rows}) != len(KEPT):
        raise SystemExit("duplicate sample payloads")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [item for item in manifest.get("series", []) if item.get("id") == pins.SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        raise SystemExit("manifest must declare exactly one primary series " + pins.SERIES_ID)
    if series[0].get("sample_count") != len(KEPT) or series[0].get("total_size_bytes") != total_bytes:
        raise SystemExit("manifest sample_count/total_size_bytes differ from realized output")
    print(
        f"verify ok: samples={len(KEPT)} values={total_values} bytes={total_bytes} "
        f"outside[-10,100]={checks['fraction_outside_minus10_100_mmhg']} "
        f"plausible_windows={checks['fraction_windows_plausible_icp']} aggregate_sha256={checks['aggregate_sample_sha256']}"
    )


if __name__ == "__main__":
    main()
