#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil


DATASET_ID = "zenodo_aegis_obd_pid_u8"
SERIES_ID = "aegis_obd_pid_value_u8"
HEADER = ["obdData_id", "trip_id", "obdPid", "data", "timestamp"]
MIN_VALUES = 1_024
PID_NAMES = {
    "04": "calculated_engine_load",
    "05": "engine_coolant_temperature",
    "0B": "intake_manifold_pressure",
    "0C": "engine_speed",
    "0D": "vehicle_speed",
    "0F": "intake_air_temperature",
    "10": "mass_air_flow_rate",
    "11": "throttle_position",
    "33": "absolute_barometric_pressure",
    "3C": "catalyst_temperature_bank1_sensor1",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decimal_value(text: str) -> Decimal | None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def main() -> None:
    args = parse_args()
    data_root = args.repo_root / args.data_dir
    source = data_root / "extracted" / DATASET_ID / "obdData.csv"
    inventory_path = data_root / "downloads" / DATASET_ID / "inventory.json"
    filter_dir = data_root / "filtered" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    output_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    if not source.is_file() or not inventory_path.is_file():
        raise SystemExit("missing validated local source; run download.sh first")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[tuple[int, str], dict[str, object]] = defaultdict(
        lambda: {
            "values": bytearray(), "count": 0, "numeric": 0, "integral": 0,
            "u8_eligible": True, "minimum": None, "maximum": None,
            "histogram": Counter(), "previous_timestamp": None,
            "timestamps_monotonic": True,
        }
    )
    rows = 0
    previous_row_id = 0
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != HEADER:
            raise SystemExit(f"source header mismatch: {header}")
        for line_number, row in enumerate(reader, 2):
            if len(row) != 5:
                raise SystemExit(f"line {line_number}: expected 5 fields, got {len(row)}")
            try:
                row_id = int(row[0])
                trip_id = int(row[1])
            except ValueError as exc:
                raise SystemExit(f"line {line_number}: invalid row/trip ID: {exc}")
            if row_id != previous_row_id + 1:
                raise SystemExit(f"line {line_number}: nonconsecutive row ID {row_id} after {previous_row_id}")
            previous_row_id = row_id
            pid = row[2].strip().upper()
            if not re.fullmatch(r"[0-9A-F]{2}", pid):
                raise SystemExit(f"line {line_number}: invalid OBD PID {pid!r}")
            timestamp = row[4].strip()
            try:
                datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise SystemExit(f"line {line_number}: invalid timestamp: {exc}")
            group = groups[(trip_id, pid)]
            group["count"] = int(group["count"]) + 1
            previous_timestamp = group["previous_timestamp"]
            if previous_timestamp is not None and timestamp < str(previous_timestamp):
                group["timestamps_monotonic"] = False
            group["previous_timestamp"] = timestamp
            value = decimal_value(row[3].strip())
            if value is not None:
                group["numeric"] = int(group["numeric"]) + 1
                if value == value.to_integral_value():
                    group["integral"] = int(group["integral"]) + 1
                minimum = group["minimum"]
                maximum = group["maximum"]
                group["minimum"] = value if minimum is None or value < minimum else minimum
                group["maximum"] = value if maximum is None or value > maximum else maximum
            if value is None or value != value.to_integral_value() or not 0 <= value <= 255:
                group["u8_eligible"] = False
                values = group["values"]
                if isinstance(values, bytearray):
                    values.clear()
            elif bool(group["u8_eligible"]):
                integer = int(value)
                values = group["values"]
                histogram = group["histogram"]
                assert isinstance(values, bytearray) and isinstance(histogram, Counter)
                values.append(integer)
                histogram[integer] += 1
            rows += 1

    index_rows: list[dict[str, object]] = []
    profiles: list[dict[str, object]] = []
    for (trip_id, pid), group in sorted(groups.items()):
        values = group["values"]
        histogram = group["histogram"]
        assert isinstance(values, bytearray) and isinstance(histogram, Counter)
        selected = (
            int(group["count"]) >= MIN_VALUES and bool(group["u8_eligible"])
            and bool(group["timestamps_monotonic"]) and len(histogram) > 1
            and len(values) == int(group["count"])
        )
        profile = {
            "trip_id": trip_id, "pid": pid, "pid_name": PID_NAMES.get(pid, "unknown"),
            "observations": int(group["count"]), "numeric_values": int(group["numeric"]),
            "integer_values": int(group["integral"]),
            "minimum": str(group["minimum"]) if group["minimum"] is not None else None,
            "maximum": str(group["maximum"]) if group["maximum"] is not None else None,
            "distinct_u8_values": len(histogram),
            "timestamps_monotonic": bool(group["timestamps_monotonic"]),
            "complete_u8": bool(group["u8_eligible"]) and len(values) == int(group["count"]),
            "selected": selected,
        }
        profiles.append(profile)
        if not selected:
            continue
        data = bytes(values)
        output = output_dir / f"trip{trip_id:03d}_pid{pid}_u8_n{len(data)}.bin"
        output.write_bytes(data)
        sample_rel = output.relative_to(data_root).as_posix()
        source_rel = source.relative_to(data_root).as_posix()
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": sample_rel, "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1,
            "sample_size_bytes": len(data), "value_count": len(data),
            "sample_format": "raw homogeneous uint8 decoded OBD measurement timeline",
            "sample_geometry": "variable_length_trip_pid_timeline_1d",
            "sample_rank": 1, "sample_shape": [len(data)],
            "sample_axes": ["observation_order"],
            "natural_record_kind": "complete_aegis_trip_pid_timeline",
            "source_format": "AEGIS five-column comma-separated OBD observation table",
            "source_field": "data grouped by trip_id and obdPid",
            "source_path": source_rel, "source_trip_id": trip_id,
            "obd_pid_hex": pid, "obd_pid_name": PID_NAMES.get(pid, "unknown"),
            "minimum": min(data), "maximum": max(data),
            "distinct_values": len(histogram),
            "value_histogram": {str(key): histogram[key] for key in sorted(histogram)},
            "sha256": sha256_bytes(data),
        })
        print(
            f"built trip={trip_id} pid={pid} name={PID_NAMES.get(pid, 'unknown')} "
            f"values={len(data)} range={min(data)}..{max(data)} distinct={len(histogram)}"
        )

    if len(index_rows) < 3:
        raise SystemExit(f"too few qualifying trip/PID samples: {len(index_rows)}")
    hashes = [str(row["sha256"]) for row in index_rows]
    if len(hashes) != len(set(hashes)):
        raise SystemExit("duplicate primary samples detected")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in index_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts = sorted(int(row["value_count"]) for row in index_rows)
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID,
        "source_rows": rows, "source_trip_ids": len({trip for trip, _ in groups}),
        "source_pids": sorted({pid for _, pid in groups}),
        "trip_pid_groups": len(groups), "samples": len(index_rows),
        "primary_values": sum(counts), "primary_sample_bytes": sum(counts),
        "min_sample_values": counts[0], "median_sample_values": counts[len(counts) // 2],
        "max_sample_values": counts[-1], "selected_trip_ids": len({int(row["source_trip_id"]) for row in index_rows}),
        "selected_pids": sorted({str(row["obd_pid_hex"]) for row in index_rows}),
        "profiles": profiles,
    }
    (filter_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in stats.items() if key != "profiles"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
