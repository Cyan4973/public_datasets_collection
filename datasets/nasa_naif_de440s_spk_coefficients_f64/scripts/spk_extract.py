#!/usr/bin/env python3
# Local decoder for the accepted NASA/JPL DE440s SPK recipe.
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys


DATASET_ID = "nasa_naif_de440s_spk_coefficients_f64"
SERIES_ID = "spk_type2_position_chebyshev_f64"
DAF_RECORD_BYTES = 1024
DAF_WORD_BYTES = 8
MAX_PRIMARY_BYTES = 1_000_000_000


def unpack_from(fmt: str, data: bytes, offset: int = 0):
    return struct.unpack_from(fmt, data, offset)


def exact_positive_int(value: float, name: str) -> int:
    if not math.isfinite(value) or value < 1 or value != int(value):
        raise ValueError(f"invalid {name}: {value!r}")
    return int(value)


def file_header(raw: bytes) -> dict[str, object]:
    if len(raw) < DAF_RECORD_BYTES:
        raise ValueError("source is shorter than one DAF record")
    record = raw[:DAF_RECORD_BYTES]
    if record[:8] != b"DAF/SPK ":
        raise ValueError(f"expected DAF/SPK identity, got {record[:8]!r}")
    binary_format = record[88:96]
    if binary_format == b"LTL-IEEE":
        endian = "<"
    elif binary_format == b"BIG-IEEE":
        endian = ">"
    else:
        raise ValueError(f"unsupported DAF binary format {binary_format!r}")
    nd, ni = unpack_from(endian + "ii", record, 8)
    forward, backward, free = unpack_from(endian + "iii", record, 76)
    if (nd, ni) != (2, 6):
        raise ValueError(f"unexpected SPK summary dimensions ND={nd} NI={ni}")
    record_count = len(raw) // DAF_RECORD_BYTES
    if len(raw) % DAF_RECORD_BYTES:
        raise ValueError("DAF source size is not a multiple of 1024 bytes")
    if not 1 <= forward <= record_count or not 1 <= backward <= record_count:
        raise ValueError("DAF summary record pointers are out of bounds")
    if not 1 <= free <= len(raw) // DAF_WORD_BYTES + 1:
        raise ValueError("DAF free-address pointer is out of bounds")
    return {
        "endian": endian,
        "binary_format": binary_format.decode("ascii"),
        "nd": nd,
        "ni": ni,
        "forward": forward,
        "backward": backward,
        "free": free,
        "record_count": record_count,
    }


def read_summaries(raw: bytes, header: dict[str, object]) -> list[dict[str, object]]:
    endian = str(header["endian"])
    summary_size_words = int(header["nd"]) + (int(header["ni"]) + 1) // 2
    summary_size_bytes = summary_size_words * DAF_WORD_BYTES
    name_size = summary_size_bytes
    capacity = (DAF_RECORD_BYTES - 3 * DAF_WORD_BYTES) // summary_size_bytes
    record_no = int(header["forward"])
    previous = 0
    seen = set()
    summaries = []
    while record_no:
        if record_no in seen:
            raise ValueError("cycle in DAF summary record chain")
        seen.add(record_no)
        offset = (record_no - 1) * DAF_RECORD_BYTES
        record = raw[offset : offset + DAF_RECORD_BYTES]
        next_value, prev_value, count_value = unpack_from(endian + "ddd", record, 0)
        next_record = int(next_value)
        prev_record = int(prev_value)
        count = int(count_value)
        if next_value != next_record or prev_value != prev_record or count_value != count:
            raise ValueError(f"non-integral summary control value in record {record_no}")
        if prev_record != previous:
            raise ValueError(f"broken previous-summary pointer in record {record_no}")
        if count < 0 or count > capacity:
            raise ValueError(f"invalid summary count {count} in record {record_no}")
        name_record_no = record_no + 1
        name_offset = (name_record_no - 1) * DAF_RECORD_BYTES
        if name_offset + DAF_RECORD_BYTES > len(raw):
            raise ValueError("missing DAF name record")
        name_record = raw[name_offset : name_offset + DAF_RECORD_BYTES]
        for index in range(count):
            summary_offset = 3 * DAF_WORD_BYTES + index * summary_size_bytes
            summary = record[summary_offset : summary_offset + summary_size_bytes]
            if len(summary) != summary_size_bytes:
                raise ValueError("truncated DAF summary")
            initial_et, final_et = unpack_from(endian + "dd", summary, 0)
            target, center, frame, data_type, start, end = unpack_from(endian + "6i", summary, 16)
            name_raw = name_record[index * name_size : (index + 1) * name_size]
            name = name_raw.decode("ascii", errors="replace").rstrip(" \x00")
            if not (math.isfinite(initial_et) and math.isfinite(final_et) and initial_et < final_et):
                raise ValueError(f"invalid coverage interval in summary {name!r}")
            if start < 1 or end < start or end * DAF_WORD_BYTES > len(raw):
                raise ValueError(f"invalid array addresses for summary {name!r}: {start}..{end}")
            summaries.append(
                {
                    "ordinal": len(summaries),
                    "name": name,
                    "initial_et": initial_et,
                    "final_et": final_et,
                    "target": target,
                    "center": center,
                    "frame": frame,
                    "data_type": data_type,
                    "start_address": start,
                    "end_address": end,
                }
            )
        previous = record_no
        if next_record < 0 or next_record > int(header["record_count"]):
            raise ValueError(f"next-summary pointer out of bounds: {next_record}")
        record_no = next_record
    if previous != int(header["backward"]):
        raise ValueError("DAF backward-summary pointer does not match summary chain")
    if not summaries:
        raise ValueError("DAF/SPK contains no segment summaries")
    return summaries


