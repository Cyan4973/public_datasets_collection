#!/usr/bin/env python3
"""Build the TPEHG DB unfiltered EHG int16 samples from local files only.

For each of the 300 official records: re-check the source SHA-256 values from
download_inventory.json, parse the WFDB header, check the initial value and the
16-bit checksum of all 12 interleaved signals, then write the three unfiltered
bipolar channels (signal indices 0, 4, 8; names '1', '2', '3') as one
little-endian int16 sample each. The nine digitally filtered DOCFILT signals
and every header comment (clinical fields) are discarded.

Records are routed to one of two primary series by ADC code lattice, which
coincides with the header sampling-frequency string: '20.000000' -> full
16-bit codes (step1 series), '20.000110' -> codes on two adjacent residues
mod 16 (step16 series). Each kept channel must satisfy its series' lattice
assertion, so neither series mixes regimes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from array import array
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tpehg_common import (  # noqa: E402
    BIPOLAR_LEADS,
    BYTES_PER_FRAME,
    DATASET_ID,
    EXPECTED_DAT_BYTES,
    EXPECTED_PRIMARY_BYTES,
    EXPECTED_PRIMARY_VALUES,
    EXPECTED_RECORDS,
    EXPECTED_SAMPLES,
    EXPECTED_TOTAL_FRAMES,
    NATURAL_RECORD_KIND,
    PRIMARY_SIGNALS,
    SERIES_BY_FREQUENCY,
    SIGNAL_COUNT,
    lattice_ok,
    mod16_profile,
    parse_header,
    sha256_file,
)

MIN_DISTINCT = 32
MIN_TRANSITION_FRACTION = 0.05
MAX_SATURATED_FRACTION = 0.5


def longest_run(values: array) -> int:
    best = run = 1
    for left, right in zip(values, values[1:]):
        run = run + 1 if left == right else 1
        if run > best:
            best = run
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data_root: Path = args.data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"

    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    records = inventory["records"]
    if len(records) != EXPECTED_RECORDS or int(inventory["data_bytes"]) != EXPECTED_DAT_BYTES:
        raise SystemExit("download inventory does not match the pinned scope; re-run download.sh")

    if samples_root.exists():
        for stale in samples_root.glob("*/*.bin"):
            stale.unlink()
        for directory in samples_root.iterdir():
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    for config in SERIES_BY_FREQUENCY.values():
        (samples_root / str(config["series_id"])).mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    records_per_series: dict[str, int] = {}
    total_frames = 0
    for record in records:
        record_id = str(record["record_id"])
        header_path = download_dir / str(record["header_file"])
        data_path = download_dir / str(record["data_file"])
        for path, key in ((header_path, "header_sha256"), (data_path, "data_sha256")):
            if sha256_file(path) != record[key]:
                raise SystemExit(f"{path.name}: sha256 differs from download inventory")
        header = parse_header(header_path, record_id)
        frames = int(header["frames"])
        raw = data_path.read_bytes()
        if len(raw) != frames * BYTES_PER_FRAME:
            raise SystemExit(f"{record_id}: data size does not match header frame count")
        words = array("h")
        words.frombytes(raw)
        if sys.byteorder != "little":
            words.byteswap()
        for signal in header["signals"]:
            channel = words[int(signal["index"])::SIGNAL_COUNT]
            if len(channel) != frames:
                raise SystemExit(f"{record_id}: signal {signal['index']} length mismatch")
            if channel[0] != int(signal["initial_value"]):
                raise SystemExit(f"{record_id}: signal {signal['index']} initial value mismatch")
            if (sum(channel) - int(signal["checksum"])) & 0xFFFF:
                raise SystemExit(f"{record_id}: signal {signal['index']} WFDB checksum mismatch")
        total_frames += frames
        frequency = str(header["frequency"])
        config = SERIES_BY_FREQUENCY[frequency]
        series_id = str(config["series_id"])
        lattice = str(config["lattice"])
        records_per_series[series_id] = records_per_series.get(series_id, 0) + 1

        for signal_index, channel_name in PRIMARY_SIGNALS.items():
            if header["signals"][signal_index]["name"] != channel_name:
                raise SystemExit(f"{record_id}: signal {signal_index} is not channel {channel_name}")
            values = words[signal_index::SIGNAL_COUNT]
            encoded_array = array("h", values)
            if sys.byteorder != "little":
                encoded_array.byteswap()
            encoded = encoded_array.tobytes()
            count = len(values)
            minimum = min(values)
            maximum = max(values)
            distinct = len(set(values))
            transitions = sum(1 for left, right in zip(values, values[1:]) if left != right)
            low = values.count(-32768)
            high = values.count(32767)
            profile = mod16_profile(values)
            if not lattice_ok(lattice, profile):
                raise SystemExit(f"{record_id} channel {channel_name}: code lattice {profile} is not {lattice}")
            if (
                minimum >= maximum
                or distinct < MIN_DISTINCT
                or transitions < MIN_TRANSITION_FRACTION * count
                or (low + high) > MAX_SATURATED_FRACTION * count
            ):
                raise SystemExit(f"{record_id} channel {channel_name}: degenerate waveform")
            output = samples_root / series_id / f"{record_id}_ch{channel_name}.bin"
            output.write_bytes(encoded)
            rows.append({
                "adc_code_lattice": lattice,
                "adc_gain_per_mv": 13107,
                "adc_resolution_bits": 16,
                "adc_zero": 0,
                "bipolar_lead": BIPOLAR_LEADS[channel_name],
                "bit_width": 16,
                "channel": channel_name,
                "dataset_id": DATASET_ID,
                "distinct_values": distinct,
                "element_size_bytes": 2,
                "endianness": "little",
                "longest_constant_run": longest_run(values),
                "maximum": maximum,
                "minimum": minimum,
                "mod16_residue_count": profile[0],
                "mod16_top2_fraction": profile[2],
                "natural_record_kind": NATURAL_RECORD_KIND,
                "numeric_kind": "int",
                "record_id": record_id,
                "role": "primary",
                "sample_axes": ["time_sample"],
                "sample_path": output.relative_to(data_root).as_posix(),
                "sample_rank": 1,
                "sample_shape": [count],
                "sample_size_bytes": len(encoded),
                "sampling_frequency_header": frequency,
                "saturated_high_count": high,
                "saturated_low_count": low,
                "series_id": series_id,
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "source_sample": data_path.relative_to(data_root).as_posix(),
                "source_signal_index": signal_index,
                "transition_count": transitions,
                "value_count": count,
            })

    if total_frames != EXPECTED_TOTAL_FRAMES:
        raise SystemExit(f"total frames {total_frames} != {EXPECTED_TOTAL_FRAMES}")
    if len(rows) != EXPECTED_SAMPLES:
        raise SystemExit(f"sample count {len(rows)} != {EXPECTED_SAMPLES}")
    hashes = [str(row["sha256"]) for row in rows]
    if len(set(hashes)) != len(hashes):
        raise SystemExit("duplicate primary samples")
    primary_values = sum(int(row["value_count"]) for row in rows)
    primary_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    if primary_values != EXPECTED_PRIMARY_VALUES or primary_bytes != EXPECTED_PRIMARY_BYTES:
        raise SystemExit(f"primary totals changed: values={primary_values} bytes={primary_bytes}")

    per_series = {}
    for config in SERIES_BY_FREQUENCY.values():
        series_id = str(config["series_id"])
        series_rows = [row for row in rows if row["series_id"] == series_id]
        values = sum(int(row["value_count"]) for row in series_rows)
        if records_per_series.get(series_id) != config["records"] or values != config["values"]:
            raise SystemExit(f"{series_id}: records={records_per_series.get(series_id)} values={values} changed")
        counts = sorted(int(row["value_count"]) for row in series_rows)
        per_series[series_id] = {
            "adc_code_lattice": config["lattice"],
            "records": records_per_series[series_id],
            "samples": len(series_rows),
            "values": values,
            "bytes": 2 * values,
            "value_count_min": counts[0],
            "value_count_median": counts[len(counts) // 2],
            "value_count_max": counts[-1],
            "global_minimum": min(int(row["minimum"]) for row in series_rows),
            "global_maximum": max(int(row["maximum"]) for row in series_rows),
            "min_distinct_values": min(int(row["distinct_values"]) for row in series_rows),
            "max_longest_constant_run": max(int(row["longest_constant_run"]) for row in series_rows),
            "mod16_top2_fraction_range": [
                min(float(row["mod16_top2_fraction"]) for row in series_rows),
                max(float(row["mod16_top2_fraction"]) for row in series_rows),
            ],
            "saturated_low_values": sum(int(row["saturated_low_count"]) for row in series_rows),
            "saturated_high_values": sum(int(row["saturated_high_count"]) for row in series_rows),
        }

    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tmp.replace(index_path)

    stats = {
        "dataset_id": DATASET_ID,
        "records": len(records),
        "samples": len(rows),
        "primary_values": primary_values,
        "primary_bytes": primary_bytes,
        "source_data_bytes": EXPECTED_DAT_BYTES,
        "total_frames": total_frames,
        "series": per_series,
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
