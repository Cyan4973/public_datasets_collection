#!/usr/bin/env python3
"""Strictly decode RDI PD0 earth-coordinate int16 velocity ensembles."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys


DATASET_ID = "zenodo_adcp_pd0_i16"
SERIES_ID = "adcp_earth_velocity_i16"
ENSEMBLE_BYTES = 1172
TOTAL_ENSEMBLE_BYTES = 1174
BEAMS = 4
CELLS = 51
VALUES_PER_ENSEMBLE = BEAMS * CELLS
VELOCITY_BYTES_PER_ENSEMBLE = VALUES_PER_ENSEMBLE * 2
OFFSETS = (18, 77, 142, 552, 758, 964)
BLOCK_IDS = (0x0000, 0x0080, 0x0100, 0x0200, 0x0300, 0x0400)
VELOCITY_OFFSET = OFFSETS[2] + 2
VELOCITY_END = OFFSETS[3]
INVALID_VELOCITY = -32768
SOURCES = (
    {
        "name": "line2_ADCP1000.000",
        "size": 24_813_664,
        "md5": "04c27147b68aecb5e6feef84702d9b5e",
        "ensembles": 21_136,
        "payload_sha256": "0da90b8c4491ec8130bab1a69fef5e168b65e9ce53c57541a0f6993cebef9d90",
        "minimum": -32768,
        "maximum": 9537,
        "distinct_values": 3462,
        "invalid_values": 522660,
        "transitions": 3870607,
    },
    {
        "name": "line2_ADCP1001.000",
        "size": 46_960_000,
        "md5": "8e1631f12dd8caa61c2dc76a31efb642",
        "ensembles": 40_000,
        "payload_sha256": "4f98d2efa473a59e17bc3e990904f02093ee754f080a6356ecba7132feea831a",
        "minimum": -32768,
        "maximum": 4733,
        "distinct_values": 3378,
        "invalid_values": 934993,
        "transitions": 7430055,
    },
    {
        "name": "line3_ADCP2001.000",
        "size": 10_962_812,
        "md5": "3f8da2d38e4f6783f5fdff1dff82f3a1",
        "ensembles": 9_338,
        "payload_sha256": "4b8c2507eadfc7f2888972871e6896567c2d3ed8d502bf58cc328f3893c63131",
        "minimum": -32768,
        "maximum": 8236,
        "distinct_values": 2831,
        "invalid_values": 230738,
        "transitions": 1698665,
    },
)
AGGREGATE_SHA256 = "98a4beb96fbd5e6ae46cca792019533d7857cbd60c26dc93faecd43bb114eb5c"


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_record_metadata(download_dir: Path) -> None:
    metadata_path = download_dir / "zenodo_record_5015459.json"
    if not metadata_path.is_file():
        raise SystemExit(f"missing Zenodo metadata: {metadata_path}")
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    license_obj = metadata.get("license", {}) if isinstance(metadata, dict) else {}
    if (
        int(record.get("id", 0)) != 5015459
        or metadata.get("title") != "Salinity and Velocity in Lower South San Francisco Bay"
        or not isinstance(license_obj, dict)
        or license_obj.get("id") != "cc-by-4.0"
    ):
        raise SystemExit("unexpected Zenodo record identity, title, or license")


def decode_source(path: Path, expected: dict[str, object]) -> tuple[bytes, dict[str, object]]:
    if path.stat().st_size != expected["size"] or file_hash(path, "md5") != expected["md5"]:
        raise ValueError(f"{path.name}: source size or MD5 mismatch")
    data = path.read_bytes()
    if len(data) % TOTAL_ENSEMBLE_BYTES:
        raise ValueError(f"{path.name}: source is not an exact sequence of fixed PD0 ensembles")
    payload = bytearray()
    checksum_sum = 0
    ensemble_count = 0
    for position in range(0, len(data), TOTAL_ENSEMBLE_BYTES):
        if data[position : position + 2] != b"\x7f\x7f":
            raise ValueError(f"{path.name}: missing PD0 header at byte {position}")
        ensemble_bytes = struct.unpack_from("<H", data, position + 2)[0]
        if ensemble_bytes != ENSEMBLE_BYTES:
            raise ValueError(f"{path.name}: ensemble {ensemble_count} has length {ensemble_bytes}")
        data_type_count = data[position + 5]
        if data_type_count != len(OFFSETS):
            raise ValueError(f"{path.name}: ensemble {ensemble_count} has {data_type_count} data types")
        offsets = struct.unpack_from(f"<{data_type_count}H", data, position + 6)
        if offsets != OFFSETS:
            raise ValueError(f"{path.name}: ensemble {ensemble_count} offset table changed")
        block_ids = tuple(struct.unpack_from("<H", data, position + offset)[0] for offset in offsets)
        if block_ids != BLOCK_IDS:
            raise ValueError(f"{path.name}: ensemble {ensemble_count} block sequence changed")
        fixed = position + OFFSETS[0]
        beams = data[fixed + 8]
        cells = data[fixed + 9]
        cell_length_cm = struct.unpack_from("<H", data, fixed + 12)[0]
        blank_after_transmit_cm = struct.unpack_from("<H", data, fixed + 14)[0]
        coordinate_transform = data[fixed + 25]
        if (beams, cells, cell_length_cm, blank_after_transmit_cm, coordinate_transform) != (4, 51, 25, 44, 31):
            raise ValueError(
                f"{path.name}: ensemble {ensemble_count} geometry/coordinate mode changed: "
                f"{(beams, cells, cell_length_cm, blank_after_transmit_cm, coordinate_transform)}"
            )
        ensemble_end = position + ENSEMBLE_BYTES
        stored_checksum = struct.unpack_from("<H", data, ensemble_end)[0]
        computed_checksum = sum(data[position:ensemble_end]) & 0xFFFF
        if stored_checksum != computed_checksum:
            raise ValueError(f"{path.name}: ensemble {ensemble_count} checksum mismatch")
        checksum_sum = (checksum_sum + stored_checksum) & 0xFFFFFFFFFFFFFFFF
        payload.extend(data[position + VELOCITY_OFFSET : position + VELOCITY_END])
        ensemble_count += 1
    if ensemble_count != expected["ensembles"]:
        raise ValueError(f"{path.name}: ensemble count {ensemble_count} != {expected['ensembles']}")
    payload_bytes = bytes(payload)
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    if payload_sha256 != expected["payload_sha256"]:
        raise ValueError(f"{path.name}: decoded velocity SHA-256 changed")
    values = array("h")
    values.frombytes(payload_bytes)
    if values.itemsize != 2:
        raise ValueError("host signed-short width is not 16 bits")
    if sys.byteorder == "big":
        values.byteswap()
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    observed = {
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": len(set(values)),
        "invalid_values": values.count(INVALID_VELOCITY),
        "transitions": transitions,
    }
    for key, value in observed.items():
        if value != expected[key]:
            raise ValueError(f"{path.name}: statistic {key} changed: {value} != {expected[key]}")
    value_count = ensemble_count * VALUES_PER_ENSEMBLE
    return payload_bytes, {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_md5": expected["md5"],
        "ensemble_count": ensemble_count,
        "ensemble_bytes": ENSEMBLE_BYTES,
        "data_type_offsets": list(OFFSETS),
        "block_ids": [f"0x{value:04x}" for value in BLOCK_IDS],
        "depth_cells": CELLS,
        "velocity_components": BEAMS,
        "cell_length_cm": 25,
        "blank_after_transmit_cm": 44,
        "coordinate_transform_byte": 31,
        "coordinate_frame": "earth",
        "value_count": value_count,
        "decoded_bytes": len(payload_bytes),
        "invalid_sentinel": INVALID_VELOCITY,
        "invalid_fraction": observed["invalid_values"] / value_count,
        "checksum_sum_mod_u64": checksum_sum,
        "decoded_sha256": payload_sha256,
        **observed,
    }


def decode_all(download_dir: Path) -> list[tuple[Path, bytes, dict[str, object]]]:
    validate_record_metadata(download_dir)
    decoded = []
    for expected in SOURCES:
        path = download_dir / str(expected["name"])
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
        payload, report = decode_source(path, expected)
        decoded.append((path, payload, report))
    aggregate = hashlib.sha256()
    for _path, payload, _report in decoded:
        aggregate.update(payload)
    if aggregate.hexdigest() != AGGREGATE_SHA256:
        raise ValueError("aggregate decoded payload hash changed")
    return decoded


def inspect_command(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    reports = [report for _path, _payload, report in decoded]
    result = {
        "dataset_id": DATASET_ID,
        "sample_count": len(reports),
        "ensemble_count": sum(int(report["ensemble_count"]) for report in reports),
        "value_count": sum(int(report["value_count"]) for report in reports),
        "total_size_bytes": sum(int(report["decoded_bytes"]) for report in reports),
        "aggregate_payload_sha256": AGGREGATE_SHA256,
        "samples": reports,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    rows = []
    for source, payload, report in decoded:
        stem = source.name.removesuffix(".000")
        ensemble_count = int(report["ensemble_count"])
        output = family_dir / f"{stem}_e{ensemble_count}_c{CELLS}_v{BEAMS}_i16le.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": source.relative_to(args.data_root).as_posix(),
            "source_file": source.name,
            "value_count": int(report["value_count"]),
            "sample_size_bytes": len(payload),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "sample_geometry": "3d_adcp_velocity_field",
            "sample_shape": [ensemble_count, CELLS, BEAMS],
            "sample_axes": ["measurement_ensemble", "depth_cell", "earth_velocity_component"],
            "natural_record_kind": "complete_adcp_recording",
            "invalid_sentinel": INVALID_VELOCITY,
            "invalid_values": report["invalid_values"],
            "minimum": report["minimum"],
            "maximum": report["maximum"],
            "distinct_values": report["distinct_values"],
            "sha256": report["decoded_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "ensemble_count": sum(int(report["ensemble_count"]) for _p, _b, report in decoded),
        "value_count": sum(int(row["value_count"]) for row in rows),
        "total_size_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "aggregate_payload_sha256": AGGREGATE_SHA256,
        "source_inspections": [report for _p, _b, report in decoded],
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: stats[key] for key in (
        "dataset_id", "sample_count", "ensemble_count", "value_count",
        "total_size_bytes", "aggregate_payload_sha256"
    )}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != len(SOURCES):
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs = set()
    aggregate = hashlib.sha256()
    for row, (source, payload, report) in zip(rows, decoded):
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if row.get("source_file") != source.name or not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output mismatch for {source.name}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch for {source.name}")
        if row.get("sample_shape") != [int(report["ensemble_count"]), CELLS, BEAMS]:
            raise SystemExit(f"indexed shape mismatch for {source.name}")
        aggregate.update(payload)
    actual_outputs = {
        path.resolve()
        for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    expected_values = sum(int(report["value_count"]) for _p, _b, report in decoded)
    expected_bytes = sum(len(payload) for _p, payload, _r in decoded)
    expected_ensembles = sum(int(report["ensemble_count"]) for _p, _b, report in decoded)
    if (
        stats.get("sample_count") != len(SOURCES)
        or stats.get("ensemble_count") != expected_ensembles
        or stats.get("value_count") != expected_values
        or stats.get("total_size_bytes") != expected_bytes
        or stats.get("aggregate_payload_sha256") != aggregate.hexdigest()
    ):
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(SOURCES),
        "verified_ensembles": expected_ensembles,
        "verified_values": expected_values,
        "verified_bytes": expected_bytes,
        "aggregate_payload_sha256": aggregate.hexdigest(),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect_command(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