def decode_type2(raw: bytes, endian: str, summary: dict[str, object]) -> dict[str, object]:
    start = int(summary["start_address"])
    end = int(summary["end_address"])
    count = end - start + 1
    words = list(unpack_from(endian + f"{count}d", raw, (start - 1) * DAF_WORD_BYTES))
    if len(words) < 9:
        raise ValueError(f"type-2 segment is too short: {summary['name']!r}")
    init, intlen, rsize_value, record_count_value = words[-4:]
    record_size = exact_positive_int(rsize_value, "SPK record size")
    record_count = exact_positive_int(record_count_value, "SPK record count")
    if not math.isfinite(init) or not math.isfinite(intlen) or intlen <= 0:
        raise ValueError(f"invalid type-2 segment directory in {summary['name']!r}")
    if record_count * record_size + 4 != len(words):
        raise ValueError(f"type-2 directory size mismatch in {summary['name']!r}")
    if record_size <= 2 or (record_size - 2) % 3:
        raise ValueError(f"invalid type-2 record size {record_size} in {summary['name']!r}")
    coefficients_per_component = (record_size - 2) // 3
    coefficients = []
    for record_index in range(record_count):
        record = words[record_index * record_size : (record_index + 1) * record_size]
        midpoint, radius = record[:2]
        if not math.isfinite(midpoint) or not math.isfinite(radius) or radius <= 0:
            raise ValueError(f"invalid domain values in {summary['name']!r} record {record_index}")
        record_coefficients = record[2:]
        if not all(math.isfinite(value) for value in record_coefficients):
            raise ValueError(f"non-finite coefficient in {summary['name']!r} record {record_index}")
        coefficients.extend(record_coefficients)
    if len(coefficients) >= 1_000 and min(coefficients) == max(coefficients):
        raise ValueError(f"constant coefficient segment: {summary['name']!r}")
    result = dict(summary)
    result.update(
        {
            "init": init,
            "interval_length": intlen,
            "record_size": record_size,
            "record_count": record_count,
            "coefficients_per_component": coefficients_per_component,
            "coefficient_count": len(coefficients),
            "minimum": min(coefficients),
            "maximum": max(coefficients),
            "coefficients": coefficients,
        }
    )
    return result


