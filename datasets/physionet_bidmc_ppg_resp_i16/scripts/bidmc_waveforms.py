#!/usr/bin/env python3
"""Extract and independently verify native int16 BIDMC PLETH/RESP waveforms."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import re
import sys


DATASET_ID = "physionet_bidmc_ppg_resp_i16"
EXPECTED_RECORDS = 53
EXPECTED_FRAMES = 60_001
EXPECTED_FREQUENCY = 125.0
EXPECTED_SOURCE_BYTES = 34_200_570
EXPECTED_PRIMARY_VALUES = 6_360_106
EXPECTED_PRIMARY_BYTES = 12_720_212
CHANNELS = {
    "PLETH": {
        "series_id": "bidmc_pleth_adc_i16",
        "semantic_field": "photoplethysmographic_optical_pulse_adc",
    },
    "RESP": {
        "series_id": "bidmc_respiration_adc_i16",
        "semantic_field": "respiratory_waveform_adc",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_inventory(download_dir: Path) -> list[dict[str, object]]:
    payload = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_RECORDS:
        raise SystemExit("download inventory record count changed")
    if int(payload.get("source_bytes", 0)) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("download inventory aggregate waveform size changed")
    expected_ids = [f"bidmc{index:02d}" for index in range(1, EXPECTED_RECORDS + 1)]
    if [str(record.get("record_id")) for record in records] != expected_ids:
        raise SystemExit("download inventory identities or order changed")
    for record in records:
        for kind in ("header", "data"):
            path = download_dir / str(record[f"{kind}_file"])
            if path.name != str(record[f"{kind}_file"]):
                raise SystemExit("unsafe source filename in download inventory")
            if path.stat().st_size != int(record[f"{kind}_bytes"]):
                raise SystemExit(f"source size mismatch: {path.name}")
            if sha256_file(path) != str(record[f"{kind}_sha256"]):
                raise SystemExit(f"source SHA256 mismatch: {path.name}")
    return records


def parse_header(path: Path, record_id: str) -> dict[str, object]:
    text = path.read_text(encoding="ascii")
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    first = lines[0].split()
    if len(first) < 4 or first[0] != record_id:
        raise ValueError("unexpected WFDB record identity")
    signal_count = int(first[1])
    frequency = float(first[2].split("/", 1)[0])
    frames = int(first[3])
    if frequency != EXPECTED_FREQUENCY or frames != EXPECTED_FRAMES:
        raise ValueError("WFDB frequency or frame count changed")
    if signal_count not in {5, 6, 7} or len(lines) != signal_count + 1:
        raise ValueError("unexpected WFDB signal geometry")
    signals = []
    for index, line in enumerate(lines[1:]):
        fields = line.split()
        if len(fields) < 9:
            raise ValueError("short WFDB signal line")
        format_match = re.fullmatch(r"(\d+)(?:x(\d+))?(?::(\d+))?(?:\+(\d+))?", fields[1])
        if not format_match:
            raise ValueError(f"unsupported WFDB format token: {fields[1]}")
        signal = {
            "index": index,
            "filename": fields[0],
            "format": int(format_match.group(1)),
            "samples_per_frame": int(format_match.group(2) or "1"),
            "skew": int(format_match.group(3) or "0"),
            "byte_offset": int(format_match.group(4) or "0"),
            "initial_value": int(fields[5]),
            "checksum": int(fields[6]),
            "description": " ".join(fields[8:]),
        }
        if (
            signal["format"] != 16
            or signal["samples_per_frame"] != 1
            or signal["skew"] != 0
            or signal["byte_offset"] != 0
        ):
            raise ValueError("record is not ordinary interleaved WFDB format 16")
        signals.append(signal)
    filenames = {str(signal["filename"]) for signal in signals}
    if filenames != {f"{record_id}.dat"}:
        raise ValueError("unexpected WFDB data filename")
    selected: dict[str, dict[str, object]] = {}
    for name in CHANNELS:
        matches = [
            signal for signal in signals
            if re.search(
                rf"(?<![A-Z0-9]){re.escape(name)}(?![A-Z0-9])",
                str(signal["description"]).upper(),
            )
        ]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {name} signal")
        selected[name] = matches[0]
    return {
        "frames": frames,
        "frequency": frequency,
        "selected": selected,
        "signal_count": signal_count,
        "signals": signals,
    }


def canonical_bytes(values: array) -> bytes:
    encoded = array("h", values)
    if sys.byteorder != "little":
        encoded.byteswap()
    return encoded.tobytes()


def decode_record(
    *,
    record: dict[str, object],
    download_dir: Path,
    samples_root: Path,
    data_root: Path,
    mode: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    record_id = str(record["record_id"])
    header = parse_header(download_dir / str(record["header_file"]), record_id)
    source = download_dir / str(record["data_file"])
    expected_bytes = int(header["frames"]) * int(header["signal_count"]) * 2
    if source.stat().st_size != expected_bytes:
        raise ValueError(f"interleaved data size mismatch for {record_id}")
    words = array("h")
    words.frombytes(source.read_bytes())
    if sys.byteorder != "little":
        words.byteswap()
    signal_count = int(header["signal_count"])
    for signal in header["signals"]:
        channel = words[int(signal["index"])::signal_count]
        if len(channel) != int(header["frames"]):
            raise ValueError(f"channel length mismatch for {record_id}")
        if channel[0] != int(signal["initial_value"]):
            raise ValueError(f"WFDB initial value mismatch for {record_id}")
        if sum(channel) & 0xFFFF != int(signal["checksum"]) & 0xFFFF:
            raise ValueError(f"WFDB checksum mismatch for {record_id}")

    entries: list[dict[str, object]] = []
    channel_stats: dict[str, object] = {}
    for name, channel_config in CHANNELS.items():
        signal = header["selected"][name]
        values = words[int(signal["index"])::signal_count]
        encoded = canonical_bytes(values)
        digest = hashlib.sha256(encoded).hexdigest()
        minimum = min(values)
        maximum = max(values)
        transitions = sum(left != right for left, right in zip(values, values[1:]))
        distinct = len(set(values))
        if minimum >= maximum or transitions == 0 or distinct < 3:
            raise ValueError(f"degenerate selected waveform {record_id} {name}")
        series_id = str(channel_config["series_id"])
        output = samples_root / series_id / f"{record_id}_{name.lower()}.bin"
        if mode == "build":
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(encoded)
        elif output.read_bytes() != encoded:
            raise ValueError(f"built sample differs from source decode: {output.name}")
        entries.append({
            "bit_width": 16,
            "dataset_id": DATASET_ID,
            "distinct_values": distinct,
            "element_size_bytes": 2,
            "endianness": "little",
            "maximum": maximum,
            "minimum": minimum,
            "natural_record_kind": "complete_bidmc_eight_minute_waveform_channel",
            "numeric_kind": "int",
            "record_id": record_id,
            "role": "primary",
            "sample_axes": ["time_sample"],
            "sample_format": "raw homogeneous little-endian signed-int16 ADC sequence",
            "sample_geometry": "fixed_length_clinical_waveform_1d",
            "sample_path": output.relative_to(data_root).as_posix(),
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_size_bytes": len(encoded),
            "sampling_frequency_hz": header["frequency"],
            "semantic_field": channel_config["semantic_field"],
            "series_id": series_id,
            "sha256": digest,
            "source_sample": source.relative_to(data_root).as_posix(),
            "source_variable": name,
            "transition_count": transitions,
            "value_count": len(values),
        })
        channel_stats[name] = {
            "distinct_values": distinct,
            "maximum": maximum,
            "minimum": minimum,
            "sha256": digest,
            "transition_count": transitions,
        }
    return entries, {
        "channels": channel_stats,
        "record_id": record_id,
        "signal_count": signal_count,
        "source_bytes": source.stat().st_size,
        "source_sha256": record["data_sha256"],
    }


def collect(
    *,
    mode: str,
    download_dir: Path,
    samples_root: Path,
    data_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    records = load_inventory(download_dir)
    entries: list[dict[str, object]] = []
    details = []
    if mode == "build":
        for config in CHANNELS.values():
            directory = samples_root / str(config["series_id"])
            if directory.exists():
                for path in directory.glob("*.bin"):
                    path.unlink()
    for record in records:
        record_entries, detail = decode_record(
            record=record,
            download_dir=download_dir,
            samples_root=samples_root,
            data_root=data_root,
            mode=mode,
        )
        entries.extend(record_entries)
        details.append(detail)
    if len(entries) != EXPECTED_RECORDS * len(CHANNELS):
        raise SystemExit("selected sample count changed")
    hashes = [str(entry["sha256"]) for entry in entries]
    if len(hashes) != len(set(hashes)):
        raise SystemExit("duplicate selected waveform sample")
    if sum(int(entry["value_count"]) for entry in entries) != EXPECTED_PRIMARY_VALUES:
        raise SystemExit("aggregate selected value count changed")
    if sum(int(entry["sample_size_bytes"]) for entry in entries) != EXPECTED_PRIMARY_BYTES:
        raise SystemExit("aggregate primary byte count changed")
    for config in CHANNELS.values():
        series_id = str(config["series_id"])
        directory = samples_root / series_id
        expected = {
            Path(str(entry["sample_path"])).name
            for entry in entries if entry["series_id"] == series_id
        }
        actual = {path.name for path in directory.glob("*.bin")}
        if actual != expected:
            raise SystemExit(f"sample inventory differs for {series_id}")
    stats = {
        "candidate_id": DATASET_ID,
        "primary_bytes": EXPECTED_PRIMARY_BYTES,
        "primary_values": EXPECTED_PRIMARY_VALUES,
        "records": details,
        "sampling_frequency_hz": EXPECTED_FREQUENCY,
        "samples": len(entries),
        "samples_per_series": EXPECTED_RECORDS,
        "source_bytes": EXPECTED_SOURCE_BYTES,
        "source_records": EXPECTED_RECORDS,
        "values_per_sample": EXPECTED_FRAMES,
    }
    return entries, stats


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "verify" and not args.samples_root.is_dir():
        raise SystemExit("missing built sample root")
    entries, stats = collect(
        mode=args.mode,
        download_dir=args.download_dir,
        samples_root=args.samples_root,
        data_root=args.data_root,
    )
    if args.mode == "build":
        write_jsonl(args.index, entries)
        write_json(args.stats, stats)
    else:
        if read_jsonl(args.index) != entries:
            raise SystemExit("sample index differs from independent source decode")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("ingest stats differ from independent source decode")
    print(
        f"mode={args.mode} records={stats['source_records']} samples={stats['samples']} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_bytes']}"
    )


if __name__ == "__main__":
    main()
