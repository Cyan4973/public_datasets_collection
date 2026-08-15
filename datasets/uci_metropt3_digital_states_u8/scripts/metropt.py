#!/usr/bin/env python3
"""Decode all eight MetroPT-3 digital sensor timelines as uint8."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import zlib


DATASET_ID = "uci_metropt3_digital_states_u8"
SERIES_ID = "metropt3_digital_state_u8"
ROW_COUNT = 1_516_948
TOTAL_VALUES = ROW_COUNT * 8
EXPECTED_HEADER = [
    "", "timestamp", "TP2", "TP3", "H1", "DV_pressure", "Reservoirs",
    "Oil_temperature", "Motor_current", "COMP", "DV_eletric", "Towers",
    "MPG", "LPS", "Pressure_switch", "Oil_level", "Caudal_impulses",
]
SIGNALS = {
    "COMP": "Air-intake valve electrical state; active while intake is closed in off or offloaded operation.",
    "DV_eletric": "Compressor outlet-valve electrical state; active while the compressor operates under load.",
    "Towers": "Air-dryer tower selector state distinguishing tower one from tower two operation.",
    "MPG": "Loaded-operation request state that activates the intake valve when APU pressure falls below its threshold.",
    "LPS": "Low-pressure switch state that activates when system pressure falls below 7 bar.",
    "Pressure_switch": "Pressure-switch state detecting discharge in the air-drying towers.",
    "Oil_level": "Oil-level switch state that activates when compressor oil is below the expected level.",
    "Caudal_impulses": "Sampled pulse-output state from the air-flow quantity sensor between the APU and reservoirs.",
}
SOURCE_IDENTITIES = {
    "downloads/uci_dataset_791.json": (9_576, "82b91c5ac61d01dadb53299d9be559f748c7e22904a6e4c08e313627d57e50b1"),
    "downloads/uci_dataset_791.html": (206_466, "7181bb85f212ff0dec63b47c15ec17ca5f8f4ca742cbe6316b3a641fc882402e"),
    "downloads/metropt3_dataset.zip": (218_381_995, "aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a"),
    "extracted/metropt3.csv": (218_300_507, "db30ccb4ea402e3c8bf2c99db06e288d4f2a772f6928f9dbe26a920d69793e24"),
}
RECIPE_DIR = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_inputs(data_root: Path) -> Path:
    base = data_root
    for relative, (size, expected_hash) in SOURCE_IDENTITIES.items():
        path = base / relative.replace("downloads/", f"downloads/{DATASET_ID}/", 1).replace(
            "extracted/", f"extracted/{DATASET_ID}/", 1
        )
        if not path.is_file() or path.stat().st_size != size or file_hash(path) != expected_hash:
            raise SystemExit(f"missing or mismatched pinned MetroPT input: {path}")
    metadata = json.loads((data_root / "downloads" / DATASET_ID / "uci_dataset_791.json").read_text(encoding="utf-8"))
    text = json.dumps(metadata).lower()
    if "metropt" not in text or "10.24432/c5vw3r" not in text or '"uci_id": 791' not in text:
        raise SystemExit("pinned UCI metadata semantics changed")
    rights = (data_root / "downloads" / DATASET_ID / "uci_dataset_791.html").read_text(
        encoding="utf-8", errors="replace"
    ).lower()
    if "metropt" not in rights or not (
        "cc by 4.0" in rights or "creative commons attribution 4.0" in rights
        or "creativecommons.org/licenses/by/4.0" in rights
    ):
        raise SystemExit("pinned UCI CC BY 4.0 evidence changed")
    return data_root / "extracted" / DATASET_ID / "metropt3.csv"


def load_expected_signals() -> dict[str, dict[str, object]]:
    with (RECIPE_DIR / "expected_signals.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != len(SIGNALS) or [row["signal"] for row in rows] != list(SIGNALS):
        raise SystemExit("expected signal table does not match the documented signal order")
    return {
        row["signal"]: {
            "zero_count": int(row["zero_count"]),
            "one_count": int(row["one_count"]),
            "transitions": int(row["transitions"]),
            "longest_run": int(row["longest_run"]),
            "sha256": row["sha256"],
        }
        for row in rows
    }


def scan_source(data_root: Path) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    source = validate_inputs(data_root)
    buffers = {name: bytearray() for name in SIGNALS}
    indexes: dict[str, int] = {}
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = [name.strip() for name in next(reader)]
        except StopIteration as error:
            raise SystemExit("empty MetroPT CSV") from error
        if header != EXPECTED_HEADER:
            raise SystemExit(f"MetroPT header changed: {header}")
        indexes = {name: header.index(name) for name in SIGNALS}
        rows = 0
        for line_number, row in enumerate(reader, 2):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != len(header):
                raise SystemExit(f"field count changed at line {line_number}: {len(row)}")
            rows += 1
            for name, index in indexes.items():
                value = row[index].strip()
                if value == "0.0":
                    buffers[name].append(0)
                elif value == "1.0":
                    buffers[name].append(1)
                else:
                    raise SystemExit(f"non-binary {name} value at line {line_number}: {value!r}")
    if rows != ROW_COUNT or any(len(values) != ROW_COUNT for values in buffers.values()):
        raise SystemExit(f"MetroPT row count changed: {rows}")
    payloads = {name: bytes(values) for name, values in buffers.items()}
    profiles = []
    expected_signals = load_expected_signals()
    hashes: set[str] = set()
    for name, payload in payloads.items():
        histogram = Counter(payload)
        if set(histogram) != {0, 1}:
            raise SystemExit(f"digital signal lost binary diversity: {name}")
        transitions = sum(left != right for left, right in zip(payload, payload[1:]))
        longest_run = 0
        current_run = 0
        previous = None
        for value in payload:
            if value == previous:
                current_run += 1
            else:
                longest_run = max(longest_run, current_run)
                current_run = 1
                previous = value
        longest_run = max(longest_run, current_run)
        digest = hashlib.sha256(payload).hexdigest()
        if digest in hashes:
            raise SystemExit(f"duplicate digital signal payload: {name}")
        hashes.add(digest)
        actual_identity = {
            "zero_count": histogram[0],
            "one_count": histogram[1],
            "transitions": transitions,
            "longest_run": longest_run,
            "sha256": digest,
        }
        if actual_identity != expected_signals[name]:
            raise SystemExit(
                f"pinned digital signal identity changed for {name}: "
                f"{actual_identity} != {expected_signals[name]}"
            )
        profiles.append({
            "signal": name,
            "description": SIGNALS[name],
            "value_count": len(payload),
            "histogram": {str(key): histogram[key] for key in sorted(histogram)},
            "transitions": transitions,
            "longest_run": longest_run,
            "sha256": digest,
            "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
        })
    return payloads, profiles


def make_summary(profiles: list[dict[str, object]]) -> dict[str, object]:
    if len(profiles) != len(SIGNALS) or sum(int(row["value_count"]) for row in profiles) != TOTAL_VALUES:
        raise SystemExit("MetroPT output geometry changed")
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_row_count": ROW_COUNT,
        "sample_count": len(profiles),
        "value_count": TOTAL_VALUES,
        "total_size_bytes": TOTAL_VALUES,
        "signals": profiles,
    }


def inspect(args: argparse.Namespace) -> None:
    _payloads, profiles = scan_source(args.data_root)
    print(json.dumps(make_summary(profiles), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    payloads, profiles = scan_source(args.data_root)
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    rows = []
    profile_map = {row["signal"]: row for row in profiles}
    for signal, payload in payloads.items():
        profile = profile_map[signal]
        output = series_dir / f"{signal.lower()}_u8_n{ROW_COUNT}.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"extracted/{DATASET_ID}/metropt3.csv",
            "source_column": signal,
            "signal_description": SIGNALS[signal],
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": len(payload),
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous uint8 industrial digital-state timeline",
            "sample_geometry": "metropt3_sensor_timeline_1d",
            "sample_rank": 1,
            "sample_shape": [len(payload)],
            "sample_axes": ["observation_order"],
            "natural_record_kind": "metropt3_complete_sensor_timeline",
            "source_format": "UCI MetroPT-3 comma-separated telemetry table",
            "source_field": signal,
            "histogram": profile["histogram"],
            "transitions": profile["transitions"],
            "longest_run": profile["longest_run"],
            "sha256": profile["sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    result = make_summary(profiles)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    payloads, profiles = scan_source(args.data_root)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing MetroPT index or stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(SIGNALS):
        raise SystemExit(f"unexpected MetroPT index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    for row, (signal, payload) in zip(rows, payloads.items(), strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"dataset/series/role mismatch for {signal}")
        if row.get("source_column") != signal or row.get("source_field") != signal:
            raise SystemExit(f"signal ordering or source-field mismatch for {signal}")
        if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 8 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch for {signal}")
        if row.get("sample_shape") != [ROW_COUNT] or int(row.get("value_count", 0)) != ROW_COUNT:
            raise SystemExit(f"sample geometry mismatch for {signal}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh CSV parse for {signal}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch for {signal}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("MetroPT sample directory contains stale or extra outputs")
    expected_summary = make_summary(profiles)
    if json.loads(args.stats.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("MetroPT ingest stats differ from fresh CSV parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(SIGNALS),
        "verified_values": TOTAL_VALUES,
        "verified_bytes": TOTAL_VALUES,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--data-root", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--data-root", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