def scan_spk(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    header = file_header(raw)
    summaries = read_summaries(raw, header)
    segments = []
    skipped_types: dict[str, int] = {}
    skipped_tiny_segments = []
    for summary in summaries:
        data_type = int(summary["data_type"])
        if data_type == 2:
            segment = decode_type2(raw, str(header["endian"]), summary)
            if int(segment["coefficient_count"]) < 1_000:
                skipped = public_segment(segment)
                skipped["reason"] = "natural_sample_below_1000_values"
                skipped_tiny_segments.append(skipped)
            else:
                segments.append(segment)
        else:
            key = str(data_type)
            skipped_types[key] = skipped_types.get(key, 0) + 1
    if not segments:
        raise ValueError("SPK contains no supported type-2 segments")
    return {
        "source_size_bytes": len(raw),
        "binary_format": header["binary_format"],
        "summary_count": len(summaries),
        "skipped_segment_types": skipped_types,
        "skipped_tiny_segments": skipped_tiny_segments,
        "segments": segments,
    }


def sample_name(segment: dict[str, object]) -> str:
    return (
        f"segment_{int(segment['ordinal']):03d}_target_{int(segment['target'])}_"
        f"center_{int(segment['center'])}_frame_{int(segment['frame'])}.bin"
    )


def public_segment(segment: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in segment.items() if key != "coefficients"}


def write_little_doubles(path: Path, values: list[float]) -> None:
    with path.open("wb") as handle:
        chunk_size = 65_536
        for offset in range(0, len(values), chunk_size):
            chunk = values[offset : offset + chunk_size]
            handle.write(struct.pack("<" + "d" * len(chunk), *chunk))


def extract(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    data_root = Path(args.data_root).resolve()
    samples_root = Path(args.samples_root)
    index_path = Path(args.index_path)
    stats_path = Path(args.stats_path)
    if not input_path.is_file():
        raise SystemExit(f"missing local SPK kernel: {input_path}")

    scan = scan_spk(input_path)
    series_root = samples_root / SERIES_ID
    if series_root.exists():
        shutil.rmtree(series_root)
    series_root.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    counts = []
    total_bytes = 0
    for segment in scan["segments"]:
        path = series_root / sample_name(segment)
        coefficients = segment["coefficients"]
        write_little_doubles(path, coefficients)
        size = path.stat().st_size
        try:
            relative_path = path.resolve().relative_to(data_root).as_posix()
        except ValueError as error:
            raise SystemExit(f"sample path is outside DATA_DIR: {path}") from error
        records.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": relative_path,
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": size,
                "value_count": len(coefficients),
            }
        )
        counts.append(len(coefficients))
        total_bytes += size

    if sum(counts) < 10_000 and total_bytes < 102_400:
        raise SystemExit("decoded primary output is below the aggregate floor")
    if statistics.median(counts) < 1_000:
        raise SystemExit("median decoded segment is below 1,000 coefficients")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"decoded primary output exceeds {MAX_PRIMARY_BYTES} bytes")

    with index_path.open("w", encoding="utf-8", newline="") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_path": str(input_path),
        "source_size_bytes": scan["source_size_bytes"],
        "binary_format": scan["binary_format"],
        "summary_count": scan["summary_count"],
        "skipped_segment_types": scan["skipped_segment_types"],
        "skipped_tiny_segments": scan["skipped_tiny_segments"],
        "primary_sample_count": len(records),
        "primary_value_count": sum(counts),
        "primary_sample_bytes": total_bytes,
        "median_primary_sample_value_count": statistics.median(counts),
        "segments": [public_segment(segment) for segment in scan["segments"]],
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(records)} values={sum(counts)} bytes={total_bytes} "
        f"median_values={statistics.median(counts)}"
    )


def inspect(args: argparse.Namespace) -> None:
    scan = scan_spk(Path(args.input))
    clean = dict(scan)
    clean["segments"] = [public_segment(segment) for segment in scan["segments"]]
    print(json.dumps(clean, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Decode native float64 coefficients from NAIF DAF/SPK kernels")
    subparsers = root.add_subparsers(dest="command", required=True)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--input", required=True)
    extract_parser.add_argument("--data-root", required=True)
    extract_parser.add_argument("--samples-root", required=True)
    extract_parser.add_argument("--index-path", required=True)
    extract_parser.add_argument("--stats-path", required=True)
    extract_parser.set_defaults(func=extract)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--input", required=True)
    inspect_parser.set_defaults(func=inspect)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, struct.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
