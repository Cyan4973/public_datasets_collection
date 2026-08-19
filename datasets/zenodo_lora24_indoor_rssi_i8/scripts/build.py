#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import shutil


DATASET_ID = "zenodo_lora24_indoor_rssi_i8"
SERIES_ID = "lora24_rssi_i8"
MIN_VALUES = 1_024


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    return parser.parse_args()


def decode_node(data: str, real_cr: int, exhaustive: bool) -> int | None:
    if len(data) < 16 or data[3:5] != "00":
        return None
    width = 3 if exhaustive and real_cr == 4 else 2
    try:
        node = int(data[:width])
        int(data[9:16], 16)
    except ValueError:
        return None
    return node if node in (1, 2, 3) else None


def parse_sources(download_dir: Path) -> tuple[dict[tuple[object, ...], bytearray], dict[str, object]]:
    groups: dict[tuple[object, ...], bytearray] = defaultdict(bytearray)
    source_rows = valid_packets = 0
    experiment_counts = Counter()
    for experiment, filename in (("exhaustive", "Test_Exhaustive_experiment.csv"), ("long_run", "Test_long_run.csv")):
        exhaustive = experiment == "exhaustive"
        with (download_dir / filename).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"chan", "freq", "modu", "datr", "bw", "codr", "rssi", "size", "data", "real_cr"}
            if not required.issubset(reader.fieldnames or []):
                raise SystemExit(f"missing fields in {filename}: {reader.fieldnames}")
            for line_number, row in enumerate(reader, 2):
                source_rows += 1
                if None in row:
                    raise SystemExit(f"extra CSV fields {filename}:{line_number}")
                try:
                    size = int(row["size"])
                    real_cr = int(row["real_cr"])
                    rssi = int(row["rssi"])
                except ValueError as exc:
                    raise SystemExit(f"invalid numeric field {filename}:{line_number}: {exc}")
                if not -128 <= rssi <= 127:
                    raise SystemExit(f"RSSI outside int8 {filename}:{line_number}: {rssi}")
                if size != 20:
                    continue
                node = decode_node(row["data"], real_cr, exhaustive)
                if node is None:
                    continue
                if exhaustive:
                    key: tuple[object, ...] = (experiment, node)
                else:
                    try:
                        key = (
                            experiment, node, int(row["chan"]), int(row["freq"]),
                            int(row["datr"]), int(row["bw"]), row["codr"],
                            int(row["power"]), real_cr,
                        )
                    except ValueError as exc:
                        raise SystemExit(f"invalid long-run configuration {filename}:{line_number}: {exc}")
                groups[key].append(rssi & 0xFF)
                valid_packets += 1
                experiment_counts[experiment] += 1
    return groups, {
        "source_rows": source_rows, "valid_node_packets": valid_packets,
        "experiment_valid_packets": dict(experiment_counts),
    }


def main() -> None:
    args = arguments()
    data_root = args.repo_root / args.data_dir
    download_dir = data_root / "downloads" / DATASET_ID
    if not (download_dir / "inventory.json").is_file():
        raise SystemExit("missing validated inventory; run download.sh first")
    output_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filter_dir = data_root / "filtered" / DATASET_ID
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    groups, source_stats = parse_sources(download_dir)
    rows: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for key, values in sorted(groups.items(), key=lambda item: tuple(str(value) for value in item[0])):
        signed = [value if value < 128 else value - 256 for value in values]
        histogram = Counter(signed)
        if len(values) < MIN_VALUES or len(histogram) <= 1:
            rejected.append({"key": list(key), "values": len(values), "distinct": len(histogram)})
            continue
        experiment, node = str(key[0]), int(key[1])
        if experiment == "exhaustive":
            suffix = f"exhaustive_node{node}"
            configuration: dict[str, object] | None = None
            record_kind = "complete_exhaustive_node_sweep_timeline"
        else:
            _, _, chan, freq, datr, bw, codr, power, real_cr = key
            suffix = f"long_node{node}_ch{chan}_f{freq}_sf{datr}_bw{bw}_cr{real_cr}_p{power}"
            configuration = {
                "channel": chan, "frequency_mhz": freq, "spreading_factor": datr,
                "bandwidth_khz_code": bw, "coding_rate_text": codr,
                "transmit_power": power, "real_coding_rate": real_cr,
            }
            record_kind = "complete_long_run_node_configuration_timeline"
        output = output_dir / f"{suffix}_i8_n{len(values)}.bin"
        data = bytes(values)
        output.write_bytes(data)
        row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": output.relative_to(data_root).as_posix(),
            "numeric_kind": "int", "bit_width": 8, "endianness": "little",
            "element_size_bytes": 1, "sample_size_bytes": len(data), "value_count": len(data),
            "sample_format": "raw homogeneous signed-int8 RSSI timeline",
            "sample_geometry": "variable_length_fixed_link_packet_timeline_1d",
            "sample_rank": 1, "sample_shape": [len(data)], "sample_axes": ["received_packet_order"],
            "natural_record_kind": record_kind, "source_experiment": experiment,
            "source_node_id": node, "radio_configuration": configuration,
            "source_field": "rssi for valid size=20 node packets decoded by the published scripts",
            "minimum": min(signed), "maximum": max(signed), "distinct_values": len(histogram),
            "value_histogram": {str(value): histogram[value] for value in sorted(histogram)},
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        rows.append(row)
        print(f"built {suffix} values={len(data)} range={min(signed)}..{max(signed)} distinct={len(histogram)}")
    if len(rows) < 6:
        raise SystemExit(f"too few qualifying samples: {len(rows)}")
    hashes = [row["sha256"] for row in rows]
    if len(hashes) != len(set(hashes)):
        raise SystemExit("duplicate sample payloads")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts = sorted(int(row["value_count"]) for row in rows)
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, **source_stats,
        "groups_seen": len(groups), "groups_rejected": rejected,
        "samples": len(rows), "primary_values": sum(counts), "primary_sample_bytes": sum(counts),
        "min_sample_values": counts[0], "median_sample_values": counts[len(counts) // 2],
        "max_sample_values": counts[-1],
        "samples_by_experiment": dict(Counter(str(row["source_experiment"]) for row in rows)),
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in stats.items() if key != "groups_rejected"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
