#!/usr/bin/env python3
"""Build and verify anonymous uint16 read-register series from pinned PCAP."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import shutil
import sys

from inspect_modbus_pcap import inspect


DATASET_ID = "zenodo_zeroswarm_modbus_registers_u16"
SOURCE_NAME = "ZeroSWARM Normal data_v2b.pcap"
SOURCE_SIZE = 18_119_840
SOURCE_MD5 = "9f8235fcdbfcacb32e7a70db14fc6c74"
EXPECTED_COUNT = 16_280
SERIES_BY_OPERATION = {
    "input_read": "zeroswarm_modbus_input_register_u16",
    "holding_read": "zeroswarm_modbus_holding_register_u16",
}
EXPECTED_KEYS = {
    (1, "input_read", 0),
    (1, "input_read", 1),
    (1, "holding_read", 0),
    (1, "holding_read", 1),
}


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sources(download_dir: Path) -> Path:
    pcap = download_dir / SOURCE_NAME
    metadata = download_dir / "zenodo_record_15082260.json"
    if not pcap.is_file() or pcap.stat().st_size != SOURCE_SIZE or md5(pcap) != SOURCE_MD5:
        raise SystemExit("missing or mismatched pinned Zero-SWARM PCAP")
    if not metadata.is_file():
        raise SystemExit("missing Zenodo record metadata")
    record = json.loads(metadata.read_text())
    if int(record.get("id", 0)) != 15082260:
        raise SystemExit("unexpected Zenodo record id")
    if record.get("metadata", {}).get("title") != "Modbus Normal and Malicious Network Traffic":
        raise SystemExit("unexpected Zenodo title")
    if record.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    return pcap


def encode(values: list[int]) -> bytes:
    words = array("H", values)
    if words.itemsize != 2:
        raise SystemExit("host unsigned-short width is not 16 bits")
    if sys.byteorder == "big":
        words.byteswap()
    return words.tobytes()


def selected_series(pcap: Path) -> tuple[dict[str, object], dict[tuple[int, str, int], list[int]]]:
    report, decoded = inspect(pcap, include_series=True)
    selected = {key: decoded[key] for key in EXPECTED_KEYS if key in decoded}
    if set(selected) != EXPECTED_KEYS:
        raise SystemExit(f"unexpected target register keys: {sorted(selected)}")
    for key, values in selected.items():
        if len(values) != EXPECTED_COUNT:
            raise SystemExit(f"unexpected observation count for {key}: {len(values)}")
        if len(set(values)) < 2:
            raise SystemExit(f"constant target register stream: {key}")
    return report, selected


def build(args: argparse.Namespace) -> None:
    pcap = validate_sources(args.download_dir)
    report, selected = selected_series(pcap)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    rows: list[dict[str, object]] = []
    series_stats: dict[str, dict[str, object]] = {}
    for (unit, operation, address), values in sorted(selected.items()):
        series_id = SERIES_BY_OPERATION[operation]
        family_dir = args.samples_dir / series_id
        family_dir.mkdir(parents=True, exist_ok=True)
        output = family_dir / f"unit_{unit:03d}_register_{address:05d}_n{len(values):05d}.bin"
        payload = encode(values)
        output.write_bytes(payload)
        relative_output = output.relative_to(args.data_root).as_posix()
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "sample_path": relative_output,
            "source_sample": pcap.relative_to(args.data_root).as_posix(),
            "source_file": pcap.name,
            "unit_id": unit,
            "register_kind": operation.removesuffix("_read"),
            "register_address": address,
            "value_count": len(values),
            "sample_size_bytes": len(payload),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "sample_geometry": "1d_industrial_register_time_series",
            "natural_record_kind": "modbus_unit_register",
            "minimum": min(values),
            "maximum": max(values),
            "distinct_values": len(set(values)),
            "transitions": sum(left != right for left, right in zip(values, values[1:])),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        stats = series_stats.setdefault(series_id, {"sample_count": 0, "value_count": 0, "total_size_bytes": 0})
        stats["sample_count"] = int(stats["sample_count"]) + 1
        stats["value_count"] = int(stats["value_count"]) + len(values)
        stats["total_size_bytes"] = int(stats["total_size_bytes"]) + len(payload)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "source_file": SOURCE_NAME,
        "source_md5": SOURCE_MD5,
        "decoded_preflight": report,
        "series": series_stats,
        "sample_count": len(rows),
        "value_count": sum(int(row["value_count"]) for row in rows),
        "total_size_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    pcap = validate_sources(args.download_dir)
    _, selected = selected_series(pcap)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != len(EXPECTED_KEYS):
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    total_values = 0
    total_bytes = 0
    for row in rows:
        operation = f"{row['register_kind']}_read"
        key = (int(row["unit_id"]), operation, int(row["register_address"]))
        if key not in selected:
            raise SystemExit(f"index contains unexpected register key: {key}")
        expected = encode(selected[key])
        output = args.data_root / str(row["sample_path"])
        if not output.is_file() or output.read_bytes() != expected:
            raise SystemExit(f"output mismatch: {output}")
        if row.get("sha256") != hashlib.sha256(expected).hexdigest():
            raise SystemExit(f"indexed hash mismatch: {output}")
        if int(row["value_count"]) != len(selected[key]) or int(row["sample_size_bytes"]) != len(expected):
            raise SystemExit(f"indexed size mismatch: {output}")
        expected_outputs.add(output.resolve())
        total_values += len(selected[key])
        total_bytes += len(expected)
    actual_outputs = {path.resolve() for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    if stats.get("sample_count") != len(rows) or stats.get("value_count") != total_values or stats.get("total_size_bytes") != total_bytes:
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(rows),
        "verified_values": total_values,
        "verified_bytes": total_bytes,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
